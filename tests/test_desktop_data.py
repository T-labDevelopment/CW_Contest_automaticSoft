import csv
from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from cwcontest.core import CSV_FIELDS, JST, LogValidationError, QSO
from cwcontest.desktop_data import DesktopSettings, DesktopStorage, summarize_live_log


class DesktopDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.storage = DesktopStorage(Path(self.temp.name), year=2026)
        self.settings = DesktopSettings("JA1AAA", "ALL_JA", "11M", "7")

    def sample_qso(self, **changes):
        base = QSO(datetime(2026, 4, 25, 21, 10, tzinfo=JST), "7", "CW",
                   "JA2BBB", "599", "11M", "599", "20M", True)
        return replace(base, **changes)

    def test_new_install_never_invents_operator_information(self):
        result = self.storage.load_settings()
        self.assertEqual(result.station_callsign, "")
        self.assertEqual(result.sent_nr, "")

    def test_save_and_load_normalization(self):
        source = DesktopSettings(" ja1aaa ", "ALL_JA", " 11m ", "7")
        saved = self.storage.save_settings(source)
        self.assertEqual(saved.station_callsign, "JA1AAA")
        self.assertEqual(saved.sent_nr, "11M")
        self.assertEqual(self.storage.load_settings(), saved)
        self.assertEqual(json.loads(self.storage.settings_path.read_text())["sent_nr"], "11M")

    def test_contest_specific_exchange_validation(self):
        self.assertEqual(self.settings.checked(), self.settings)
        self.assertEqual(DesktopSettings("JA1AAA", "ACAG", "100116M", "7").checked().sent_nr, "100116M")
        for invalid in (DesktopSettings("", "ALL_JA", "11M", "7"),
                        DesktopSettings("JA1AAA", "ALL_JA", "100116M", "7"),
                        DesktopSettings("JA1AAA", "ACAG", "11M", "7"),
                        DesktopSettings("JA1AAA", "ALL_JA", "11M", "430")):
            with self.subTest(invalid=invalid), self.assertRaises(LogValidationError):
                invalid.checked()

    def test_append_creates_original_core_csv_and_reads(self):
        self.storage.save_settings(self.settings)
        file = self.storage.append_qso(self.settings, self.sample_qso())
        self.assertEqual(file.name, "2026_ALL_JA_JA1AAA.csv")
        with file.open(encoding="utf-8-sig", newline="") as f:
            self.assertEqual(csv.reader(f).__next__(), CSV_FIELDS)
        self.assertEqual(self.storage.list_qsos(self.settings), [self.sample_qso()])

    def test_appending_multiple_qsos_keeps_previous_rows(self):
        self.storage.append_qso(self.settings, self.sample_qso())
        self.storage.append_qso(self.settings, self.sample_qso(time_jst=datetime(2026, 4, 25, 21, 20, tzinfo=JST)))
        rows = self.storage.list_qsos(self.settings)
        self.assertEqual(len(rows), 2)
        self.assertEqual([v for q, v in summarize_live_log(rows)], ["完了", "重複候補"])

    def test_incomplete_not_eligible_for_duplicate(self):
        q = self.sample_qso()
        rows = [replace(q, completed=False), replace(q, time_jst=q.time_jst + timedelta(minutes=1))]
        self.assertEqual([v for _, v in summarize_live_log(rows)], ["未完了", "完了"])

    def test_no_log_on_invalid_exchange(self):
        with self.assertRaises(LogValidationError):
            self.storage.append_qso(self.settings, self.sample_qso(rcvd_nr="?"))
        self.assertFalse(self.storage.log_path(self.settings).exists())

    def test_unchanged_old_exchange_when_setting_changes(self):
        self.storage.append_qso(self.settings, self.sample_qso())
        newer = DesktopSettings("JA1AAA", "ALL_JA", "12M", "7")
        self.storage.save_settings(newer)
        self.assertEqual(self.storage.list_qsos(newer)[0].sent_nr, "11M")
        with self.assertRaises(LogValidationError):
            self.storage.append_qso(newer, self.sample_qso())

    def test_independent_logs_per_station_and_contest(self):
        a = self.storage.log_path(self.settings)
        b = self.storage.log_path(DesktopSettings("JA2BBB", "ALL_JA", "20M", "7"))
        c = self.storage.log_path(DesktopSettings("JA1AAA", "ACAG", "100116M", "7"))
        self.assertEqual(len({a, b, c}), 3)

    def test_corrupt_settings_must_not_be_replaced_silently(self):
        self.storage.base_dir.mkdir(exist_ok=True)
        self.storage.settings_path.write_text("not json", encoding="utf-8")
        with self.assertRaises(LogValidationError):
            self.storage.load_settings()

    def test_corrupt_csv_prevents_appending(self):
        target = self.storage.log_path(self.settings)
        target.parent.mkdir(parents=True)
        target.write_text("invalid header\n", encoding="utf-8")
        with self.assertRaises(LogValidationError):
            self.storage.append_qso(self.settings, self.sample_qso())
        self.assertEqual(target.read_text(), "invalid header\n")


if __name__ == "__main__":
    unittest.main()
