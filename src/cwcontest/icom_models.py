"""Read-only model capability and CI-V command table.

Source: manufacturer product pages and model CI-V supplementary/reference guides.
IDs are *factory defaults*, not guaranteed to match a user-configured CI-V address.
Device identification is obtained with CI-V 19 00, never from the USB name alone.
"""
from __future__ import annotations
from dataclasses import dataclass

# Restricted commands supported for identification/monitoring. Do not add
# write-capable commands here without a separate safety review.
READ_COMMANDS: dict[str, bytes] = {
    "transceiver_id": bytes.fromhex("19 00"),
    "frequency": bytes.fromhex("03"),
    "mode": bytes.fromhex("04"),
}

@dataclass(frozen=True)
class RadioModel:
    name: str
    id_code: int
    usb_civ: bool
    bluetooth_spp_civ: bool
    usb_audio: bool
    cw_message_17: bool | None  # None: no individually verified command yet
    official_source: str
    notes: str = ""


# IC-7850 and IC-7851 share the factory ID and cannot be disambiguated by 19 00.
# Some historical equipment also uses changeable CI-V addresses. Report such
# ambiguity; do not guess individual variants, firmware, or RF output power.
MODELS: tuple[RadioModel, ...] = (
    RadioModel("IC-7300", 0x94, True, False, True, True, "https://www.icom.co.jp/lineup/products/IC-7300/"),
    RadioModel("IC-705", 0xA4, True, True, True, True, "https://www.icom.co.jp/lineup/products/IC-705/", "BT SPP is CI-V only. BT receive audio on Windows unverified."),
    RadioModel("IC-7300MK2", 0xB6, True, False, True, True, "https://www.icom.co.jp/lineup/products/IC-7300MK2/"),
    RadioModel("IC-7610", 0x98, True, False, True, True, "https://www.icom.co.jp/lineup/products/IC-7610/"),
    RadioModel("IC-9700", 0xA2, True, False, True, True, "https://www.icom.co.jp/lineup/products/IC-9700/"),
    RadioModel("IC-7760", 0xB2, True, False, True, True, "https://www.icom.co.jp/lineup/products/IC-7760/"),
    RadioModel("IC-905", 0xAC, True, False, True, True, "https://www.icom.co.jp/lineup/products/IC-905/"),
    RadioModel("IC-7100", 0x88, True, False, True, None, "https://www.icom.co.jp/lineup/products/IC-7100/", "17h needs separate model/firmware confirmation"),
    RadioModel("IC-9100", 0x7C, True, False, True, None, "https://www.icom.co.jp/lineup/products/IC-9100/", "17h needs separate model/firmware confirmation"),
    RadioModel("IC-7600", 0x7A, True, False, True, True, "https://www.icom.co.jp/lineup/products/IC-7600/", "17h depends on firmware; check radio firmware"),
    RadioModel("IC-7410", 0x80, True, False, True, True, "https://www.icom.co.jp/lineup/products/IC-7410/"),
    RadioModel("IC-7200", 0x76, True, False, True, None, "https://www.icom.co.jp/lineup/products/IC-7200/", "17h not verified; receive-only until checked"),
    RadioModel("IC-7850/IC-7851", 0x8E, True, False, True, None, "https://www.icom.co.jp/lineup/products/IC-7851/", "CI-V ID cannot distinguish 7850 and 7851"),
)
BY_NAME = {m.name: m for m in MODELS}
BY_ID = {m.id_code: m for m in MODELS}


def model_for_id(value: int) -> RadioModel | None:
    return BY_ID.get(value)


def validate_transport(model: RadioModel, transport: str) -> None:
    if transport == "USB" and model.usb_civ:
        return
    if transport == "Bluetooth" and model.bluetooth_spp_civ:
        return
    raise ValueError(f"{model.name} は{transport} CI-V接続の対応を確認できません。")


def parse_address_override(value: str, model: RadioModel) -> int:
    """Optional two-digit hex address for rigs with changed CI-V address.

    The returned number is a destination address, NOT the ID to compare
    against the data returned from CI-V 19 00.
    """
    if not value.strip():
        return model.id_code
    data = value.strip().upper().removeprefix("0X").removesuffix("H")
    if len(data) != 2 or any(c not in "0123456789ABCDEF" for c in data):
        raise ValueError("CI-Vアドレスは16進数2桁で指定してください（例：94）。")
    result = int(data, 16)
    if result in (0x00, 0xE0, 0xFE, 0xFD):
        raise ValueError("予約/ブロードキャスト/区切りコードは指定できません。")
    return result
