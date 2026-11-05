"""Background read-only CI-V poller; returns immutable events to Tk main thread.

Thread never touches Tk. Serial port is owned only by this monitor while connected.
This module sends only CI-V read commands 03/04; no keying or PTT control.
"""
from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from threading import Event, Thread

from .contest_radio import RadioState, classify_radio
from .ic7300 import IC7300


@dataclass(frozen=True)
class RadioUpdate:
    state: RadioState | None
    error: str = ""


class RadioMonitor:
    def __init__(self, port: str, events: Queue[RadioUpdate],
                 *, poll_seconds: float = 1.0):
        if not port:
            raise ValueError("COMポートを指定してください")
        self.port = port
        self.events = events
        self.interval = max(0.5, poll_seconds)
        self.stop_event = Event()
        self.thread: Thread | None = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = Thread(target=self._worker, daemon=True, name="IC7300-CIV-READONLY")
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _worker(self):
        error = ""
        try:
            with IC7300.open_port(self.port) as rig:
                while not self.stop_event.is_set():
                    frequency = rig.read_frequency_hz()
                    mode = rig.read_mode()
                    self.events.put(RadioUpdate(classify_radio(frequency, mode)))
                    if self.stop_event.wait(self.interval):
                        break
        except Exception as exc:
            error = f"CI-V停止: {exc}"
        finally:
            self.events.put(RadioUpdate(None, error or "切断"))
