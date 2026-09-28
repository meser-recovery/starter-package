"""Per-scene ElevenLabs timestamps and validated local cache."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from validate import ROOT

NARRATION_DIR = ROOT / "generated/narration"


def content_hash(scene: dict, settings: dict) -> str:
    payload = {
        "text": scene["narration"],
        "voice_id": settings["voice_id"],
        "model_id": settings["model_id"],
        "output_format": settings["output_format"],
        "voice_settings": settings["voice_settings"],
        "pronunciation": settings["pronunciation"],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode()).hexdigest()


def probe_duration(path: Path) -> float:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
                            capture_output=True, text=True, check=True)
    duration = float(result.stdout.strip())
    if not 0 < duration < 3600:
        raise ValueError("invalid MP3 duration")
    return duration


def paths(scene: dict) -> tuple[Path, Path]:
    return NARRATION_DIR / f"{scene['id']}.mp3", NARRATION_DIR / f"{scene['id']}.timing.json"


def cached(scene: dict, settings: dict) -> dict | None:
    mp3, timing = paths(scene)
    if not mp3.is_file() or not timing.is_file():
        return None
    try:
        info = json.loads(timing.read_text())
        if info["narration_hash"] != content_hash(scene, settings):
            return None
        if info["mp3_sha256"] != hashlib.sha256(mp3.read_bytes()).hexdigest():
            return None
        alignment = info["alignment"]
        count = len(alignment["characters"])
        if count != len(alignment["character_start_times_seconds"]) or count != len(alignment["character_end_times_seconds"]):
            return None
        if count == 0 or "".join(alignment["characters"]) != scene["narration"]:
            return None
        if any(a < 0 or b < a for a, b in zip(alignment["character_start_times_seconds"],
                                               alignment["character_end_times_seconds"])):
            return None
        if abs(probe_duration(mp3) - info["duration_seconds"]) > 0.05:
            return None
        return info
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        env = Path.home() / ".codex/.env"
        if env.is_file():
            for line in env.read_text().splitlines():
                if line.startswith("ELEVENLABS_API_KEY="):
                    key = line.partition("=")[2].strip().strip('"').strip("'")
                    break
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY unavailable")
    return key


def generate(scene: dict, settings: dict, *, force: bool = False) -> tuple[dict, str]:
    existing = cached(scene, settings)
    if existing and not force:
        return existing, "HIT"
    # Only call after the entire YAML/pack mapping has passed CONTENT_DRIFT validation.
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{settings['voice_id']}/with-timestamps"
           f"?output_format={settings['output_format']}")
    body = {"text": scene["narration"], "model_id": settings["model_id"]}
    if settings["voice_settings"]:
        body["voice_settings"] = settings["voice_settings"]
    request = urllib.request.Request(url, json.dumps(body, ensure_ascii=False).encode(),
                                     {"xi-api-key": api_key(), "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        # The response may contain account details; never put it in logs or manifests.
        raise RuntimeError(f"ElevenLabs HTTP {error.code} for {scene['id']}") from None
    mp3_bytes = base64.b64decode(result["audio_base64"], validate=True)
    alignment = result.get("alignment") or result.get("normalized_alignment")
    if not isinstance(alignment, dict):
        raise RuntimeError(f"ElevenLabs timestamps missing for {scene['id']}")
    if "".join(alignment.get("characters", [])) != scene["narration"]:
        raise RuntimeError(f"ElevenLabs timestamps differ from narration for {scene['id']}")
    NARRATION_DIR.mkdir(parents=True, exist_ok=True)
    mp3, timing = paths(scene)
    with tempfile.NamedTemporaryFile(dir=NARRATION_DIR, suffix=".mp3", delete=False) as temporary:
        temporary.write(mp3_bytes)
        candidate = Path(temporary.name)
    try:
        duration = probe_duration(candidate)
        info = {"scene_id": scene["id"], "narration_hash": content_hash(scene, settings),
                "mp3_sha256": hashlib.sha256(mp3_bytes).hexdigest(), "duration_seconds": duration,
                "alignment": alignment}
        # Preserve the old valid cache until both replacements are ready.
        with tempfile.NamedTemporaryFile(dir=NARRATION_DIR, suffix=".json", mode="w", encoding="utf-8", delete=False) as temporary:
            json.dump(info, temporary, ensure_ascii=False)
            timing_candidate = Path(temporary.name)
        candidate.replace(mp3)
        timing_candidate.replace(timing)
        if not cached(scene, settings):
            raise RuntimeError(f"generated narration failed cache validation: {scene['id']}")
        return info, "MISS"
    finally:
        candidate.unlink(missing_ok=True)
