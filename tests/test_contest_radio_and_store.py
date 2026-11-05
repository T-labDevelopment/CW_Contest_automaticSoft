from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest

from cwcontest.candidate_selection import evaluate_candidates
from cwcontest.contest_radio import classify_radio, infer_band
from cwcontest.core import JST, QSO, LogValidationError
from cwcontest.desktop_data import DesktopSettings, DesktopStorage


class RadioAndWorkedTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.storage = DesktopStorage(self.base, year=2026)
        self.settings = DesktopSettings("JA1AAA", "ALL_JA", "11M", "7",
                                        "2026-04-25 21:00", "2026-04-26 21:00", "COM4")
        self.qso = QSO(datetime(2026, 4, 25, 21, 30, tzinfo=JST),
                       "7", "CW", "JA2BBB", "599", "11M", "599", "20M", True)
        self.clock = datetime(2026, 4, 25, 22, 0, tzinfo=JST)

    def test_old_settings_json_load_without_new_fields(self):
        self.storage.base_dir.mkdir(parents=True, exist_ok=True)
        self.storage.settings_path.write_text(
            '{"station_callsign":"JA1AAA","contest_id":"ALL_JA","sent_nr":"11M","band":"7"}',
            encoding="utf-8")
        loaded = self.storage.load_settings()
        self.assertIsNone(loaded.contest_window)
        self.assertEqual(loaded.civ_port, "")

    def test_contest_window_required_for_automatic_exclusion(self):
        old_settings = DesktopSettings("JA1AAA", "ALL_JA", "11M", "7")
        self.storage.append_qso(old_settings, self.qso)
        self.assertIsNone(self.storage.already_worked(old_settings, "JA2BBB", "7"))
        self.assertTrue(self.storage.already_worked(self.settings, "JA2BBB", "7"))

    def test_band_switch_and_reboot_persists_worked_index(self):
        self.storage.append_qso(self.settings, self.qso, frequency_hz=7_025_000)
        self.assertTrue(self.storage.already_worked(self.settings, "JA2BBB", "7"))
        self.assertFalse(self.storage.already_worked(self.settings, "JA2BBB", "14"))
        self.assertTrue(DesktopStorage(self.base, year=2026).already_worked(
            self.settings, "JA2BBB", "7"))
        record = self.storage.list_records(self.settings)[0]
        self.assertEqual(record.frequency_hz, 7_025_000)
        self.assertEqual(self.storage.worked_count(self.settings, "7"), 1)

    def test_not_completed_does_not_exclude_and_duplicates_remain(self):
        self.storage.append_qso(self.settings, replace(self.qso, completed=False))
        self.assertFalse(self.storage.already_worked(self.settings, "JA2BBB", "7"))
        self.storage.append_qso(self.settings, replace(self.qso, time_jst=self.qso.time_jst+timedelta(minutes=1)))
        self.storage.append_qso(self.settings, replace(self.qso, time_jst=self.qso.time_jst+timedelta(minutes=2)))
        self.assertTrue(self.storage.already_worked(self.settings, "JA2BBB", "7"))
        self.assertEqual(len(self.storage.list_records(self.settings)), 3)
        self.assertEqual(self.storage.worked_count(self.settings, "7"), 1)

    def test_scope_other_contest_station_period(self):
        self.storage.append_qso(self.settings, self.qso)
        newer = replace(self.settings, contest_start_jst="2027-04-24 21:00",
                        contest_end_jst="2027-04-25 21:00")
        self.assertFalse(self.storage.already_worked(newer, "JA2BBB", "7"))
        other = replace(self.settings, station_callsign="JA3CCC")
        self.assertFalse(self.storage.already_worked(other, "JA2BBB", "7"))
        acag = replace(self.settings, contest_id="ACAG", sent_nr="100116M")
        self.assertFalse(self.storage.already_worked(acag, "JA2BBB", "7"))

    def test_reject_outside_contest_window_and_bad_port(self):
        with self.assertRaises(LogValidationError):
            self.storage.append_qso(self.settings, replace(self.qso,
                  time_jst=datetime(2026, 4, 26, 21, 0, tzinfo=JST)))
        with self.assertRaises(LogValidationError):
            replace(self.settings, civ_port="serial0").checked()
        with self.assertRaises(LogValidationError):
            replace(self.settings, contest_end_jst="").checked()

    def test_import_legacy_csv_and_detect_historical_edits(self):
        old = DesktopStorage(self.base, year=2026)
        # DB created by first append; emulate a legacy install with CSV only.
        old.append_qso(self.settings, self.qso)
        old.ledger.database_path.unlink()
        # Ensure WAL files are not present after closed connections.
        records = self.storage.list_records(self.settings)
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].frequency_hz)
        csv_path = self.storage.log_path(self.settings)
        content = csv_path.read_text(encoding="utf-8-sig")
        csv_path.write_text(content.replace("JA2BBB", "JA3CCC"), encoding="utf-8-sig")
        with self.assertRaisesRegex(LogValidationError, "変更"):
            self.storage.list_records(self.settings)

    def test_frequency_and_mode_mapping(self):
        valid = classify_radio(7_025_000, "CW")
        self.assertEqual(valid.band, "7")
        self.assertTrue(valid.eligible_for("ALL_JA"))
        self.assertTrue(classify_radio(14_060_000, "CW-R").eligible_for("ALL_JA"))
        self.assertFalse(classify_radio(7_075_000, "CW").eligible_for("ALL_JA"))
        self.assertFalse(classify_radio(7_025_000, "USB").eligible_for("ALL_JA"))
        self.assertFalse(classify_radio(7_010_050, "CW").eligible_for("ALL_JA"))
        self.assertFalse(classify_radio(144_070_000, "CW").eligible_for("ALL_JA"))
        self.assertIsNone(infer_band(10_120_000))

    def test_filter_does_not_need_all_calls_decoded(self):
        self.storage.append_qso(self.settings, self.qso)
        radio = classify_radio(7_025_000, "CW")
        decisions = evaluate_candidates(self.storage, self.settings, radio,
                                        ["JA2BBB", "JA3CCC", "JA1?"], now_jst=self.clock)
        self.assertEqual([d.eligible for d in decisions], [False, True, False])
        fourteen = evaluate_candidates(self.storage, self.settings,
                                       classify_radio(14_060_000, "CW"),
                                       ["JA2BBB"], now_jst=self.clock)
        self.assertTrue(fourteen[0].eligible)
        self.assertFalse(evaluate_candidates(self.storage, self.settings, None,
                                            ["JA3CCC"], now_jst=self.clock)[0].eligible)
        self.assertFalse(evaluate_candidates(self.storage, self.settings, radio,
                     ["JA3CCC"], now_jst=datetime(2026, 4, 27, tzinfo=JST))[0].eligible)


if __name__ == "__main__":
    unittest.main()
