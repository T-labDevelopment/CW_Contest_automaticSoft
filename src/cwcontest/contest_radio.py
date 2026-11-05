"""Read-only IC-7300 state classification for JARL CW contest operation.

The dial frequency is a clue, not proof of the occupied RF spectrum.
No decision from this module authorizes RF transmission.
"""
from __future__ import annotations

from dataclasses import dataclass

# JARL 2026 contest CW frequency allocations in Hz (ALL JA / ACAG),
# https://www.jarl.org/Japanese/1_Tanoshimo/1-1_Contest/frequency.html
CONTEST_CW_RANGES: dict[str, tuple[int, int]] = {
    "1.9": (1_801_000, 1_820_000),
    "3.5": (3_510_000, 3_530_000),
    "7": (7_010_000, 7_040_000),
    "14": (14_050_000, 14_080_000),
    "21": (21_050_000, 21_080_000),
    "28": (28_050_000, 28_080_000),
    "50": (50_050_000, 50_090_000),
    "144": (144_050_000, 144_090_000),
    "430": (430_050_000, 430_090_000),
}

# Band identification is intentionally broader than the contest CW allocations.
# IC-7300 only covers up to 50 MHz; 144/430 entries support data rules, not this rig.
AMATEUR_BANDS: dict[str, tuple[int, int]] = {
    "1.9": (1_800_000, 2_000_000),
    "3.5": (3_500_000, 4_000_000),
    "7": (7_000_000, 7_300_000),
    "14": (14_000_000, 14_500_000),
    "21": (21_000_000, 21_500_000),
    "28": (28_000_000, 30_000_000),
    "50": (50_000_000, 54_000_000),
    "144": (144_000_000, 146_000_000),
    "430": (430_000_000, 440_000_000),
}

CW_MODES = {"CW", "CW-R"}
# Purely a conservative UI warning margin; not a legal bandwidth calculation.
EDGE_MARGIN_HZ = 500


def infer_band(frequency_hz: int) -> str | None:
    if isinstance(frequency_hz, bool) or not isinstance(frequency_hz, int) or frequency_hz <= 0:
        return None
    for band, (low, high) in AMATEUR_BANDS.items():
        if low <= frequency_hz < high:
            return band
    return None


@dataclass(frozen=True)
class RadioState:
    frequency_hz: int
    mode: str
    band: str | None
    in_cw_contest_segment: bool
    edge_warning: bool

    @property
    def cw_mode(self) -> bool:
        return self.mode in CW_MODES

    @property
    def frequency_label(self) -> str:
        return f"{self.frequency_hz / 1_000_000:.6f} MHz"

    def eligible_for(self, contest_id: str) -> bool:
        from .core import ALLOWED_BANDS
        # IC-7300 has no 144/430 MHz transmitter; never mark those bands eligible.
        return bool(self.cw_mode and self.band in {"1.9", "3.5", "7", "14", "21", "28", "50"}
                    and self.band in ALLOWED_BANDS.get(contest_id, ())
                    and self.in_cw_contest_segment and not self.edge_warning)


def classify_radio(frequency_hz: int, mode: str) -> RadioState:
    band = infer_band(frequency_hz)
    limits = CONTEST_CW_RANGES.get(band or "")
    in_segment = bool(limits and limits[0] <= frequency_hz <= limits[1])
    near_edge = bool(in_segment and limits and
                     not (limits[0] + EDGE_MARGIN_HZ <= frequency_hz <= limits[1] - EDGE_MARGIN_HZ))
    return RadioState(frequency_hz, mode, band, in_segment, near_edge)
