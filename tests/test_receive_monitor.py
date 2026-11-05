"""USB receiver is tested without touching any radio/audio hardware."""
from dataclasses import replace
from pathlib import Path
from queue import Queue
import math
import tempfile
import unittest
import wave

from cwcontest.audio_cw import MORSE
from cwcontest.desktop_data import DesktopSettings, DesktopStorage
from cwcontest.receive_monitor import (AudioDecodeMonitor, CandidateTracker,
                                       ReceiveUpdate, decode_file, extract_callsigns)


def synthesize(text: str, rate: int = 8000, tone: int = 700, wpm: int = 20) -> list[float]:
    inv = {letter: pattern for pattern, letter in MORSE.items()}
    dot = 1.2 / wpm
    samples = []
    def pulse(on: bool, seconds: float):
        start = len(samples)
        samples.extend((.7 * math.sin(2*math.pi*tone*(start+i)/rate) if on else 0)
                       for i in range(round(seconds*rate)))
    pulse(False, .25)
    for wi, word in enumerate(text.split()):
        if wi: pulse(False, 7 * dot)
        for ci, char in enumerate(word):
            if ci: pulse(False, 3 * dot)
            for si, mark in enumerate(inv[char]):
                if si: pulse(False, dot)
                pulse(True, dot if mark == '.' else 3 * dot)
    pulse(False, .3)
    return samples


class ReceiveMonitorTests(unittest.TestCase):
    def test_candidates_are_hints_and_not_numeric_rst(self):
        self.assertEqual(extract_callsigns('CQ TEST JA1AAA 599 11M JA2BBB JA1?'),
                         ['JA1AAA', 'JA2BBB'])
        self.assertEqual(extract_callsigns('ja2bbb ja2bbb'), ['JA2BBB'])

    def test_candidate_tracking_and_reset(self):
        tracker = CandidateTracker(limit=2)
        tracker.observe('JA1AAA JA2BBB')
        tracker.observe('JA1AAA JA3CCC')
        self.assertEqual(tracker.candidates(), [('JA1AAA', 2), ('JA3CCC', 1)])
        tracker.clear()
        self.assertEqual(tracker.candidates(), [])

    def test_wav_decoder_end_to_end_without_radio(self):
        samples = synthesize('JA1AAA')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sample.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
                wav.writeframes(b''.join(round(max(-1, min(1, s)) * 32767).to_bytes(
                    2, 'little', signed=True) for s in samples))
            result = decode_file(path, 700)
            self.assertEqual(result.origin, 'WAV')
            self.assertIn('JA1AAA', result.text)
            self.assertIn('JA1AAA', extract_callsigns(result.text))

    def test_invalid_audio_monitor_config_rejected(self):
        for dev,tone in [(-1,700),(0,399),(0,1101)]:
            with self.assertRaises(ValueError):
                AudioDecodeMonitor(dev,tone,Queue())
        monitor = AudioDecodeMonitor(0,700,Queue())
        monitor.invalidate()
        self.assertTrue(monitor.invalidate_event.is_set())
        monitor.stop()
        self.assertTrue(monitor.stop_event.is_set())

    def test_settings_new_fields_round_trip_and_back_compat(self):
        with tempfile.TemporaryDirectory() as folder:
            store = DesktopStorage(Path(folder))
            settings = DesktopSettings('JA1AAA','ALL_JA','11M','7',
                                       audio_device=2,cw_tone_hz=750)
            self.assertEqual(store.save_settings(settings),store.load_settings())
            legacy = {'station_callsign':'JA1AAA','contest_id':'ALL_JA',
                      'sent_nr':'11M','band':'7'}
            import json
            store.settings_path.write_text(json.dumps(legacy), encoding='utf-8')
            self.assertEqual(store.load_settings().audio_device, -1)
            self.assertEqual(store.load_settings().cw_tone_hz, 700)
            for kwargs in [dict(audio_device=-2),dict(cw_tone_hz=1110)]:
                with self.assertRaises(ValueError):
                    replace(settings, **kwargs).checked()

if __name__ == '__main__':
    unittest.main()
