#!/usr/bin/env python3
"""Verify every artifact of a locally generated full tutorial candidate."""
from __future__ import annotations

import json
import hashlib
import re
import subprocess
import wave

from assemble import ffprobe
from browser_capture import visual_hash as browser_hash
from capture import output_paths, probe, visual_hash as animation_hash
from fixtures import OUTPUT_DIR, RECIPE_PATH
from narration import cached
from validate import ROOT, validate


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def cue_times(path):
    require(path.is_file(), f"missing subtitles: {path}")
    cues = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if " --> " not in line:
            continue
        pair = []
        for value in line.split(" --> ", 1):
            match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", value)
            require(match is not None, f"invalid subtitle time: {value}")
            h, m, s, ms = map(int, match.groups())
            require(m < 60 and s < 60, f"invalid subtitle time: {value}")
            pair.append(h * 3600 + m * 60 + s + ms / 1000)
        cues.append(pair)
    require(cues, f"no subtitle cues: {path}")
    return cues


def verify() -> dict:
    content = validate()
    spec = json.loads((ROOT / "tutorial.yaml").read_text(encoding="utf-8"))
    scenes = spec["scenes"]
    require(len(scenes) == 60, "full candidate requires 60 scenes")
    recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
    for track in recipe["tracks"]:
        path = OUTPUT_DIR / track["file"]
        require(path.is_file(), f"synthetic fixture missing: {track['file']}")
        with wave.open(str(path)) as audio:
            require((audio.getnchannels(), audio.getframerate(), audio.getnframes()) ==
                    (1, recipe["sample_rate"], recipe["sample_rate"] * recipe["duration_seconds"]),
                    f"synthetic fixture format failed: {track['file']}")
    manifest = json.loads((ROOT / "generated/manifests/build.json").read_text(encoding="utf-8"))
    source_digest = hashlib.sha256()
    for path in sorted(path for path in ROOT.rglob("*") if path.is_file() and
                       not {"generated", "__pycache__"}.intersection(path.parts) and path.suffix != ".pyc"):
        source_digest.update(str(path.relative_to(ROOT)).encode())
        source_digest.update(path.read_bytes())
    frontend = ROOT.parent / "service/frontend"
    frontend_digest = hashlib.sha256()
    for path in sorted(path for path in frontend.rglob("*") if path.is_file()):
        frontend_digest.update(str(path.relative_to(frontend)).encode())
        frontend_digest.update(path.read_bytes())
    require(manifest["canonical_content"]["sha256"] == content["pack_sha256"] and
            manifest["tutorial_source_sha256"] == source_digest.hexdigest() and
            manifest["frontend_tree_sha256"] == frontend_digest.hexdigest() and
            manifest["content_validation"]["status"] == "PASS" and
            manifest["selection"] == [scene["id"] for scene in scenes] and
            manifest["final_validation"] == "PASS" and manifest["production_mutation_requests"] == 0,
            "full build manifest failed")
    rows = {row["scene_id"]: row for row in manifest["scenes"]}
    require(len(rows) == 60, "manifest scene coverage failed")
    for scene in scenes:
        sid = scene["id"]
        timing = cached(scene, spec["narration"])
        require(timing is not None, f"MP3/timestamps missing or invalid: {sid}")
        visual, meta_path = output_paths(scene)
        require(visual.is_file() and meta_path.is_file(), f"capture missing: {sid}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        expected = browser_hash(scene) if scene["visual"]["type"] == "browser" else animation_hash(scene)
        require(meta["visual_hash"] == expected and meta["expected_state"] == "PASS" and
                meta["browser_errors"] == 0 and meta["production_mutation_requests"] == 0,
                f"capture state failed: {sid}")
        require(probe(visual)["duration_seconds"] + .1 >= timing["duration_seconds"] + sum(scene["padding"].values()),
                f"capture shorter than narration: {sid}")
        row = rows[sid]
        require(row["status"] == "PASS" and row["content_validation"] == "PASS" and
                row["expected_state_validation"] == "PASS" and row["production_mutation_requests"] == 0,
                f"scene report failed: {sid}")
        clip = ROOT / "generated/review" / f"{sid}.mp4"
        require(clip.is_file(), f"review clip missing: {sid}")
        info = ffprobe(clip)
        require(any(s.get("codec_name") == "h264" and s.get("width") == 1920 and s.get("height") == 1080
                    for s in info["streams"]) and any(s.get("codec_name") == "aac" for s in info["streams"]),
                f"review clip codec failed: {sid}")
        require(float(info["format"]["duration"]) + .1 >= timing["duration_seconds"],
                f"review clip too short: {sid}")
    final = ROOT / "generated/final/meser-audio-tutorial-ru.mp4"
    info = ffprobe(final)
    video = [s for s in info["streams"] if s.get("codec_type") == "video"]
    audio = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    require(len(video) == 1 and video[0].get("codec_name") == "h264" and
            (video[0].get("width"), video[0].get("height"), video[0].get("r_frame_rate")) ==
            (1920, 1080, "30/1") and len(audio) == 1 and audio[0].get("codec_name") == "aac",
            "final codec/resolution/fps failed")
    duration = float(info["format"]["duration"])
    srt = cue_times(ROOT / "generated/subtitles/tutorial.ru.srt")
    vtt = cue_times(ROOT / "generated/subtitles/tutorial.ru.vtt")
    require(len(srt) == len(vtt) and all(0 <= a < b <= duration + .05 for a, b in srt + vtt),
            "subtitle cue count/bounds failed")
    require((ROOT / "generated/review/index.html").is_file(), "review index missing")
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(final), "-f", "null", "-"], check=True)
    return {"status": "PASS", "scenes": 60, "chapters": len(spec["tutorial"]["chapters"]),
            "subtitle_cues": len(srt), "duration_seconds": duration,
            "codec": "H.264/AAC", "resolution": "1920x1080", "fps": 30,
            "full_decode": "PASS", "production_mutation_requests": 0}


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
