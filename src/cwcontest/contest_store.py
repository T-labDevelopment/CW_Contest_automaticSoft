"""Persistent SQLite QSO ledger and worked-station index.

Original CSV log rows are retained, and the legacy CSV is mirrored for the
existing contest scoring/export tool. The SQLite database is the internal
queryable record; in-place edits to previously imported CSV rows are rejected.
"""
from __future__ import annotations

import csv
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3

from .core import CSV_FIELDS, QSO, LogValidationError, read_qsos


@dataclass(frozen=True)
class StoredQSO:
    id: int
    qso: QSO
    frequency_hz: int | None


def qso_csv_values(qso: QSO) -> list[str]:
    return [qso.time_jst.isoformat(), qso.band, qso.mode, qso.callsign,
            qso.sent_rst, qso.sent_nr, qso.rcvd_rst, qso.rcvd_nr,
            str(qso.completed).lower()]


def fingerprint(qso: QSO) -> str:
    return hashlib.sha256("\x1f".join(qso_csv_values(qso)).encode("utf-8")).hexdigest()


class ContestLedger:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.database_path, timeout=5.0)
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("""CREATE TABLE IF NOT EXISTS qsos (
            id INTEGER PRIMARY KEY,
            station_call TEXT NOT NULL,
            contest_id TEXT NOT NULL,
            time_jst TEXT NOT NULL,
            band TEXT NOT NULL,
            mode TEXT NOT NULL,
            callsign TEXT NOT NULL,
            sent_rst TEXT NOT NULL,
            sent_nr TEXT NOT NULL,
            rcvd_rst TEXT NOT NULL,
            rcvd_nr TEXT NOT NULL,
            completed INTEGER NOT NULL,
            frequency_hz INTEGER,
            source_path TEXT NOT NULL,
            source_row INTEGER NOT NULL,
            source_hash TEXT NOT NULL,
            imported_utc TEXT NOT NULL,
            UNIQUE(source_path, source_row)
        )""")
        con.execute("""CREATE INDEX IF NOT EXISTS worked_idx ON qsos
            (station_call, contest_id, band, callsign, completed, time_jst)""")
        return con

    @staticmethod
    def _insert(con: sqlite3.Connection, station: str, contest: str, path: Path,
                index: int, qso: QSO, frequency_hz: int | None) -> None:
        con.execute("""INSERT INTO qsos (
            station_call,contest_id,time_jst,band,mode,callsign,sent_rst,sent_nr,
            rcvd_rst,rcvd_nr,completed,frequency_hz,source_path,source_row,
            source_hash,imported_utc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (station, contest, qso.time_jst.isoformat(), qso.band, qso.mode,
             qso.callsign, qso.sent_rst, qso.sent_nr, qso.rcvd_rst, qso.rcvd_nr,
             int(qso.completed), frequency_hz, str(path.resolve()), index,
             fingerprint(qso), datetime.now(timezone.utc).isoformat()))

    @classmethod
    def import_csv(cls, con: sqlite3.Connection, station: str, contest: str, path: Path) -> int:
        if not path.is_file():
            return 0
        qsos = read_qsos(path)
        source = str(path.resolve())
        known = dict(con.execute(
            "SELECT source_row,source_hash FROM qsos WHERE source_path=?", (source,)).fetchall())
        if any(row >= len(qsos) for row in known):
            raise LogValidationError("CSVの既存行が削除されています。原本を復旧してください。")
        imported = 0
        for index, qso in enumerate(qsos):
            digest = fingerprint(qso)
            if index in known:
                if known[index] != digest:
                    raise LogValidationError(f"CSVの既存行 {index + 2} が変更されています。履歴は改変できません。")
                continue
            cls._insert(con, station, contest, path, index, qso, None)
            imported += 1
        return imported

    def import_only(self, station: str, contest: str, path: Path) -> int:
        with closing(self.connect()) as con, con:
            return self.import_csv(con, station, contest, path)

    def append(self, station: str, contest: str, path: Path, qso: QSO,
               frequency_hz: int | None = None) -> None:
        if frequency_hz is not None and (not isinstance(frequency_hz, int) or frequency_hz <= 0):
            raise LogValidationError("記録周波数が不正です。")
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as con, con:
            self.import_csv(con, station, contest, path)
            count = (con.execute("SELECT COUNT(*) FROM qsos WHERE source_path=?",
                                 (str(path.resolve()),)).fetchone()[0])
            # CSV is kept in original core format. sqlite3 is the QSO record.
            self._insert(con, station, contest, path, count, qso, frequency_hz)
            # The transaction remains open while mirroring the CSV, so a failed
            # mirror cannot falsely mark the QSO as committed in SQLite.
            new_file = not path.exists()
            with path.open("a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as handle:
                writer = csv.writer(handle)
                if new_file:
                    writer.writerow(CSV_FIELDS)
                writer.writerow(qso_csv_values(qso))
                handle.flush()
                import os
                os.fsync(handle.fileno())

    def records(self, station: str, contest: str, path: Path) -> list[StoredQSO]:
        with closing(self.connect()) as con, con:
            self.import_csv(con, station, contest, path)
            rows = con.execute("""SELECT id,time_jst,band,mode,callsign,sent_rst,sent_nr,
                            rcvd_rst,rcvd_nr,completed,frequency_hz FROM qsos
                            WHERE source_path=? ORDER BY source_row""", (str(path.resolve()),)).fetchall()
        from .core import parse_jst
        return [StoredQSO(row[0], QSO(parse_jst(row[1]), row[2], row[3], row[4],
                                      row[5], row[6], row[7], row[8], bool(row[9])), row[10])
                for row in rows]

    def worked(self, station: str, contest: str, start_jst: datetime, end_jst: datetime,
               band: str, callsign: str) -> bool:
        with closing(self.connect()) as con, con:
            return con.execute("""SELECT 1 FROM qsos WHERE station_call=? AND contest_id=?
                AND band=? AND callsign=? AND completed=1
                AND time_jst>=? AND time_jst<? LIMIT 1""",
                (station, contest, band, callsign.upper(),
                 start_jst.isoformat(), end_jst.isoformat())).fetchone() is not None

    def worked_count(self, station: str, contest: str, start_jst: datetime,
                     end_jst: datetime, band: str) -> int:
        with closing(self.connect()) as con, con:
            return con.execute("""SELECT COUNT(DISTINCT callsign) FROM qsos
                WHERE station_call=? AND contest_id=? AND band=? AND completed=1
                AND time_jst>=? AND time_jst<?""",
                (station, contest, band,
                 start_jst.isoformat(), end_jst.isoformat())).fetchone()[0]
