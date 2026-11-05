"""Desktop settings and append-only CSV QSO storage (no RF I/O).

This layer deliberately does not assume that a decoded CW message is a QSO.
Only callers who confirmed the exchange may append completed records.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Optional

from .contest_store import ContestLedger, StoredQSO

from .core import (
    ALLOWED_BANDS, CALL_RE, CSV_FIELDS, JST, LogValidationError, QSO,
    RST_RE, _exchange_valid, parse_jst,
)


@dataclass(frozen=True)
class DesktopSettings:
    station_callsign: str = ""
    contest_id: str = "ALL_JA"
    sent_nr: str = ""
    band: str = "7"
    contest_start_jst: str = ""  # YYYY-MM-DD HH:MM, JST
    contest_end_jst: str = ""
    civ_port: str = ""

    def checked(self) -> "DesktopSettings":
        call = self.station_callsign.strip().upper()
        nr = self.sent_nr.strip().upper().replace(" ", "")
        contest = self.contest_id.strip().upper()
        band = str(self.band).strip()
        if contest not in ALLOWED_BANDS:
            raise LogValidationError("未対応のコンテストです。")
        if not CALL_RE.fullmatch(call) or not any(c.isalpha() for c in call):
            raise LogValidationError("自局コールサインの形式を確認してください。例：JA1AAA")
        if not _exchange_valid(contest, nr):
            example = "11M" if contest == "ALL_JA" else "100116M"
            raise LogValidationError(f"コンテストナンバーが不正です。例：{example}（RSTは入力不要）")
        if band not in ALLOWED_BANDS[contest]:
            raise LogValidationError("選択したコンテストで使えないバンドです。")
        start = self.contest_start_jst.strip()
        end = self.contest_end_jst.strip()
        if bool(start) != bool(end):
            raise LogValidationError("コンテスト開始と終了は両方入力してください。")
        if start:
            a, b = parse_contest_time(start), parse_contest_time(end)
            if a >= b:
                raise LogValidationError("コンテスト期間の終了は開始より後にしてください。")
            start, end = a.strftime("%Y-%m-%d %H:%M"), b.strftime("%Y-%m-%d %H:%M")
        port = self.civ_port.strip().upper()
        if port and not re.fullmatch(r"COM[1-9][0-9]*", port):
            raise LogValidationError("CI-Vポート名は COM4 のように入力してください。")
        return DesktopSettings(call, contest, nr, band, start, end, port)

    @property
    def contest_window(self) -> tuple[datetime, datetime] | None:
        if not self.contest_start_jst or not self.contest_end_jst:
            return None
        return parse_contest_time(self.contest_start_jst), parse_contest_time(self.contest_end_jst)


def parse_contest_time(value: str) -> datetime:
    try:
        stamp = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    except (TypeError, ValueError) as exc:
        raise LogValidationError("日時は 2026-04-25 21:00 の形式で入力してください。") from exc
    return stamp.replace(tzinfo=JST)


def default_data_directory() -> Path:
    """Persistent directory outside PyInstaller's temporary extraction directory."""
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / "JARL_CW_AutoContest"
    return Path.home() / ".jarl_cw_autocontest"


class DesktopStorage:
    _write_lock = threading.Lock()

    def __init__(self, base_dir: Optional[Path] = None, *, year: Optional[int] = None):
        self.base_dir = Path(base_dir) if base_dir is not None else default_data_directory()
        self.year = year

    @property
    def settings_path(self) -> Path:
        return self.base_dir / "settings.json"

    def load_settings(self) -> DesktopSettings:
        try:
            raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return DesktopSettings()
        except (ValueError, OSError) as exc:
            raise LogValidationError(f"設定ファイルが読み込めません: {exc}") from exc
        mandatory = {"station_callsign", "contest_id", "sent_nr", "band"}
        accepted = mandatory | {"contest_start_jst", "contest_end_jst", "civ_port"}
        if not isinstance(raw, dict) or not mandatory.issubset(raw) or not set(raw).issubset(accepted):
            raise LogValidationError("設定ファイルの項目が不正です。")
        return DesktopSettings(**raw).checked()

    def save_settings(self, settings: DesktopSettings) -> DesktopSettings:
        value = settings.checked()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # Atomic replacement prevents damaged settings on program termination.
        fd, temp_name = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=self.base_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(asdict(value), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.settings_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return value

    def log_path(self, settings: DesktopSettings) -> Path:
        value = settings.checked()
        year = (self.year if self.year is not None else
                value.contest_window[0].year if value.contest_window else datetime.now(JST).year)
        call = re.sub(r"[^A-Z0-9]", "_", value.station_callsign)
        return self.base_dir / "logs" / f"{year}_{value.contest_id}_{call}.csv"

    def append_qso(self, settings: DesktopSettings, qso: QSO,
                   *, frequency_hz: int | None = None) -> Path:
        """Append operator-confirmed QSO; never silently overwrite or score it."""
        value = settings.checked()
        if qso.time_jst.tzinfo is None or qso.time_jst.utcoffset() != JST.utcoffset(None):
            raise LogValidationError("交信時刻はJST (+09:00) で指定してください。")
        if qso.band not in ALLOWED_BANDS[value.contest_id] or qso.mode != "CW":
            raise LogValidationError("バンドまたは電波型式が不正です。")
        if not CALL_RE.fullmatch(qso.callsign) or not any(c.isalpha() for c in qso.callsign):
            raise LogValidationError("相手局コールサインが不正です。")
        if not RST_RE.fullmatch(qso.sent_rst) or not RST_RE.fullmatch(qso.rcvd_rst):
            raise LogValidationError("RSTが不正です。")
        if not _exchange_valid(value.contest_id, qso.sent_nr) or not _exchange_valid(value.contest_id, qso.rcvd_nr):
            raise LogValidationError("送信または受信コンテストナンバーが不正です。")
        if qso.sent_nr != value.sent_nr:
            raise LogValidationError("交信データの送信ナンバーが現在の設定値と異なります。")
        if value.contest_window:
            start, end = value.contest_window
            if not start <= qso.time_jst < end:
                raise LogValidationError("設定されたコンテスト期間外の交信です。")
        path = self.log_path(value)
        with self._write_lock:
            self.ledger.append(value.station_callsign, value.contest_id, path, qso,
                               frequency_hz=frequency_hz)
        return path

    @property
    def ledger(self) -> ContestLedger:
        return ContestLedger(self.base_dir / "contest_log.sqlite3")

    def list_records(self, settings: DesktopSettings) -> list[StoredQSO]:
        value = settings.checked()
        return self.ledger.records(value.station_callsign, value.contest_id, self.log_path(value))

    def list_qsos(self, settings: DesktopSettings) -> list[QSO]:
        return [r.qso for r in self.list_records(settings)]

    def already_worked(self, settings: DesktopSettings, callsign: str,
                       band: str) -> bool | None:
        """None means the contest window is unknown: auto-filter must fail closed."""
        value = settings.checked()
        if value.contest_window is None:
            return None
        if band not in ALLOWED_BANDS[value.contest_id]:
            raise LogValidationError("未対応バンドを交信済み照合には使えません。")
        call = callsign.strip().upper()
        if not CALL_RE.fullmatch(call):
            raise LogValidationError("交信済み照合には完全なコールサインが必要です。")
        self.list_records(value)  # import legacy or externally appended CSV first
        start, end = value.contest_window
        return self.ledger.worked(value.station_callsign, value.contest_id, start, end,
                                  band, call)

    def worked_count(self, settings: DesktopSettings, band: str) -> int | None:
        value = settings.checked()
        if value.contest_window is None:
            return None
        self.list_records(value)
        start, end = value.contest_window
        return self.ledger.worked_count(value.station_callsign, value.contest_id,
                                        start, end, band)


def summarize_live_log(qsos: list[QSO]) -> list[tuple[QSO, str]]:
    """Display-only duplicate indicator; NOT official contest scoring."""
    seen: set[tuple[str, str]] = set()
    by_order: dict[int, str] = {}
    for index, qso in sorted(enumerate(qsos), key=lambda item: (item[1].time_jst, item[0])):
        if not qso.completed:
            by_order[index] = "未完了"
        elif (qso.band, qso.callsign) in seen:
            by_order[index] = "重複候補"
        else:
            by_order[index] = "完了"
            seen.add((qso.band, qso.callsign))
    return [(qso, by_order[index]) for index, qso in enumerate(qsos)]
