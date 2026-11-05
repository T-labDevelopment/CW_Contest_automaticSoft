"""Static CI-V model/transport capability tests: zero physical RF output."""
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest

from cwcontest.ic7300 import CIVError, IC7300, make_frame
from cwcontest.icom_models import (
    MODELS, BY_ID, BY_NAME, READ_COMMANDS, model_for_id,
    parse_address_override, validate_transport,
)
from cwcontest.desktop_data import DesktopSettings, DesktopStorage
from cwcontest.core import LogValidationError


class CIVOddAddressWire:
    def __init__(self, address=0x62, response_id=0xA4):
        self.address = address
        self.response_id = response_id
        self.output = bytearray()
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        if data[2] == self.address and data[4:-1] == bytes.fromhex("19 00"):
            self.output.extend(make_frame(bytes((0x19, 0x00, self.response_id)), 0xE0, self.address))
        return len(data)

    def read(self, size):
        result = bytes(self.output[:size]); del self.output[:size]
        return result

    def close(self):
        pass


class ModelsTests(unittest.TestCase):
    def test_command_table_contains_only_read_commands(self):
        self.assertEqual(READ_COMMANDS, {"transceiver_id": b"\x19\x00",
                                         "frequency": b"\x03", "mode": b"\x04"})

    def test_expected_model_ids_are_unique(self):
        self.assertEqual(len(BY_ID), len(MODELS))
        self.assertEqual(model_for_id(0x94).name, "IC-7300")
        self.assertEqual(model_for_id(0xA4).name, "IC-705")
        self.assertEqual(model_for_id(0xB6).name, "IC-7300MK2")
        self.assertIsNone(model_for_id(0xF1))

    def test_bluetooth_only_on_explicitly_confirmed_profile(self):
        for profile in MODELS:
            validate_transport(profile, "USB")
            if profile.name == "IC-705":
                validate_transport(profile, "Bluetooth")
            else:
                with self.assertRaises(ValueError):
                    validate_transport(profile, "Bluetooth")
            with self.assertRaises(ValueError):
                validate_transport(profile, "Wi-Fi")

    def test_changed_civ_address_still_checks_model_identity(self):
        wire = CIVOddAddressWire()
        radio = IC7300(wire, timeout_s=0.02, radio_address=0x62)
        self.assertEqual(radio.read_transceiver_id(), 0xA4)
        self.assertEqual(wire.writes, [b"\xfe\xfe\x62\xe0\x19\x00\xfd"])
        self.assertEqual(parse_address_override("62h", BY_NAME["IC-705"]), 0x62)
        self.assertEqual(parse_address_override("", BY_NAME["IC-705"]), 0xA4)

    def test_bad_identity_response_fails_closed(self):
        wire = CIVOddAddressWire(response_id=0xA4)
        radio = IC7300(wire, timeout_s=0.02, radio_address=0x62)
        self.assertEqual(radio.read_transceiver_id(), 0xA4)
        with self.assertRaisesRegex(ValueError, "対応"):
            validate_transport(BY_NAME["IC-7300"], "Bluetooth")

    def test_reject_broadcast_or_delimiter_override(self):
        for addr in ("00", "E0", "FE", "FD", "nothex", "ABC"):
            with self.subTest(addr=addr), self.assertRaises(ValueError):
                parse_address_override(addr, BY_NAME["IC-705"])

    def test_settings_store_new_fields_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as base:
            store = DesktopStorage(Path(base))
            old = {"station_callsign":"JA1AAA", "contest_id":"ALL_JA",
                   "sent_nr":"11M", "band":"7", "civ_port":"COM3"}
            store.base_dir.mkdir(parents=True, exist_ok=True)
            store.settings_path.write_text(json.dumps(old), encoding="utf-8")
            legacy = store.load_settings()
            self.assertEqual((legacy.radio_model, legacy.civ_transport), ("IC-7300", "USB"))
            newer = replace(legacy, radio_model="IC-705", civ_transport="Bluetooth")
            self.assertEqual(store.load_settings(), legacy)
            store.save_settings(newer)
            self.assertEqual(store.load_settings(), newer)
            with self.assertRaises(LogValidationError):
                replace(legacy, civ_transport="Bluetooth").checked()

if __name__ == "__main__":
    unittest.main()
