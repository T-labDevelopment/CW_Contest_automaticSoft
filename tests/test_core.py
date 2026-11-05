import copy
import unittest
from pathlib import Path
from cwcontest.core import read_config, read_qsos, score_and_audit, jarlelog_r21, excel_csv, LogValidationError

ROOT = Path(__file__).resolve().parents[1]


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.config = read_config(ROOT / "examples/allja2026_demo.json")
        self.qsos = read_qsos(ROOT / "examples/allja2026_demo.csv")

    def test_official_scoring_and_duplicate_retained(self):
        a = score_and_audit(self.config, self.qsos)
        self.assertEqual(a["points"], 3)
        self.assertEqual(a["multipliers"], 2)
        self.assertEqual(a["total_score"], 6)
        self.assertEqual(a["dupes"], 1)
        self.assertEqual(a["incomplete_qsos"], 1)
        self.assertEqual(a["complete_qsos"], 4)

    def test_jarl_r21_format(self):
        a = score_and_audit(self.config, self.qsos)
        text = jarlelog_r21(self.config, a)
        self.assertIn("<SUMMARYSHEET VERSION=R2.1>", text)
        self.assertIn("<TOTALSCORE>6</TOTALSCORE>", text)
        self.assertIn("<OATH>", text)
        self.assertIn("2026-04-25 21:10 7 CW JA2BBB 599 10M 599 20M", text)
        self.assertEqual(text.count("2026-04-25 "), 4)
        self.assertIn("</LOGSHEET>", text)

    def test_excel_review_contains_incomplete(self):
        text = excel_csv(score_and_audit(self.config, self.qsos))
        self.assertIn("INCOMPLETE", text)
        self.assertIn("DUPE", text)

    def test_no_late_qso(self):
        from dataclasses import replace
        from datetime import timedelta
        new = replace(self.qsos[0], time_jst=self.qsos[0].time_jst + timedelta(days=3))
        with self.assertRaises(LogValidationError):
            score_and_audit(self.config, [new])

    def test_bad_exchange(self):
        from dataclasses import replace
        bad = replace(self.qsos[0], rcvd_nr="991M")
        with self.assertRaises(LogValidationError):
            score_and_audit(self.config, [bad])

    def test_unordered_csv_uses_qso_time_for_duplicates(self):
        from dataclasses import replace
        older = replace(self.qsos[0], time_jst=self.qsos[0].time_jst.replace(minute=5))
        later = replace(self.qsos[0], time_jst=self.qsos[0].time_jst.replace(minute=55))
        a = score_and_audit(self.config, [later, older])
        self.assertEqual(a["dupes"], 1)
        self.assertEqual(a["rows"][0]["qso"].time_jst.minute, 5)
        self.assertEqual(a["rows"][0]["points"], 1)
        self.assertEqual(a["rows"][1]["points"], 0)

    def test_contest_end_exactly_is_excluded(self):
        from dataclasses import replace
        from cwcontest.core import parse_jst
        q = replace(self.qsos[0], time_jst=parse_jst(self.config["end_jst"]))
        with self.assertRaises(LogValidationError):
            score_and_audit(self.config, [q])

    def test_out_of_category_logging(self):
        from dataclasses import replace
        config = copy.deepcopy(self.config)
        config["scoring_bands"] = ["14"]
        data = score_and_audit(config, self.qsos)
        self.assertEqual(data["total_score"], 0)
        self.assertEqual(data["complete_qsos"], 4)


if __name__ == "__main__":
    unittest.main()
