"""Windows USB Audio recording through sounddevice 0.5.6 (optional).

Records only; live self-running on-air QSO control is NOT enabled.
"""
from __future__ import annotations

import wave


def list_devices():
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice==0.5.6 required: pip install '.[audio]'") from exc
    return [(i, str(d['name']), int(d['max_input_channels']))
            for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0]


def capture_wav(out: str, *, device: int, seconds: float = 10.0,
                sample_rate: int = 48000):
    if seconds <= 0 or seconds > 120 or sample_rate not in (16000, 48000):
        raise ValueError("invalid recording duration or sample rate")
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice==0.5.6 required: pip install '.[audio]'") from exc
    # Blocking RawInputStream outputs raw bytes: no data buffers are sent to radio.
    with sd.RawInputStream(device=device, samplerate=sample_rate,
                           channels=1, dtype='int16', blocksize=1024) as stream:
        with wave.open(out, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            remaining = int(round(seconds * sample_rate))
            while remaining:
                block, overflow = stream.read(min(1024, remaining))
                if overflow:
                    raise RuntimeError("audio input overflow; recording invalid")
                wav.writeframes(block)
                remaining -= len(block) // 2
