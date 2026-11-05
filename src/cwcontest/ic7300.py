"""IC-7300 (not MK2) CI-V control. No transmitting without explicit interlocks.

The command 0x17 sends CW text. A CI-V ACK only acknowledges command
handling; it is NOT evidence of completed RF CW transmission.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Protocol

RADIO_ADDRESS = 0x94
CONTROLLER_ADDRESS = 0xE0
CW_CHARACTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 /?.-,:'()=+\"@")
CW_MODES = {0x03: "CW", 0x07: "CW-R"}


class CIVError(RuntimeError):
    """Invalid frame, unsuccessful command, or failed safety check."""


@dataclass(frozen=True)
class Frame:
    destination: int
    source: int
    data: bytes


def make_frame(data: bytes, destination: int = RADIO_ADDRESS,
               source: int = CONTROLLER_ADDRESS) -> bytes:
    if not data or b"\xfd" in data or b"\xfe" in data:
        # binary CI-V commands sometimes use FE/FD in payload, but no
        # such payload is used by our restricted command subset.
        raise CIVError("empty data or CI-V delimiter in restricted payload")
    return bytes((0xFE, 0xFE, destination, source)) + data + b"\xfd"


class FrameParser:
    """Incremental parser. Ignores malformed preambles and incomplete frames."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        self.buffer.extend(data)
        result = []
        while True:
            start = self.buffer.find(b"\xfe\xfe")
            if start < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer.endswith(b"\xfe") else b""
                break
            if start:
                del self.buffer[:start]
            end = self.buffer.find(b"\xfd", 4)
            if end < 0:
                if len(self.buffer) > 512:
                    self.buffer.clear()
                break
            candidate = bytes(self.buffer[:end+1])
            del self.buffer[:end+1]
            if len(candidate) >= 6:
                result.append(Frame(candidate[2], candidate[3], candidate[4:-1]))
        return result


def make_cw_text_frame(text: str) -> bytes:
    message = text.upper()
    if not 1 <= len(message) <= 30:
        raise CIVError("IC-7300 CI-V CW message must be 1 to 30 characters; no auto-chunking")
    if any(c not in CW_CHARACTERS for c in message):
        raise CIVError("unsupported character in IC-7300 CW message")
    return make_frame(b"\x17" + message.encode("ascii"))


def make_cw_abort_frame() -> bytes:
    return make_frame(b"\x17\xff")


def decode_frequency_bcd(data: bytes) -> int:
    if len(data) != 5:
        raise CIVError("IC-7300 frequency reply must have 5 BCD bytes")
    digits = []
    for value in data:
        lo, hi = value & 15, value >> 4
        if lo > 9 or hi > 9:
            raise CIVError("invalid BCD frequency")
        digits.extend((str(lo), str(hi)))
    return int("".join(reversed(digits)))


class SerialLike(Protocol):
    def write(self, data: bytes) -> int: ...
    def read(self, size: int = 1) -> bytes: ...
    def close(self) -> None: ...


class IC7300:
    """Single-owner, fail-closed CI-V session.

    COM port opening deliberately holds DTR/RTS inactive. Radio configuration
    must also leave USB SEND and USB KEYING (CW) disabled for this backend.
    """

    def __init__(self, connection: SerialLike, timeout_s: float = 1.5):
        self.serial = connection
        self.timeout_s = timeout_s
        self.parser = FrameParser()

    @classmethod
    def open_port(cls, port: str, baud: int = 115200):
        try:
            import serial  # pyserial==3.5, optional until real hardware testing
        except ImportError as exc:
            raise CIVError("pyserial==3.5 is required: pip install '.[radio]'") from exc
        if not port:
            raise CIVError("explicit COM port is required")
        try:
            conn = serial.Serial(port=None, baudrate=baud, timeout=0.15,
                                 write_timeout=1.0, rtscts=False, dsrdtr=False)
            conn.dtr = False
            conn.rts = False
            conn.port = port
            conn.open()
        except Exception as exc:
            raise CIVError(f"cannot open port: {exc}") from exc
        return cls(conn)

    def close(self):
        self.serial.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _transaction(self, command: bytes, response_prefix: bytes) -> bytes:
        frame = make_frame(command)
        written = self.serial.write(frame)
        if written != len(frame):
            raise CIVError("partial CI-V write; do not retry automatically")
        stop_at = time.monotonic() + self.timeout_s
        while time.monotonic() < stop_at:
            for response in self.parser.feed(self.serial.read(128)):
                if response.source != RADIO_ADDRESS or response.destination != CONTROLLER_ADDRESS:
                    continue  # echo / broadcast / other equipment
                if response.data == b"\xfa":
                    raise CIVError("IC-7300 returned NG (FA)")
                if response.data.startswith(response_prefix):
                    return response.data[len(response_prefix):]
        raise CIVError("CI-V response timeout (no automatic retry)")

    def read_frequency_hz(self) -> int:
        return decode_frequency_bcd(self._transaction(b"\x03", b"\x03"))

    def read_mode(self) -> str:
        data = self._transaction(b"\x04", b"\x04")
        if not data:
            raise CIVError("empty mode response")
        return CW_MODES.get(data[0], f"OTHER:0x{data[0]:02X}")

    def read_break_in(self) -> int:
        data = self._transaction(b"\x16\x47", b"\x16\x47")
        if len(data) != 1 or data[0] not in (0, 1, 2):
            raise CIVError("invalid break-in state")
        return data[0]

    def read_tx_status(self) -> int:
        data = self._transaction(b"\x1c\x00", b"\x1c\x00")
        if len(data) != 1 or data[0] not in (0, 1):
            raise CIVError("invalid TX status")
        return data[0]

    def diagnostic(self) -> dict:
        return {"model_profile": "IC-7300", "frequency_hz": self.read_frequency_hz(),
                "mode": self.read_mode(), "break_in": self.read_break_in(),
                "tx_status": self.read_tx_status()}

    def transmit_once(self, text: str, *, user_armed: bool = False,
                      radio_menu_confirmed: bool = False) -> str:
        """One short manual message; never sends CQ repetitively or auto-QSOs."""
        command = make_cw_text_frame(text)  # validate before touching radio
        if not user_armed or not radio_menu_confirmed:
            raise CIVError("RF transmission disabled: arm AND radio menu confirmation required")
        # Check twice immediately before command for visible operator protection.
        if self.read_mode() != "CW":
            raise CIVError("radio mode must be CW")
        if self.read_break_in() == 0:
            raise CIVError("radio break-in is OFF")
        if self.read_tx_status() != 0:
            raise CIVError("transmitter already active; refusing to queue CW")
        # Firmware may return FB (ACK), but do not equate ACK with RF completion.
        self._transaction(command[4:-1], b"\xfb")
        return "CI-V command ACK (on-air CW completion unverified)"

    def abort(self):
        # This is allowed even when the transmit arm is disabled.
        self.serial.write(make_cw_abort_frame())
