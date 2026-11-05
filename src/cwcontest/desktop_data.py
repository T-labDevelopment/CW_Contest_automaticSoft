"""Desktop settings and append-only CSV QSO storage (no RF I/O).

This layer deliberately does not assume that a decoded CW message is a QSO.
Only callers who confirmed the exchange may append completed records.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Optional

from .core import (
    ALLOWED_BANDS, CALL_RE, CSV_FIELDS, JST, LogValidationError, QSO,
    RST_RE, _exchange_valid, read_qsos,
)


@dataclass(frozen=True)
class DesktopSettings:
    station_callsign: str = ""
    contest_id: str = "ALL_JA"
    sent_nr: str = ""
    band: str = "7"

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
        return DesktopSettings(call, contest, nr, band)


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
        if not isinstance(raw, dict) or set(raw) != {
            "station_callsign", "contest_id", "sent_nr", "band"
        }:
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
        year = self.year if self.year is not None else datetime.now(JST).year
        call = re.sub(r"[^A-Z0-9]", "_", value.station_callsign)
        return self.base_dir / "logs" / f"{year}_{value.contest_id}_{call}.csv"

    def append_qso(self, settings: DesktopSettings, qso: QSO) -> Path:
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
        path = self.log_path(value)
        with self._write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                # Do not append to a corrupt/incompatible file.
                read_qsos(path)
            with path.open("a", encoding="utf-8-sig" if not path.exists() else "utf-8", newline="") as handle:
                writer = csv.writer(handle)
                if handle.tell() == 0:
                    writer.writerow(CSV_FIELDS)
                writer.writerow([
                    qso.time_jst.isoformat(), qso.band, qso.mode, qso.callsign,
                    qso.sent_rst, qso.sent_nr, qso.rcvd_rst, qso.rcvd_nr,
                    str(qso.completed).lower(),
                ])
                handle.flush()
                os.fsync(handle.fileno())
        return path

    def list_qsos(self, settings: DesktopSettings) -> list[QSO]:
        path = self.log_path(settings)
        return read_qsos(path) if path.is_file() else []


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
