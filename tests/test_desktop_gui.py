"""Runs on Windows desktop, or on CI with xvfb-run."""
from datetime import datetime
from pathlib import Path
import tempfile
import tkinter as tk
import unittest

from cwcontest.core import JST, QSO
from cwcontest.desktop import DesktopApp
from cwcontest.desktop_data import DesktopStorage


class DesktopGuiTests(unittest.TestCase):
    def setUp(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"no graphical display: {exc}")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = root
        self.addCleanup(lambda: root.destroy() if root.winfo_exists() else None)
        self.app = DesktopApp(root, DesktopStorage(Path(self.temp.name), year=2026))
        self.root.update()

    def test_separate_log_window_and_settings(self):
        self.assertIsNotNone(self.app.log_window)
        self.assertNotEqual(self.app.root, self.app.log_window)
        self.assertEqual(len(self.app.tree.get_children()), 0)
        self.assertIn("設定画面", self.app.log_summary_var.get())

    def test_settings_save_and_live_log_refresh(self):
        self.app.call_var.set("JA1AAA")
        self.app.nr_var.set("11M")
        self.app._on_save()
        self.assertEqual(self.app.settings.station_callsign, "JA1AAA")
        q = QSO(datetime(2026,4,25,21,10,tzinfo=JST), "7", "CW", "JA2BBB", "599", "11M", "599", "20M", True)
        self.app.storage.append_qso(self.app.settings, q)
        self.app._refresh_log()
        self.assertEqual(len(self.app.tree.get_children()), 1)
        first = self.app.tree.item(self.app.tree.get_children()[0])["values"]
        self.assertEqual(first[3], "JA2BBB")
        self.assertIn("計 1 件", self.app.log_summary_var.get())

    def test_external_csv_change_appears_on_periodic_refresh(self):
        self.app.call_var.set("JA1AAA")
        self.app.nr_var.set("11M")
        self.app._on_save()
        q = QSO(datetime(2026,4,25,21,10,tzinfo=JST), "7", "CW", "JA3CCC", "599", "11M", "599", "25M", True)
        self.app.storage.append_qso(self.app.settings, q)
        self.root.after(1150, self.root.quit)
        self.root.mainloop()
        self.assertEqual(len(self.app.tree.get_children()), 1)

    def test_radio_frequency_auto_switches_and_invalidates_previous_candidate(self):
        from cwcontest.contest_radio import classify_radio
        from cwcontest.radio_monitor import RadioUpdate
        self.app.call_var.set("JA1AAA")
        self.app.nr_var.set("11M")
        self.app.start_var.set("2026-04-25 21:00")
        self.app.end_var.set("2026-04-26 21:00")
        self.app._on_save()
        self.app.selected_station = "JA2BBB"
        self.app.radio_events.put(RadioUpdate(classify_radio(7_025_000, "CW")))
        self.app._poll_radio_events()
        self.assertIn("7.025000", self.app.radio_var.get())
        self.app.selected_station = "JA2BBB"
        self.app.radio_events.put(RadioUpdate(classify_radio(14_060_000, "CW")))
        self.app._poll_radio_events()
        self.assertIn("14.060000", self.app.radio_var.get())
        self.assertIsNone(self.app.selected_station)
        self.app.radio_events.put(RadioUpdate(None, "通信切断"))
        self.app._poll_radio_events()
        self.assertIsNone(self.app.radio_state)
        self.assertIn("通信切断", self.app.radio_var.get())

    def test_receive_candidate_shows_in_separate_log_and_can_copy(self):
        from cwcontest.receive_monitor import ReceiveUpdate
        self.app.call_var.set("JA1AAA")
        self.app.nr_var.set("11M")
        self.app._on_save()
        self.app.rx_events.put(ReceiveUpdate("CQ JA2BBB 599", 22.0, origin="WAV"))
        self.app._poll_rx_events()
        self.assertEqual(len(self.app.candidate_tree.get_children()), 1)
        row = self.app.candidate_tree.get_children()[0]
        self.app.candidate_tree.selection_set(row)
        self.app._choose_candidate()
        self.assertEqual(self.app.other_call_var.get(), "JA2BBB")
        self.assertEqual(len(self.app.tree.get_children()), 0)  # never auto-log

    def test_band_switch_clears_receive_candidates(self):
        from cwcontest.contest_radio import classify_radio
        from cwcontest.radio_monitor import RadioUpdate
        self.app.candidate_tracker.observe("JA2BBB")
        self.app.radio_events.put(RadioUpdate(classify_radio(7_025_000, "CW")))
        self.app._poll_radio_events()
        self.app.radio_events.put(RadioUpdate(classify_radio(14_060_000, "CW")))
        self.app._poll_radio_events()
        self.assertEqual(self.app.candidate_tracker.candidates(), [])

    def test_close_reopen_log_still_refreshes(self):
        self.app._close_log_window()
        self.assertIsNone(self.app.log_window)
        self.app.open_log_window()
        self.assertIsNotNone(self.app.tree)


if __name__ == "__main__":
    unittest.main()

class RadioModelUiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"no graphical display: {exc}")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: self.root.destroy() if self.root.winfo_exists() else None)
        self.app = DesktopApp(self.root, DesktopStorage(Path(self.tmp.name)))
        self.root.update()

    def test_bluetooth_button_disabled_for_ic7300_enabled_for_ic705(self):
        self.assertEqual(str(self.app.bt_button.cget("state")), "disabled")
        self.app.radio_model_var.set("IC-705")
        self.app._on_radio_model_change()
        self.assertEqual(str(self.app.bt_button.cget("state")), "normal")
        self.app.civ_transport_var.set("Bluetooth")
        self.app.radio_model_var.set("IC-9700")
        self.app._on_radio_model_change()
        self.assertEqual(str(self.app.bt_button.cget("state")), "disabled")
        self.assertEqual(self.app.civ_transport_var.get(), "USB")

    def test_identification_handshake_does_not_clear_state_on_recognition(self):
        from cwcontest.radio_monitor import RadioUpdate
        from cwcontest.contest_radio import classify_radio
        self.app.radio_events.put(RadioUpdate(None, identified_model="IC-7300", detected_id=0x94))
        self.app._poll_radio_events()
        self.assertEqual(self.app.verified_radio_model, "IC-7300")
        self.app.radio_events.put(RadioUpdate(classify_radio(7_025_000, "CW"),
                                              identified_model="IC-7300", detected_id=0x94))
        self.app._poll_radio_events()
        self.assertIn("7.025", self.app.radio_var.get())
        self.app.radio_events.put(RadioUpdate(None, error="CI-V停止: ID mismatch"))
        self.app._poll_radio_events()
        self.assertIsNone(self.app.verified_radio_model)
