"""Design-profile regression checks. No actual USB/CW transmit driver exists yet."""

import json
import unittest
from pathlib import Path


class RadioProfileDesignTests(unittest.TestCase):
    def test_ic7300_usb_profile_is_safe_and_hardware_free_by_default(self):
        profile_file = Path(__file__).resolve().parent.parent / "profiles" / "ic7300_usb_draft.json"
        profile = json.loads(profile_file.read_text(encoding="utf-8"))
        self.assertFalse(profile["verified_with_hardware"])
        self.assertEqual(profile["audio"]["source"], "usb_audio")
        self.assertEqual(profile["control"]["transport"], "usb_virtual_serial")
        self.assertEqual(profile["keying"]["preferred_backend"], "icom_civ_cw")
        self.assertEqual(
            profile["keying"]["fallback_backends"],
            ["usb_serial_dtr_rts", "external_usb_key"],
        )
        self.assertEqual(profile["keying"]["civ_command_hex"], "17")
        self.assertEqual(profile["keying"]["civ_max_message_characters"], 30)
        self.assertEqual(profile["keying"]["civ_abort_data_hex"], "FF")
        self.assertFalse(profile["keying"]["transmit_enabled"])
        self.assertIsNone(profile["control"]["com_port"])
        self.assertIsNone(profile["keying"]["usb_keying_line"])


if __name__ == "__main__":
    unittest.main()
