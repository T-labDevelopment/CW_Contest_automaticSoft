"""Manual-approval CW QSO state machine; independent from actual RF and DSP.

It generates text for the operator to review. Never directly drives a transmitter.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum, auto
import re

from .core import CALL_RE, JST, QSO
from .ic7300 import CIVError, make_cw_text_frame


class State(Enum):
    IDLE = auto()
    WAIT_CALL = auto()
    APPROVE_CALL = auto()
    WAIT_EXCHANGE = auto()
    APPROVE_EXCHANGE = auto()
    WAIT_ACK_CONFIRM = auto()
    READY_TO_LOG = auto()
    COMPLETE = auto()
    ABORTED = auto()


class QSOStateError(ValueError):
    pass


class Session:
    def __init__(self, my_call: str, my_exchange: str, band: str):
        self.my_call = my_call.upper()
        self.my_exchange = my_exchange.upper()
        self.band = band
        if not CALL_RE.fullmatch(self.my_call) or not re.fullmatch(r'[0-9]{2,6}[HMLP]', self.my_exchange):
            raise QSOStateError('invalid local call or contest exchange')
        self.state = State.IDLE
        self.their_call = None
        self.their_exchange = None
        self.raw_call_copy = ''
        self.raw_exchange_copy = ''
        self.confidence = 0.0

    def _expected(self, state: State):
        if self.state != state:
            raise QSOStateError(f'expected {state.name}, got {self.state.name}')

    @staticmethod
    def _message(value: str) -> str:
        # Single message: forbid implicit chaining beyond 30 character CI-V limit.
        try:
            make_cw_text_frame(value)
        except CIVError as exc:
            raise QSOStateError(str(exc)) from exc
        return value

    def begin_cq(self) -> str:
        self._expected(State.IDLE)
        message = self._message(f'CQ TEST {self.my_call} {self.my_call}')
        self.state = State.WAIT_CALL
        return message

    def receive_call(self, call: str, *, raw: str, confidence: float):
        self._expected(State.WAIT_CALL)
        call = call.upper().strip()
        if not CALL_RE.fullmatch(call) or not any(c.isalpha() for c in call):
            raise QSOStateError('call sign cannot be unambiguously parsed')
        if not 0 <= confidence <= 1:
            raise QSOStateError('invalid decoder confidence')
        self.their_call = call
        self.raw_call_copy = raw
        self.confidence = confidence
        self.state = State.APPROVE_CALL

    def approve_call(self) -> str:
        self._expected(State.APPROVE_CALL)
        message = self._message(f'{self.their_call} 5NN {self.my_exchange}')
        self.state = State.WAIT_EXCHANGE
        return message

    def receive_exchange(self, copied: str, *, confidence: float):
        self._expected(State.WAIT_EXCHANGE)
        if not 0 <= confidence <= 1:
            raise QSOStateError('invalid decoder confidence')
        normalized = copied.upper().replace(' ', '')
        match = re.fullmatch(r'(?:599|5NN)([0-9]{2,6}[HMLP])', normalized)
        if not match:
            raise QSOStateError('received RST and exchange are incomplete/uncertain')
        self.their_exchange = match.group(1)
        self.raw_exchange_copy = copied
        self.confidence = min(self.confidence, confidence)
        self.state = State.APPROVE_EXCHANGE

    def approve_exchange(self) -> str:
        self._expected(State.APPROVE_EXCHANGE)
        self.state = State.WAIT_ACK_CONFIRM
        return self._message('TU')

    def confirm_ack_finished(self):
        """Call only after the operator has observed the final CW actually sent."""
        self._expected(State.WAIT_ACK_CONFIRM)
        self.state = State.READY_TO_LOG

    def commit(self, *, when_jst: datetime, operator_confirmed: bool) -> QSO:
        self._expected(State.READY_TO_LOG)
        if not operator_confirmed or when_jst.tzinfo is None or when_jst.utcoffset() != JST.utcoffset(None):
            raise QSOStateError('operator confirmation and JST timestamp are required')
        qso = QSO(time_jst=when_jst, band=self.band, mode='CW',
                  callsign=self.their_call, sent_rst='599', sent_nr=self.my_exchange,
                  rcvd_rst='599', rcvd_nr=self.their_exchange, completed=True)
        self.state = State.COMPLETE
        return qso

    def abort(self):
        self.state = State.ABORTED
