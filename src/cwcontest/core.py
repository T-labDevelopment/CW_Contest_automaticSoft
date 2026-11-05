"""JARL ALL JA / 全市全郡 (CW) のオフラインログ集計・出力。

標準ライブラリのみで動作。実無線機の送信・受信は実装していない。
公式に確認済みの一般規約とログ形式を参考にした検証用プロトタイプ。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
import re
from typing import Any

JST = timezone(timedelta(hours=9))
JARL_OATH = (
    "私は、JARL制定のコンテスト規約および電波法令にしたがい運用した結果、"
    "ここに提出するサマリーシートおよびログシートなどが事実と相違ないものであることを、"
    "私の名誉において誓います。"
)
ALLOWED_BANDS = {
    "ALL_JA": {"1.9", "3.5", "7", "14", "21", "28", "50"},
    "ACAG": {"1.9", "3.5", "7", "14", "21", "28", "50", "144", "430"},
}
CSV_FIELDS = [
    "time_jst", "band", "mode", "callsign", "sent_rst", "sent_nr",
    "rcvd_rst", "rcvd_nr", "completed",
]
CALL_RE = re.compile(r"^[A-Z0-9]{1,6}[0-9][A-Z0-9]{1,5}(?:/[A-Z0-9]{1,4})?$")
RST_RE = re.compile(r"^[1-5][1-9][1-9]$")


class LogValidationError(ValueError):
    pass


@dataclass(frozen=True)
class QSO:
    time_jst: datetime
    band: str
    mode: str
    callsign: str
    sent_rst: str
    sent_nr: str
    rcvd_rst: str
    rcvd_nr: str
    completed: bool

    @property
    def multiplier(self) -> str:
        return self.rcvd_nr[:-1]


def read_config(path: str | Path) -> dict[str, Any]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    required = [
        "contest_id", "contest_name", "start_jst", "end_jst", "category_code",
        "station_callsign", "scoring_bands", "address", "name", "email",
        "power_w", "date_signed", "signature",
    ]
    missing = [name for name in required if name not in config or config[name] in (None, "")]
    if missing:
        raise LogValidationError("設定の必須項目がありません: " + ", ".join(missing))
    if config["contest_id"] not in ALLOWED_BANDS:
        raise LogValidationError("未実装のコンテスト: " + str(config["contest_id"]))
    if not set(config["scoring_bands"]).issubset(ALLOWED_BANDS[config["contest_id"]]):
        raise LogValidationError("scoring_bands に非対応バンドが含まれます")
    if not config["scoring_bands"]:
        raise LogValidationError("scoring_bands は空にできません")
    if not re.fullmatch(r"[A-Z0-9/]+", config["station_callsign"]):
        raise LogValidationError("station_callsign が不正です")
    if not re.fullmatch(r"[A-Z0-9]+", config["category_code"]):
        raise LogValidationError("category_code が不正です")
    if not isinstance(config["power_w"], (int, float)) or config["power_w"] <= 0:
        raise LogValidationError("power_w が不正です")
    start, end = parse_jst(config["start_jst"]), parse_jst(config["end_jst"])
    if start >= end:
        raise LogValidationError("start_jst は end_jst より前でなければなりません")
    for key in ("contest_name", "address", "name", "email", "date_signed", "signature"):
        if any(mark in str(config[key]) for mark in ("<", ">", "\n", "\r")):
            raise LogValidationError(f"{key} に使用できない文字が含まれます")
    return config


def parse_jst(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise LogValidationError("日時がISO8601形式ではありません: " + raw) from exc
    if value.tzinfo is None or value.utcoffset() != timedelta(hours=9):
        raise LogValidationError("日時は +09:00 のタイムゾーン付きJSTで指定してください: " + raw)
    return value.astimezone(JST)


def read_qsos(path: str | Path) -> list[QSO]:
    qsos = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_FIELDS:
            raise LogValidationError("CSV列名・順序が不正です: " + str(reader.fieldnames))
        for line, row in enumerate(reader, start=2):
            try:
                completed = row["completed"].strip().lower()
                if completed not in ("true", "false"):
                    raise LogValidationError("completed は true または false")
                qso = QSO(
                    time_jst=parse_jst(row["time_jst"].strip()),
                    band=row["band"].strip(),
                    mode=row["mode"].strip().upper(),
                    callsign=row["callsign"].strip().upper(),
                    sent_rst=row["sent_rst"].strip(),
                    sent_nr=row["sent_nr"].strip().upper(),
                    rcvd_rst=row["rcvd_rst"].strip(),
                    rcvd_nr=row["rcvd_nr"].strip().upper(),
                    completed=(completed == "true"),
                )
                qsos.append(qso)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                raise LogValidationError(f"CSV {line}行目: {exc}") from exc
    return qsos


def _exchange_valid(contest_id: str, value: str) -> bool:
    if not re.fullmatch(r"[0-9]+[HMLP]", value):
        return False
    location = value[:-1]
    if contest_id == "ALL_JA":
        return (len(location) == 2 and 2 <= int(location) <= 48) or (
            len(location) == 3 and 101 <= int(location) <= 114
        )
    # 全市全郡の市郡区コードはデータベースでの照合が未実装。
    # 現段階では数字長の概略チェックのみ（実在するコードかは未確認）。
    if contest_id == "ACAG":
        return 4 <= len(location) <= 6
    return False


def score_and_audit(config: dict[str, Any], qsos: list[QSO]) -> dict[str, Any]:
    contest_id = config["contest_id"]
    start = parse_jst(config["start_jst"])
    end = parse_jst(config["end_jst"])
    seen_calls: set[tuple[str, str]] = set()
    multipliers: set[tuple[str, str]] = set()
    rows = []
    errors = []
    dupes = 0
    counted = 0
    incomplete = 0
    scoring = set(config["scoring_bands"])
    # 重複の得点採用は実際の交信時刻順とする（CSVの行順に依存しない）。
    ordered = sorted(enumerate(qsos, start=2), key=lambda item: (item[1].time_jst, item[0]))
    for index, q in ordered:
        if not q.completed:
            incomplete += 1
            rows.append({"qso": q, "duplicate": False, "points": 0, "status": "INCOMPLETE"})
            continue
        problems = []
        if not (start <= q.time_jst < end):
            problems.append("コンテスト期間外")
        if q.mode != "CW":
            problems.append("非CWモード")
        if q.band not in ALLOWED_BANDS[contest_id]:
            problems.append("規約対象外バンド")
        if not CALL_RE.fullmatch(q.callsign):
            problems.append("コールサイン形式不明")
        if not RST_RE.fullmatch(q.sent_rst) or not RST_RE.fullmatch(q.rcvd_rst):
            problems.append("RST形式不正")
        if not _exchange_valid(contest_id, q.sent_nr):
            problems.append("送信ナンバー形式不正")
        if not _exchange_valid(contest_id, q.rcvd_nr):
            problems.append("受信ナンバー形式不正")
        if problems:
            errors.append(f"CSV {index}行目: " + " / ".join(problems))
            rows.append({"qso": q, "duplicate": False, "points": 0, "status": "ERROR"})
            continue
        key = (q.band, q.callsign)
        duplicate = key in seen_calls
        seen_calls.add(key)
        eligible = q.band in scoring
        points = int(not duplicate and eligible)
        if duplicate:
            dupes += 1
        if points:
            counted += 1
            multipliers.add((q.band, q.multiplier))
        rows.append({"qso": q, "duplicate": duplicate, "points": points,
                     "status": "DUPE" if duplicate else ("OK" if eligible else "OUT_OF_CATEGORY")})
    if errors:
        raise LogValidationError("ログ検証エラー:\n" + "\n".join(errors))
    return {"rows": rows, "total_qsos": len(qsos), "complete_qsos": sum(q.completed for q in qsos),
            "incomplete_qsos": incomplete, "dupes": dupes, "points": counted,
            "multipliers": len(multipliers), "total_score": counted * len(multipliers)}


def _tag(name: str, value: Any) -> str:
    return f"<{name}>{escape(str(value), quote=False)}</{name}>"


def jarlelog_r21(config: dict[str, Any], audit: dict[str, Any]) -> str:
    """JARL国内CW向け R2.1 ログを生成。署名行為は呼び出し側が確認すること。"""
    fields = [
        ("CONTESTNAME", config["contest_name"]),
        ("CATEGORYCODE", config["category_code"]),
        ("CALLSIGN", config["station_callsign"]),
        ("TOTALSCORE", audit["total_score"]),
        ("ADDRESS", config["address"]),
        ("NAME", config["name"]),
        ("EMAIL", config["email"]),
        ("POWER", config["power_w"]),
    ]
    for key, tag in (("opplace", "OPPLACE"), ("fdcoeff", "FDCOEFF"),
                     ("powersupply", "POWERSUPPLY"), ("multioplist", "MULTIOPLIST")):
        if config.get(key) not in (None, ""):
            fields.append((tag, config[key]))
    fields += [("OATH", JARL_OATH), ("DATE", config["date_signed"]),
               ("SIGNATURE", config["signature"])]
    lines = ["<SUMMARYSHEET VERSION=R2.1>"]
    lines += [_tag(key, value) for key, value in fields]
    lines += ["</SUMMARYSHEET>", '<LOGSHEET TYPE="CWContestPrototype">']
    for row in audit["rows"]:
        q = row["qso"]
        if not q.completed:
            continue
        lines.append(
            f"{q.time_jst:%Y-%m-%d} {q.time_jst:%H:%M} {q.band} CW {q.callsign} "
            f"{q.sent_rst} {q.sent_nr} {q.rcvd_rst} {q.rcvd_nr}"
        )
    lines.append("</LOGSHEET>")
    return "\n".join(lines) + "\n"


def excel_csv(audit: dict[str, Any]) -> str:
    import io
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["time_jst", "band", "mode", "callsign", "sent_rst", "sent_nr",
                     "rcvd_rst", "rcvd_nr", "completed", "status", "points"])
    for row in audit["rows"]:
        q = row["qso"]
        writer.writerow([q.time_jst.isoformat(), q.band, q.mode, q.callsign, q.sent_rst,
                         q.sent_nr, q.rcvd_rst, q.rcvd_nr, str(q.completed).lower(),
                         row["status"], row["points"]])
    return out.getvalue()
