import unittest
from cwcontest.ic7300 import (
    IC7300, CIVError, FrameParser, decode_frequency_bcd, make_frame,
    make_cw_text_frame, make_cw_abort_frame,
)


class FakeSerial:
    """Mock CI-V radio, no physical RF equipment."""
    def __init__(self, mode=3, break_in=1, tx=0, fail=False):
        self.writes = []
        self.replies = bytearray()
        self.mode, self.break_in, self.tx, self.fail = mode, break_in, tx, fail

    def write(self, data):
        self.writes.append(data)
        payload = data[4:-1]
        if payload == b'\x19\x00':
            response = b'\x19\x00\x94'
        elif payload == b'\x03':
            response = b'\x03\x00\x00\x10\x07\x00'  # 7,100,000 Hz
        elif payload == b'\x04':
            response = bytes((4, self.mode, 1))
        elif payload == b'\x16\x47':
            response = bytes((0x16, 0x47, self.break_in))
        elif payload == b'\x1c\x00':
            response = bytes((0x1c, 0, self.tx))
        elif payload.startswith(b'\x17'):
            response = b'\xfa' if self.fail else b'\xfb'
        else:
            response = b'\xfa'
        # A CI-V echo is not the reply from the radio.
        self.replies.extend(data + make_frame(response, destination=0xE0, source=0x94))
        return len(data)

    def read(self, size=1):
        b = bytes(self.replies[:size]); del self.replies[:size]; return b

    def close(self):
        return None


class TestProtocol(unittest.TestCase):
    def test_text_frame(self):
        self.assertEqual(make_cw_text_frame('CQ JA1AAA'), b'\xfe\xfe\x94\xe0\x17CQ JA1AAA\xfd')
        self.assertEqual(make_cw_abort_frame(), b'\xfe\xfe\x94\xe0\x17\xff\xfd')

    def test_reject_oversize_and_unsafe_characters(self):
        for text in ('', 'X'*31, 'JA1AAA\n', 'JA1AAA^'):
            with self.assertRaises(CIVError):
                make_cw_text_frame(text)

    def test_frame_incremental(self):
        p = FrameParser()
        f = make_frame(b'\x03', 0xe0, 0x94)
        self.assertEqual(p.feed(b'\x00' + f[:3]), [])
        self.assertEqual(len(p.feed(f[3:])), 1)

    def test_frequency_bcd(self):
        self.assertEqual(decode_frequency_bcd(b'\x00\x00\x10\x07\x00'), 7_100_000)
        with self.assertRaises(CIVError):
            decode_frequency_bcd(b'\x00\xfa\x10\x07\x00')

    def test_read_only_diagnostic(self):
        wire = FakeSerial()
        r = IC7300(wire, timeout_s=.02)
        d = r.diagnostic()
        self.assertEqual(d['frequency_hz'], 7_100_000)
        self.assertEqual(d['mode'], 'CW')
        self.assertEqual(d['break_in'], 1)
        self.assertEqual(d['tx_status'], 0)
        self.assertFalse(any(b'\x17' in frame[4:-1] for frame in wire.writes))

    def test_transmission_requires_arms(self):
        wire = FakeSerial()
        r = IC7300(wire, timeout_s=.02)
        with self.assertRaises(CIVError):
            r.transmit_once('TEST')
        self.assertFalse(wire.writes)

    def test_cw_mode_check(self):
        wire = FakeSerial(mode=1)
        r = IC7300(wire, timeout_s=.02)
        with self.assertRaisesRegex(CIVError, 'CW'):
            r.transmit_once('TEST', user_armed=True, radio_menu_confirmed=True)
        self.assertFalse(any(frame[4:-1].startswith(b'\x17') for frame in wire.writes))

    def test_no_break_in(self):
        wire = FakeSerial(break_in=0)
        r = IC7300(wire, timeout_s=.02)
        with self.assertRaisesRegex(CIVError, 'break-in'):
            r.transmit_once('TEST', user_armed=True, radio_menu_confirmed=True)

    def test_prevent_tx_when_radio_transmitting(self):
        wire = FakeSerial(tx=1)
        r = IC7300(wire, timeout_s=.02)
        with self.assertRaisesRegex(CIVError, 'already active'):
            r.transmit_once('TEST', user_armed=True, radio_menu_confirmed=True)

    def test_single_rf_message_fake_ack(self):
        wire = FakeSerial()
        r = IC7300(wire, timeout_s=.02)
        self.assertIn('completion unverified', r.transmit_once('TEST', user_armed=True, radio_menu_confirmed=True))
        self.assertEqual(wire.writes[-1], make_cw_text_frame('TEST'))

    def test_ng_no_retry(self):
        wire = FakeSerial(fail=True)
        r = IC7300(wire, timeout_s=.02)
        with self.assertRaises(CIVError):
            r.transmit_once('TEST', user_armed=True, radio_menu_confirmed=True)
        self.assertEqual(sum(x.startswith(b'\xfe\xfe\x94\xe0\x17') for x in wire.writes), 1)

    def test_abort_unarmed(self):
        wire = FakeSerial()
        IC7300(wire).abort()
        self.assertEqual(wire.writes, [make_cw_abort_frame()])


if __name__ == '__main__':
    unittest.main()
