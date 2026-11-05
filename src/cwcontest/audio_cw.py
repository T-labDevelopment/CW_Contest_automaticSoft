"""Experimental single-tone CW audio detector for offline PCM WAV files.

Not a pile-up decoder. No direct transmit decisions should depend on it.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
import sys
import wave

MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F",
    "--.": "G", "....": "H", "..": "I", ".---": "J", "-.-": "K", ".-..": "L",
    "--": "M", "-.": "N", "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R",
    "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
    "-.--": "Y", "--..": "Z", "-----": "0", ".----": "1", "..---": "2",
    "...--": "3", "....-": "4", ".....": "5", "-....": "6", "--...": "7",
    "---..": "8", "----.": "9", "-..-.": "/", "..--..": "?", "-...-": "=",
    ".-.-.-": ".", "--..--": ",", "-....-": "-",
}


@dataclass(frozen=True)
class DecodeResult:
    text: str
    estimated_wpm: float | None
    note: str = "experimental single-tone decoder; operator confirmation required"


def tone_amplitudes(samples: list[float], sample_rate: int, tone_hz: int,
                    window_ms: int = 10) -> list[float]:
    """Goertzel narrowband envelope, non-overlapping windows."""
    if sample_rate < 4000 or not 100 <= tone_hz < sample_rate / 2:
        raise ValueError("invalid CW tone or audio sample rate")
    n = max(8, round(sample_rate * window_ms / 1000))
    omega = 2.0 * math.pi * tone_hz / sample_rate
    coeff = 2.0 * math.cos(omega)
    result = []
    for i in range(0, len(samples) - n + 1, n):
        a = b = 0.0
        for sample in samples[i:i+n]:
            c = sample + coeff * a - b
            b, a = a, c
        real = a - b * math.cos(omega)
        imag = b * math.sin(omega)
        result.append(2.0 * math.hypot(real, imag) / n)
    return result


def _runs(flags: list[bool]) -> list[tuple[bool, int]]:
    if not flags:
        return []
    out = []
    current, count = flags[0], 0
    for flag in flags:
        if flag != current:
            out.append((current, count))
            current, count = flag, 0
        count += 1
    out.append((current, count))
    return out


def decode_envelope(envelope: list[float], window_ms: int = 10) -> DecodeResult:
    if not envelope:
        return DecodeResult("", None)
    peak = max(envelope)
    if peak < 0.012:
        return DecodeResult("", None)
    threshold = max(0.012, peak * 0.27)
    flags = [a >= threshold for a in envelope]
    # Reject 10 ms spikes/gaps before timing estimation.
    for _ in range(2):
        runs = _runs(flags)
        start = 0
        for on, length in runs:
            if length <= 1 and start > 0 and start + length < len(flags):
                flags[start:start+length] = [flags[start-1]] * length
            start += length
    runs = _runs(flags)
    on_lengths = sorted(length for on, length in runs if on and length >= 2)
    if not on_lengths:
        return DecodeResult("", None)
    # The shortest on-pulse may be dot or dash, and is uncertain for dot-free text.
    shortest = on_lengths[max(0, (len(on_lengths) - 1) // 5)]
    off_lengths = sorted(length for on, length in runs if not on and length >= 2)
    potential_dots = [x for x in on_lengths if x <= shortest * 1.7]
    dot_windows = float(sorted(potential_dots)[len(potential_dots)//2])
    if off_lengths:
        short_gap = off_lengths[0]
        if dot_windows > 2.1 * short_gap:
            dot_windows /= 3.0  # dot-free (dash-only) messages
    dot_windows = max(1.0, dot_windows)
    symbols = []
    letters = []
    for on, length in runs:
        if on:
            symbols.append("-" if length >= dot_windows * 2.0 else ".")
        elif symbols:
            if length >= dot_windows * 6:
                letters.append(MORSE.get("".join(symbols), "?"))
                letters.append(" ")
                symbols = []
            elif length >= dot_windows * 2.3:
                letters.append(MORSE.get("".join(symbols), "?"))
                symbols = []
    if symbols:
        letters.append(MORSE.get("".join(symbols), "?"))
    estimated_wpm = 1200.0 / (dot_windows * window_ms)
    return DecodeResult("".join(letters).strip(), round(estimated_wpm, 1))


def decode_samples(samples: list[float], sample_rate: int, tone_hz: int = 700) -> DecodeResult:
    return decode_envelope(tone_amplitudes(samples, sample_rate, tone_hz))


def read_wav_mono(path: str) -> tuple[list[float], int]:
    with wave.open(path, "rb") as audio:
        if audio.getcomptype() != "NONE" or audio.getsampwidth() != 2:
            raise ValueError("only uncompressed 16-bit PCM WAV is supported")
        count = audio.getnframes()
        ch = audio.getnchannels()
        rate = audio.getframerate()
        if ch not in (1, 2):
            raise ValueError("only mono/stereo WAV is supported")
        values = array('h')
        values.frombytes(audio.readframes(count))
        if sys.byteorder != 'little':
            values.byteswap()
        if ch == 1:
            return [v / 32768 for v in values], rate
        return [(values[i] + values[i+1]) / 65536 for i in range(0, len(values), 2)], rate


def decode_wav(path: str, tone_hz: int = 700) -> DecodeResult:
    samples, sample_rate = read_wav_mono(path)
    return decode_samples(samples, sample_rate, tone_hz)
