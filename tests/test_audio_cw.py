import math
from pathlib import Path
import tempfile
import unittest
import wave

from cwcontest.audio_cw import decode_samples, decode_wav, tone_amplitudes

CODE = {"C": "-.-.", "Q": "--.-", "T": "-", "E": ".", "S": "...", "J": ".---", "A": ".-", "1": ".----", "2": "..---", "3": "...--"}


def synthetic_cw(text, fs=8000, tone=700, wpm=20):
    dot = 1.2 / wpm
    samples = []
    def run(is_on, sec):
        n = round(fs * sec)
        start = len(samples)
        samples.extend([.65 * math.sin(2 * math.pi * tone * (start + k)/fs) if is_on else 0.0 for k in range(n)])
    run(False, 0.3)
    for w, word in enumerate(text.split()):
        if w: run(False, 7*dot)
        for index, char in enumerate(word):
            if index: run(False, 3*dot)
            for i, symbol in enumerate(CODE[char]):
                if i: run(False, dot)
                run(True, dot if symbol == '.' else dot*3)
    run(False, 0.3)
    return samples


class TestAudioCW(unittest.TestCase):
    def test_goertzel_detects_tone(self):
        s = synthetic_cw('E')
        env = tone_amplitudes(s, 8000, 700)
        self.assertGreater(max(env), .3)

    def test_decode_single_signal(self):
        result = decode_samples(synthetic_cw('CQ TEST'), 8000, 700)
        self.assertEqual(result.text, 'CQ TEST')
        self.assertAlmostEqual(result.estimated_wpm, 20.0, delta=3.0)

    def test_decode_wav(self):
        samples = synthetic_cw('JA1', wpm=15)
        with tempfile.TemporaryDirectory() as folder:
            name = str(Path(folder) / 'rx.wav')
            with wave.open(name, 'wb') as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(8000)
                out.writeframes(b''.join(round(s * 32767).to_bytes(2, 'little', signed=True) for s in samples))
            self.assertEqual(decode_wav(name).text, 'JA1')

    def test_silence(self):
        self.assertEqual(decode_samples([0.0]*8000, 8000).text, '')


if __name__ == '__main__':
    unittest.main()
