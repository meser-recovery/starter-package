"""Timing-derived subtitles, scene review clips, and deterministic FFmpeg master."""
from __future__ import annotations

import hashlib
import html
import json
import subprocess
import tempfile
from pathlib import Path

from narration import cached, content_hash, paths
from validate import ROOT, validate


def ffprobe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def duration(info: dict) -> float:
    return float(info["format"]["duration"])


def caption_font() -> Path:
    for path in ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"):
        if Path(path).is_file():
            return Path(path)
    raise RuntimeError("Unicode caption font unavailable")


def timestamp(seconds: float, srt: bool) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{whole:02}{',' if srt else '.'}{milliseconds:03}"


def cues(scene: dict, timing: dict, offset: float) -> list[tuple[float, float, str]]:
    alignment = timing["alignment"]
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    text = "".join(chars)
    if text != scene["narration"]:
        raise RuntimeError(f"timing text mismatch: {scene['id']}")
    groups = []
    begin = 0
    for index, char in enumerate(chars):
        current = "".join(chars[begin:index + 1]).strip()
        if (char in ".!?…" and len(current) >= 18) or len(current) >= 58 or index == len(chars) - 1:
            if current:
                indexes = [i for i in range(begin, index + 1) if not chars[i].isspace()]
                first, last = indexes[0], indexes[-1]
                cue_start = offset + scene["padding"]["head"] + starts[first]
                cue_end = offset + scene["padding"]["head"] + ends[last]
                if cue_end <= cue_start or cue_end > offset + timing["duration_seconds"] + sum(scene["padding"].values()) + .05:
                    raise RuntimeError(f"subtitle bounds invalid: {scene['id']}")
                groups.append((cue_start, cue_end, current.replace("\n", " ")))
            begin = index + 1
    return groups


def write_subtitles(all_cues: list, base: str) -> tuple[Path, Path]:
    folder = ROOT / "generated/subtitles"
    folder.mkdir(parents=True, exist_ok=True)
    srt = folder / f"{base}.srt"
    vtt = folder / f"{base}.vtt"
    srt.write_text("\n\n".join(f"{i}\n{timestamp(a, True)} --> {timestamp(b, True)}\n{text}"
                              for i, (a, b, text) in enumerate(all_cues, 1)) + "\n", encoding="utf-8")
    vtt.write_text("WEBVTT\n\n" + "\n\n".join(f"{timestamp(a, False)} --> {timestamp(b, False)}\n{text}"
                            for a, b, text in all_cues) + "\n", encoding="utf-8")
    return srt, vtt


def assemble(scenes: list[dict], spec: dict, *, name: str = "meser-audio-tutorial-ru") -> dict:
    validation = validate()
    generated = ROOT / "generated"
    review = generated / "review"
    review.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    all_cues = []
    offset = 0.0
    clips = []
    for scene in scenes:
        from capture import output_paths, probe, visual_hash
        from browser_capture import visual_hash as browser_visual_hash
        mp3, timing_path = paths(scene)
        timing = cached(scene, spec["narration"])
        if not timing:
            raise RuntimeError(f"current narration unavailable: {scene['id']}")
        visual, visual_meta_path = output_paths(scene)
        if not visual.exists() or not visual_meta_path.exists():
            raise RuntimeError(f"validated visual unavailable: {scene['id']}")
        visual_meta = json.loads(visual_meta_path.read_text())
        current_visual_hash = browser_visual_hash(scene) if scene["visual"]["type"] == "browser" else visual_hash(scene)
        if visual_meta["visual_hash"] != current_visual_hash:
            raise RuntimeError(f"stale visual hash: {scene['id']}")
        visual_info = probe(visual)
        if visual_meta["expected_state"] != "PASS" or visual_meta["browser_errors"]:
            raise RuntimeError(f"visual expected-state failed: {scene['id']}")
        if visual_meta["production_mutation_requests"]:
            raise RuntimeError(f"production mutation evidence: {scene['id']}")
        minimum_duration = timing["duration_seconds"] + sum(scene["padding"].values())
        if visual_info["duration_seconds"] < minimum_duration - .1:
            raise RuntimeError(f"capture too short: {scene['id']}")
        target_duration = max(minimum_duration, visual_info["duration_seconds"])
        all_cues.extend(cues(scene, timing, offset))
        clip = review / f"{scene['id']}.mp4"
        candidate = clip.with_suffix(".tmp.mp4")
        head_ms = round(scene["padding"]["head"] * 1000)
        command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(visual), "-i", str(mp3),
                   "-filter_complex", f"[1:a]adelay={head_ms}:all=1,apad[a]", "-map", "0:v:0", "-map", "[a]",
                   "-t", str(target_duration)]
        caption_path = None
        if scene["captions"]:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as caption_file:
                caption_file.write("\n".join(scene["captions"]))
                caption_path = Path(caption_file.name)
            font = caption_font()
            caption_y = (("620" if scene["id"] == "020-one-translator" else "780")
                         if scene["visual"]["type"] == "animation" else
                         "260" if scene["id"] == "049-final-download-save" else "h-text_h-96")
            command += ["-vf", f"drawtext=fontfile='{font}':textfile='{caption_path}':fontsize=42:fontcolor=white:"
                        f"box=1:boxcolor=black@0.76:boxborderw=22:line_spacing=8:x=(w-text_w)/2:y={caption_y}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p"]
        else:
            command += ["-c:v", "copy"]
        command += ["-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(candidate)]
        try:
            subprocess.run(command, check=True)
        finally:
            if caption_path:
                caption_path.unlink(missing_ok=True)
        clip_info = ffprobe(candidate)
        streams = clip_info["streams"]
        if not any(s["codec_name"] == "h264" and s["width"] == 1920 and s["height"] == 1080 for s in streams):
            raise RuntimeError("review clip video contract failed")
        if not any(s["codec_name"] == "aac" for s in streams):
            raise RuntimeError("review clip audio contract failed")
        candidate.replace(clip)
        clips.append(clip)
        manifest_rows.append({"scene_id": scene["id"], "chapter": scene["chapter"],
                              "canonical_refs": scene["canonical_refs"],
                              "narration_hash": content_hash(scene, spec["narration"]),
                              "visual_hash": visual_meta["visual_hash"],
                              "narration_duration": timing["duration_seconds"],
                              "capture_duration": visual_info["duration_seconds"],
                              "narration_cache": "HIT", "visual_cache": "HIT",
                              "cache_scope": "assemble validated existing media",
                              "artifacts": {"mp3": str(mp3), "timing": str(timing_path),
                                            "capture": str(visual), "preview": str(clip)},
                              "expected_state_validation": "PASS", "content_validation": "PASS", "status": "PASS",
                              "error": None,
                              "production_mutation_requests": visual_meta["production_mutation_requests"]})
        offset += duration(clip_info)
    subtitle_name = "tutorial.ru" if name == "meser-audio-tutorial-ru" else f"{name}.ru"
    srt, vtt = write_subtitles(all_cues, subtitle_name)
    if any(a < 0 or b > offset + .05 for a, b, _ in all_cues):
        raise RuntimeError("subtitle outside assembled timeline")
    final_dir = generated / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    final = final_dir / f"{name}.mp4"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as listing:
        for clip in clips:
            listing.write(f"file '{clip}'\n")
        list_path = Path(listing.name)
    try:
        candidate = final.with_suffix(".tmp.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-safe", "0", "-f", "concat", "-i", str(list_path),
                        "-c", "copy", "-movflags", "+faststart", str(candidate)], check=True)
        final_info = ffprobe(candidate)
        if abs(duration(final_info) - offset) > max(.2, .02 * len(scenes)):
            raise RuntimeError("master duration mismatch")
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(candidate), "-f", "null", "-"], check=True)
        candidate.replace(final)
    finally:
        list_path.unlink(missing_ok=True)
    frontend = ROOT.parent / "service/frontend"
    frontend_digest = hashlib.sha256()
    for path in sorted(path for path in frontend.rglob("*") if path.is_file()):
        frontend_digest.update(str(path.relative_to(frontend)).encode())
        frontend_digest.update(path.read_bytes())
    source_digest = hashlib.sha256()
    for path in sorted(path for path in ROOT.rglob("*") if path.is_file() and
                       not {"generated", "__pycache__"}.intersection(path.parts) and path.suffix != ".pyc"):
        source_digest.update(str(path.relative_to(ROOT)).encode())
        source_digest.update(path.read_bytes())
    manifest = {"repo_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "frontend_tree_sha256": frontend_digest.hexdigest(),
                "tutorial_source_sha256": source_digest.hexdigest(),
                "canonical_content": {"path": str(ROOT / spec["tutorial"]["canonical_content"]["source"]),
                                      "sha256": validation["pack_sha256"]},
                "schema_version": spec["schema_version"], "content_validation": validation,
                "selection": [scene["id"] for scene in scenes], "mode": "assemble",
                "final_validation": "PASS", "final": str(final), "final_duration": duration(final_info),
                "subtitles": [str(srt), str(vtt)], "production_mutation_requests": 0,
                "scenes": manifest_rows}
    manifest_dir = generated / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / ("build.json" if name == "meser-audio-tutorial-ru" else f"{name}.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    rows = "\n".join("<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in (
        item["scene_id"], item["chapter"], json.dumps(item["canonical_refs"], ensure_ascii=False),
        item["content_validation"], next(scene["narration"] for scene in scenes if scene["id"] == item["scene_id"]),
        item["narration_duration"], item["capture_duration"], item["narration_cache"], item["status"])) +
        f'<td><a href="{html.escape(Path(item["artifacts"]["preview"]).name)}">Preview</a></td></tr>'
        for item in manifest_rows)
    index = review / ("index.html" if name == "meser-audio-tutorial-ru" else f"{name}.html")
    index.write_text(f'<!doctype html><html lang="ru"><meta charset="utf-8"><title>Scene review</title><style>body{{font:16px Arial;padding:2rem;background:#101a2c;color:#eee}}td,th{{border:1px solid #456;padding:.6rem;vertical-align:top}}table{{border-collapse:collapse}}a{{color:#9cd}}</style><h1>Scene review</h1><table><thead><tr>{"".join(f"<th>{x}</th>" for x in ["Scene ID","Chapter","Canonical refs","Content","Narration","Narration duration","Capture duration","Cache","Validation","Preview"])}</tr></thead><tbody>{rows}</tbody></table></html>', encoding="utf-8")
    return {"final": str(final), "duration_seconds": duration(final_info), "manifest": str(manifest_path),
            "review_index": str(index), "subtitles": [str(srt), str(vtt)], "scene_count": len(scenes)}
