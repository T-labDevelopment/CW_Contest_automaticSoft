"""Explicit, non-autonomous IC-7300 diagnostics and CW audio capture CLI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .ic7300 import CIVError, IC7300, make_cw_text_frame


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m cwcontest", description="IC-7300 PC-only test interface")
    subs = parser.add_subparsers(dest="command", required=True)
    check = subs.add_parser("radio-check", help="Read-only CI-V diagnosis: frequency, mode, BK-IN, TX")
    check.add_argument("--port", required=True, help="COM port on Windows, e.g. COM4")
    check.add_argument("--baud", type=int, default=115200)
    send = subs.add_parser("cw-send", help="One explicitly approved short CW message on RF")
    send.add_argument("--port", required=True)
    send.add_argument("--baud", type=int, default=115200)
    send.add_argument("--text", required=True)
    send.add_argument("--profile", default="profiles/ic7300_usb.json")
    send.add_argument("--arm-rf", action="store_true", help="Explicitly allow this one live RF transmission")
    send.add_argument("--menu-checked", action="store_true", help="Confirm IC-7300 BK-IN/USB menu and RF safety")
    stop = subs.add_parser("cw-abort", help="Send CI-V 17 FF unconditionally; emergency stop")
    stop.add_argument("--port", required=True)
    stop.add_argument("--baud", type=int, default=115200)
    subs.add_parser("audio-devices", help="List input devices (IC-7300 USB audio)")
    capture = subs.add_parser("audio-record", help="Record IC-7300 AF to PCM WAV, no TX")
    capture.add_argument("--device", type=int, required=True)
    capture.add_argument("--seconds", type=float, default=10.0)
    capture.add_argument("--sample-rate", type=int, default=48000)
    capture.add_argument("--out", required=True)
    decode = subs.add_parser("decode-wav", help="Experimental offline single-signal CW decoder")
    decode.add_argument("--wav", required=True)
    decode.add_argument("--tone", type=int, default=700)
    args = parser.parse_args(argv)
    try:
        if args.command == "radio-check":
            with IC7300.open_port(args.port, args.baud) as radio:
                print(json.dumps(radio.diagnostic(), ensure_ascii=False, indent=2))
        elif args.command == "cw-send":
            cfg = json.loads(Path(args.profile).read_text(encoding="utf-8"))
            if cfg.get("radio_model") != "ICOM IC-7300" or cfg.get("keying", {}).get("transmit_enabled") is not True:
                raise CIVError("transmit_enabled=false or not an IC-7300 profile")
            if not args.arm_rf or not args.menu_checked:
                raise CIVError("both --arm-rf and --menu-checked are mandatory")
            # Validate message before opening the serial port.
            make_cw_text_frame(args.text)
            with IC7300.open_port(args.port, args.baud) as radio:
                print(radio.transmit_once(args.text, user_armed=True, radio_menu_confirmed=True))
        elif args.command == "cw-abort":
            with IC7300.open_port(args.port, args.baud) as radio:
                radio.abort()
                print("CI-V stop command sent. Confirm RF TX has actually stopped on radio.")
        elif args.command == "audio-devices":
            from .audio_usb import list_devices
            for i, name, channels in list_devices():
                print(f"{i}: {name} ({channels} input channels)")
        elif args.command == "audio-record":
            from .audio_usb import capture_wav
            capture_wav(args.out, device=args.device, seconds=args.seconds, sample_rate=args.sample_rate)
            print(f"recorded PCM WAV: {args.out} (not decoded, no TX)")
        elif args.command == "decode-wav":
            from .audio_cw import decode_wav
            result = decode_wav(args.wav, args.tone)
            print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    except (CIVError, OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0
