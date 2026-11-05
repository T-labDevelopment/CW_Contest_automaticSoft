"""Receive-only IC-7300 USB Audio CW monitor and conservative caller hints.

This decoder is a *single-tone experiment*. Never treat its output or candidate
ranking as a verified on-air exchange or permission to transmit.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from queue import Queue
from threading import Event, Thread

from .audio_cw import decode_samples, decode_wav
from .core import CALL_RE


@dataclass(frozen=True)
class ReceiveUpdate:
    text: str = ""
    wpm: float | None = None
    error: str = ""
    origin: str = "USB"


# These are hints, not certainty estimates. Avoid numbers-only, CQ and TEST.
_WORDS = re.compile(r"[A-Z0-9/]+")


def extract_callsigns(text: str) -> list[str]:
    """Return distinctive, syntactically plausible callsign *candidates* only."""
    result: list[str] = []
    for word in _WORDS.findall(text.upper()):
        if (CALL_RE.fullmatch(word)
                and sum(c.isalpha() for c in word) >= 2
                and any(c.isdigit() for c in word)
                and word not in result):
            result.append(word)
    return result


class CandidateTracker:
    """Keep observed call candidates for the current frequency+mode context."""
    def __init__(self, limit: int = 25):
        self.limit = limit
        self.counts: dict[str, int] = {}

    def clear(self):
        self.counts.clear()

    def observe(self, decoded_text: str):
        for call in extract_callsigns(decoded_text):
            self.counts[call] = min(self.counts.get(call, 0) + 1, 999)
        while len(self.counts) > self.limit:
            # Discard the oldest of the least-observed calls, not the best one.
            victim = min(self.counts, key=lambda call: self.counts[call])
            del self.counts[victim]

    def candidates(self) -> list[tuple[str, int]]:
        return sorted(self.counts.items(), key=lambda kv: (-kv[1], kv[0]))


def decode_file(path: str | Path, tone_hz: int) -> ReceiveUpdate:
    result = decode_wav(str(path), tone_hz)
    return ReceiveUpdate(result.text, result.estimated_wpm, origin="WAV")


class AudioDecodeMonitor:
    """A background 8 s sliding audio window; 4 s hop, receive-only."""
    SAMPLE_RATE = 16000
    WINDOW_SECONDS = 8
    HOP_SECONDS = 4

    def __init__(self, device: int, tone_hz: int, events: Queue[ReceiveUpdate]):
        if device < 0:
            raise ValueError("USB音声入力デバイスを選択してください")
        if not 400 <= tone_hz <= 1100:
            raise ValueError("CWトーン周波数は400～1100Hzで指定してください")
        self.device = device
        self.tone_hz = tone_hz
        self.events = events
        self.stop_event = Event()
        self.invalidate_event = Event()
        self.thread: Thread | None = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = Thread(target=self._worker, daemon=True, name="CW-USB-RX")
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def invalidate(self):
        """Discard the previous receive window after CAT frequency/mode changes."""
        self.invalidate_event.set()

    def _worker(self):
        try:
            import sounddevice as sd  # optional; PyInstaller bundles at build time
            window = self.SAMPLE_RATE * self.WINDOW_SECONDS
            hop = self.SAMPLE_RATE * self.HOP_SECONDS
            buf = array("h")
            # Use raw stream to avoid mandatory NumPy. This is never an output stream.
            with sd.RawInputStream(samplerate=self.SAMPLE_RATE, device=self.device,
                                   channels=1, dtype="int16", blocksize=2048) as stream:
                while not self.stop_event.is_set():
                    data, overflow = stream.read(2048)
                    if overflow:
                        self.events.put(ReceiveUpdate(error="USB音声入力オーバーフロー：候補を破棄"))
                        buf = array("h")
                        continue
                    if self.invalidate_event.is_set():
                        buf = array("h")
                        self.invalidate_event.clear()
                    chunk = array("h")
                    chunk.frombytes(data)
                    if sys.byteorder != "little":
                        chunk.byteswap()
                    buf.extend(chunk)
                    if len(buf) < window:
                        continue
                    samples = [v / 32768.0 for v in buf[:window]]
                    del buf[:hop]
                    decoded = decode_samples(samples, self.SAMPLE_RATE, self.tone_hz)
                    self.events.put(ReceiveUpdate(decoded.text, decoded.estimated_wpm))
        except Exception as exc:
            self.events.put(ReceiveUpdate(error=f"USB音声受信停止: {exc}"))
        finally:
            self.events.put(ReceiveUpdate(error="USB音声監視を終了しました"))
