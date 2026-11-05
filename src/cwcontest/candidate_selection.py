"""Receive-only worked-station eligibility; no transmit decision is produced."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contest_radio import RadioState
from .desktop_data import DesktopSettings, DesktopStorage
from .core import CALL_RE, JST


@dataclass(frozen=True)
class CandidateDecision:
    callsign: str
    eligible: bool
    reason: str


def evaluate_candidates(storage: DesktopStorage, settings: DesktopSettings,
                        radio: RadioState | None, callsigns: list[str],
                        *, now_jst: datetime | None = None) -> list[CandidateDecision]:
    """Reject uncertain calls and worked stations; require fresh caller-supplied radio state.

    This is a receive-only shortlist, not an authorization to transmit.
    The caller must invalidate `radio` immediately on any CI-V read error.
    """
    if radio is None:
        return [CandidateDecision(call, False, "CI-V未接続・取得失敗") for call in callsigns]
    if not radio.eligible_for(settings.contest_id):
        return [CandidateDecision(call, False, "CWモード/コンテスト周波数帯を要確認") for call in callsigns]
    if not settings.contest_window:
        return [CandidateDecision(call, False, "コンテスト期間未設定") for call in callsigns]
    start, end = settings.contest_window
    now = now_jst or datetime.now(JST)
    if not start <= now < end:
        return [CandidateDecision(call, False, "コンテスト開催期間外") for call in callsigns]
    result = []
    for raw in callsigns:
        call = raw.strip().upper()
        if not CALL_RE.fullmatch(call):
            result.append(CandidateDecision(raw, False, "コールサイン不完全"))
        elif call == settings.station_callsign:
            result.append(CandidateDecision(call, False, "自局") )
        elif storage.already_worked(settings, call, radio.band):
            result.append(CandidateDecision(call, False, "このバンドで交信済み"))
        else:
            result.append(CandidateDecision(call, True, "未交信候補"))
    return result
