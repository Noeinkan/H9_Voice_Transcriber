"""Record a sample of your own voice so transcripts can call you Person 1.

Run it once:

    python enroll_voice.py              record 30 s from the default microphone
    python enroll_voice.py sample.m4a   use an existing recording instead
    python enroll_voice.py --list-devices

It writes voice/me.wav (the sample, so you can check it) and voice/me.npy
(the fingerprint the transcriber compares against). Re-run it any time to
replace both.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

import voice_id

DEFAULT_SECONDS = 30
MIN_LEVEL = 0.01  # anything quieter than this is a dead microphone


def list_devices() -> int:
    import sounddevice

    print(sounddevice.query_devices())
    return 0


def record(seconds: int, device: int | None) -> np.ndarray:
    import sounddevice

    print(f"Recording {seconds} seconds from the microphone.")
    print("Talk normally - read anything out loud, pauses are fine.")
    for count in (3, 2, 1):
        print(f"  starting in {count}...", flush=True)
        time.sleep(1)
    print("  GO", flush=True)

    frames = sounddevice.rec(
        int(seconds * voice_id.SAMPLE_RATE),
        samplerate=voice_id.SAMPLE_RATE,
        channels=1,
        dtype="float32",
        device=device,
    )
    sounddevice.wait()
    print("  done recording")
    return frames.reshape(-1)


def load_file(path: Path) -> np.ndarray:
    import faster_whisper

    print(f"Reading {path}")
    return faster_whisper.decode_audio(str(path), sampling_rate=voice_id.SAMPLE_RATE)


def main() -> int:
    parser = argparse.ArgumentParser(description="Enroll your voice as Person 1.")
    parser.add_argument("source", nargs="?", help="audio file to use instead of recording")
    parser.add_argument("--seconds", type=int, default=DEFAULT_SECONDS)
    parser.add_argument("--device", type=int, default=None, help="microphone index")
    parser.add_argument("--list-devices", action="store_true")
    args = parser.parse_args()

    if args.list_devices:
        return list_devices()

    if args.source:
        source = Path(args.source)
        if not source.is_file():
            print(f"No such file: {source}")
            return 1
        waveform = load_file(source)
    else:
        try:
            waveform = record(args.seconds, args.device)
        except Exception as exc:  # no microphone, driver refused, wrong index
            print(f"Could not record from the microphone: {exc}")
            print("Record a voice memo on your phone and pass it instead:")
            print("    python enroll_voice.py my_voice.m4a")
            return 1

    duration = len(waveform) / voice_id.SAMPLE_RATE
    level = float(np.max(np.abs(waveform))) if waveform.size else 0.0
    print(f"Captured {duration:.0f} s, peak level {level:.3f}")

    if duration < 5:
        print("That is too short to be a reliable fingerprint. Aim for 20-30 s.")
        return 1
    if level < MIN_LEVEL:
        print("The audio is silent. Check the microphone and try again")
        print("(python enroll_voice.py --list-devices, then --device N).")
        return 1

    voice_id.VOICE_DIR.mkdir(parents=True, exist_ok=True)
    import soundfile

    soundfile.write(str(voice_id.SAMPLE_FILE), waveform, voice_id.SAMPLE_RATE)
    print(f"Saved sample to {voice_id.SAMPLE_FILE}")

    print("Building the voice fingerprint (first run downloads titanet_large)...")
    vector = voice_id.embed_waveform(waveform)
    path = voice_id.save_enrollment(vector)
    print(f"Saved fingerprint to {path}")
    print()
    print("Done. From now on, when your voice is in a recording it is Person 1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
