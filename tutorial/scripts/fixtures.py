#!/usr/bin/env python3
"""Deterministic, speech-free synthetic Zoom multitrack fixture generator."""
from __future__ import annotations

import hashlib
import json
import math
import random
import struct
import wave
from pathlib import Path

from validate import ROOT

RECIPE_PATH = ROOT / "fixtures/recipes/synthetic-zoom-v1.json"
OUTPUT_DIR = ROOT / "generated/fixtures/synthetic-zoom-v1"


def active(time: float, intervals: list[list[float]]) -> bool:
    return any(start <= time < end for start, end in intervals)


def generate() -> dict:
    recipe = json.loads(RECIPE_PATH.read_text())
    rate = recipe["sample_rate"]
    count = int(recipe["duration_seconds"] * rate)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for track_index, track in enumerate(recipe["tracks"]):
        rng = random.Random(1100 + track_index)
        pcm = bytearray(count * 2)
        for index in range(count):
            time = index / rate
            value = 0.0
            if active(time, track["speech"]) and not active(time, [recipe["common_silence"]]):
                # A gated harmonic signal makes the fixture clearly synthetic, not a human voice.
                envelope = min(1, (time % .28) / .025, (.28 - time % .28) / .03)
                phase = 2 * math.pi * track["tone_hz"] * time
                value = track["gain"] * envelope * (math.sin(phase) + .22 * math.sin(phase * 2))
                if track.get("hum_hz"):
                    value += .05 * math.sin(2 * math.pi * track["hum_hz"] * time)
            if active(time, [track["cough"]] if track.get("cough") else []):
                value += .55 * (rng.random() * 2 - 1)
            if active(time, [track["local_noise"]] if track.get("local_noise") else []):
                value += .24 * (rng.random() * 2 - 1)
            sample = max(-32768, min(32767, round(value * 32767)))
            struct.pack_into("<h", pcm, index * 2, sample)
        path = OUTPUT_DIR / track["file"]
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(pcm)
        hashes[track["file"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"recipe_sha256": hashlib.sha256(RECIPE_PATH.read_bytes()).hexdigest(),
            "sample_rate": rate, "duration_seconds": recipe["duration_seconds"],
            "track_sha256": hashes, "output_dir": str(OUTPUT_DIR)}


if __name__ == "__main__":
    print(json.dumps(generate(), ensure_ascii=False, indent=2))
