"""Windows desktop entry point. '--self-check-out' checks packed runtime without RF."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check-out":
        # No serial-port enumeration, microphone recording or TX on this path.
        import sqlite3
        import tkinter
        import serial             # bundled pyserial
        import sounddevice        # bundled optional Windows Audio dependency
        from cwcontest import audio_cw, core, desktop_data, receive_monitor
        Path(sys.argv[2]).write_text(json.dumps({
            "application": "IC7300_CW_AutoContest",
            "packed_modules": ["tkinter", "sqlite3", "serial", "sounddevice", "cwcontest"],
            "cw_decoder_available": callable(audio_cw.decode_wav),
            "receive_monitor_available": callable(receive_monitor.decode_file),
            "transmitter_enabled": False,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if len(sys.argv) > 1:
        raise SystemExit("Unsupported argument. Use --self-check-out PATH")
    from cwcontest.desktop import main as launch_desktop
    launch_desktop()


if __name__ == "__main__":
    main()
