#!/usr/bin/env python3
"""Single entrypoint for the S11 tutorial build."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from narration import cached, content_hash, generate, paths
from validate import ROOT, ContentDrift, validate


@contextlib.contextmanager
def demo_server(base_url: str | None):
    if base_url:
        yield base_url
        return
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://localhost:{port}"
    server = subprocess.Popen(["node", str(ROOT.parent / "tests/safety/s10b_preview_server.mjs"),
                               str(port), origin], cwd=ROOT.parent, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,
                              env={**os.environ, "S11_PREVIEW_PART_BYTES": "262144"})
    try:
        for _ in range(80):
            if server.poll() is not None:
                raise RuntimeError("in-memory demo server exited before readiness")
            try:
                with urllib.request.urlopen(origin + "/login", timeout=.5):
                    break
            except (OSError, urllib.error.URLError):
                time.sleep(.1)
        else:
            raise RuntimeError("in-memory demo server not ready")
        yield origin
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


def select(spec: dict, scene_id: str | None, chapter: str | None, slice_: bool) -> list[dict]:
    scenes = spec["scenes"]
    if slice_:
        scenes = [scene for scene in scenes if scene["id"] in ("002-zoom-multitrack", "006-archive-open")]
    elif scene_id:
        scenes = [scene for scene in scenes if scene["id"] == scene_id]
    if chapter:
        scenes = [scene for scene in scenes if scene["chapter"] == chapter]
    if not scenes:
        raise SystemExit("No scenes match selection")
    return scenes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("validate", "verify", "dry-run", "narration", "visual", "assemble", "all"))
    parser.add_argument("--scene")
    parser.add_argument("--chapter")
    parser.add_argument("--slice", action="store_true", help="mandatory vertical-slice scenes")
    parser.add_argument("--animations-only", action="store_true")
    parser.add_argument("--base-url", help="reuse an existing loopback in-memory preview")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if sum(bool(x) for x in (args.scene, args.chapter, args.slice)) > 1:
        parser.error("select only one of --scene, --chapter, --slice")
    if args.force and (args.mode != "narration" or not args.scene):
        parser.error("--force requires narration --scene")
    result = validate()
    spec = json.loads((ROOT / "tutorial.yaml").read_text())
    if args.mode == "validate":
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.mode == "verify":
        from verify import verify
        print(json.dumps(verify(), ensure_ascii=False))
        return
    scenes = select(spec, args.scene, args.chapter, args.slice)
    if args.animations_only:
        scenes = [scene for scene in scenes if scene["visual"]["type"] == "animation"]
        if not scenes:
            parser.error("selection contains no animation scenes")
    settings = spec["narration"]
    if args.mode == "dry-run":
        from capture import output_paths, probe, visual_hash
        from browser_capture import visual_hash as browser_visual_hash
        rows = []
        for scene in scenes:
            hit = cached(scene, settings) is not None
            mp3, timing = paths(scene)
            visual, meta_path = output_paths(scene)
            try:
                meta = json.loads(meta_path.read_text())
                expected_hash = browser_visual_hash(scene) if scene["visual"]["type"] == "browser" else visual_hash(scene)
                visual_hit = (visual.exists() and meta["visual_hash"] == expected_hash and
                              meta["expected_state"] == "PASS" and meta["browser_errors"] == 0 and
                              probe(visual)["duration_seconds"] >=
                              (cached(scene, settings) or {}).get("duration_seconds", float("inf")) +
                              sum(scene["padding"].values()) - .1)
            except (OSError, KeyError, ValueError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError):
                visual_hit = False
            rows.append({"scene": scene["id"], "chapter": scene["chapter"], "narration_cache": "HIT" if hit else "MISS",
                         "characters_to_generate": 0 if hit else len(scene["narration"]),
                         "visual_recapture": not visual_hit,
                         "outputs_expected_to_change": [] if hit and visual_hit else
                         ([str(mp3), str(timing)] if not hit else []) + ([str(visual)] if not visual_hit else [])})
        name = ("s11-vertical-slice" if args.slice else
                f"s11-{scenes[0]['id']}" if args.scene else
                f"s11-chapter-{args.chapter}" if args.chapter else "meser-audio-tutorial-ru")
        subtitle = "tutorial.ru" if name == "meser-audio-tutorial-ru" else f"{name}.ru"
        print(json.dumps({"content_validation": result, "selected_scenes": [scene["id"] for scene in scenes],
                          "assembly_outputs_expected_to_change": [
                              str(ROOT / f"generated/final/{name}.mp4"),
                              str(ROOT / f"generated/subtitles/{subtitle}.srt"),
                              str(ROOT / f"generated/subtitles/{subtitle}.vtt"),
                              str(ROOT / f"generated/manifests/{'build' if name == 'meser-audio-tutorial-ru' else name}.json"),
                              str(ROOT / f"generated/review/{'index' if name == 'meser-audio-tutorial-ru' else name}.html")],
                          "scenes": rows,
                          "approximate_characters_to_generate": sum(row["characters_to_generate"] for row in rows)},
                         ensure_ascii=False, indent=2))
        return
    if args.mode in ("narration", "all"):
        for scene in scenes:
            info, cache = generate(scene, settings, force=args.force)
            print(json.dumps({"scene": scene["id"], "cache": cache,
                              "duration_seconds": info["duration_seconds"],
                              "narration_hash": content_hash(scene, settings)}, ensure_ascii=False))
    if args.mode in ("visual", "all"):
        import asyncio
        from capture import capture as capture_animation
        from browser_capture import capture as capture_browser
        if any(scene["visual"]["type"] == "browser" for scene in scenes):
            from fixtures import generate as generate_fixtures
            generate_fixtures()
        for scene in scenes:
            runner = capture_browser if scene["visual"]["type"] == "browser" else capture_animation
            needs_demo = scene["visual"]["type"] == "browser"
            for attempt in range(2):
                try:
                    with demo_server(args.base_url) if needs_demo else contextlib.nullcontext(args.base_url or "http://localhost:1") as origin:
                        result = asyncio.run(runner(scene, settings, origin))
                    break
                except RuntimeError as error:
                    if attempt or not needs_demo or not str(error).startswith("browser capture produced only"):
                        raise
                    print(json.dumps({"scene": scene["id"], "capture_retry": "low screencast frame count"}))
            print(json.dumps({"scene": scene["id"], "visual_cache": result["cache"],
                              "capture_duration": result["duration_seconds"]}, ensure_ascii=False))
    if args.mode in ("assemble", "all"):
        from assemble import assemble
        name = ("s11-vertical-slice" if args.slice else
                f"s11-{scenes[0]['id']}" if args.scene else
                f"s11-chapter-{args.chapter}" if args.chapter else "meser-audio-tutorial-ru")
        print(json.dumps(assemble(scenes, spec, name=name), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except ContentDrift as error:
        raise SystemExit(str(error)) from None
