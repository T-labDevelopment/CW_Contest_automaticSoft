from queue import Queue
from unittest.mock import patch
import unittest

from cwcontest.radio_monitor import RadioMonitor


class MockRadio:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read_transceiver_id(self):
        self.calls.append("19 00")
        return 0x94

    def read_frequency_hz(self):
        self.calls.append("03")
        return 7_025_000

    def read_mode(self):
        self.calls.append("04")
        return "CW"


class MonitorTests(unittest.TestCase):
    def test_only_reads_frequency_and_mode(self):
        events = Queue()
        fake = MockRadio()
        monitor = RadioMonitor("COM7", events, poll_seconds=0.5)
        with patch("cwcontest.radio_monitor.IC7300.open_port", return_value=fake):
            monitor.start()
            handshake = events.get(timeout=2.0)
            result = events.get(timeout=2.0)
            monitor.stop()
            monitor.thread.join(timeout=2.0)
        self.assertEqual(result.state.band, "7")
        self.assertEqual(result.state.mode, "CW")
        self.assertEqual(fake.calls, ["19 00", "03", "04"])
        self.assertFalse(monitor.thread.is_alive())

    def test_read_failure_drops_valid_state(self):
        class BadRadio(MockRadio):
            def read_mode(self):
                raise RuntimeError("mock timeout")

        events = Queue()
        monitor = RadioMonitor("COM7", events)
        with patch("cwcontest.radio_monitor.IC7300.open_port", return_value=BadRadio()):
            monitor.start()
            handshake = events.get(timeout=2.0)
            update = events.get(timeout=2.0)
            monitor.thread.join(timeout=2.0)
        self.assertIsNone(update.state)
        self.assertIn("mock timeout", update.error)

if __name__ == "__main__":
    unittest.main()

class IdentificationGateTests(unittest.TestCase):
    def test_wrong_id_never_polls_frequency(self):
        class WrongModel(MockRadio):
            def read_transceiver_id(self):
                self.calls.append("19 00")
                return 0xA4
        wire = WrongModel()
        events = Queue()
        monitor = RadioMonitor("COM7", events, model="IC-7300", poll_seconds=0.5)
        with patch("cwcontest.radio_monitor.IC7300.open_port", return_value=wire):
            monitor.start()
            result = events.get(timeout=2)
            monitor.thread.join(timeout=2)
        self.assertIsNone(result.state)
        self.assertIn("ID不一致", result.error)
        self.assertEqual(wire.calls, ["19 00"])

    def test_bluetooth_forbidden_before_port_open(self):
        with self.assertRaises(ValueError):
            RadioMonitor("COM7", Queue(), model="IC-7300", transport="Bluetooth")
