"""Read-only CI-V monitor. Press the GUI '無線機確認' button to start.

The port is owned by one thread. Identification (19 00) is mandatory before
subscribing to frequency and mode, and a wrong model fails closed. Thread
never accesses Tk, never keys the transmitter, never uses Wi-Fi.
"""
from __future__ import annotations
from dataclasses import dataclass
from queue import Queue
from threading import Event, Thread

from .contest_radio import RadioState, classify_radio
from .ic7300 import IC7300, CIVError
from .icom_models import BY_NAME, RadioModel, parse_address_override, validate_transport


@dataclass(frozen=True)
class RadioUpdate:
    state: RadioState | None
    error: str = ""
    identified_model: str = ""
    detected_id: int | None = None


class RadioMonitor:
    def __init__(self, port: str, events: Queue[RadioUpdate], *,
                 model: str = "IC-7300", transport: str = "USB",
                 address_override: str = "", poll_seconds: float = 1.0):
        if not port:
            raise ValueError("COMポートを指定してください")
        if model not in BY_NAME:
            raise ValueError("未対応モデルは識別できません")
        self.profile: RadioModel = BY_NAME[model]
        validate_transport(self.profile, transport)
        self.address = parse_address_override(address_override, self.profile)
        self.transport = transport
        self.port = port
        self.events = events
        self.interval = max(0.5, poll_seconds)
        self.stop_event = Event()
        self.thread: Thread | None = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = Thread(target=self._worker, daemon=True, name="ICOM-CIV-READONLY")
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _worker(self):
        error = ""
        try:
            # The selected SPP virtual COM uses the same byte-oriented API
            # as USB; only the Windows COM port differs.
            with IC7300.open_port(self.port, radio_address=self.address) as rig:
                found = rig.read_transceiver_id()
                if found != self.profile.id_code:
                    raise CIVError(f"無線機ID不一致: 19 00→{found:02X}h、選択した"
                                   f"{self.profile.name}={self.profile.id_code:02X}h。"
                                   "誤接続防止のため停止します。")
                self.events.put(RadioUpdate(None, identified_model=self.profile.name,
                                            detected_id=found))
                while not self.stop_event.is_set():
                    frequency = rig.read_frequency_hz()
                    mode = rig.read_mode()
                    self.events.put(RadioUpdate(classify_radio(frequency, mode),
                                                identified_model=self.profile.name,
                                                detected_id=found))
                    if self.stop_event.wait(self.interval):
                        break
        except Exception as exc:
            error = f"CI-V停止: {exc}"
        finally:
            self.events.put(RadioUpdate(None, error or "切断"))
