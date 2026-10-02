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

from modules import generate, selection, plan, members, scene_timing
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("validate", "verify", "dry-run", "narration", "visual", "assemble", "all"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--module")
    group.add_argument("--all-modules", action="store_true")
    group.add_argument("--scene", help="expands to its complete narration module")
    group.add_argument("--chapter")
    parser.add_argument("--pilot", action="store_true", help="historical isolated A/B/C pilot")
    parser.add_argument("--animations-only", action="store_true")
    parser.add_argument("--base-url", help="existing loopback in-memory preview")
    parser.add_argument("--force", action="store_true", help="regenerate one explicitly selected module")
    args = parser.parse_args()
    if args.pilot and any((args.module,args.all_modules,args.scene,args.chapter,args.animations_only,args.force,args.base_url)):
        parser.error("--pilot cannot be combined with module/capture flags")
    if args.force and (args.mode not in ("narration","dry-run") or not args.module):
        parser.error("--force requires narration/dry-run --module ID")
    if args.animations_only and args.mode not in ("visual","dry-run"):
        parser.error("--animations-only is a visual selection")
    result = validate()
    spec = json.loads((ROOT / "tutorial.yaml").read_text())
    if spec["schema_version"] == 2:
        from audio_approval import approved_path, validate_approval, validate_block_approval
        if args.pilot:
            parser.error("historical pilot is unavailable for the approved B01–B14 source")
        if args.chapter:
            parser.error("select an approved B-block; old chapters are historical")
        if args.mode == "validate":
            print(json.dumps(result, ensure_ascii=False)); return
        if args.mode in ("visual", "assemble", "verify"):
            if args.module not in ("B01", "B02") or args.all_modules or args.scene or args.force:
                raise RuntimeError("review gate: only approved B01 verification and B02 review are supported")
            if args.module == "B01":
                validate_approval(spec, "B01")
                if args.mode != "verify" and (ROOT / 'approvals/B01-block.json').exists():
                    raise RuntimeError('B01 complete block is approved and immutable')
                from b01_block import visual, assemble, verify
            else:
                validate_block_approval('B01')
                from b02_block import visual, assemble, verify
            if args.mode == "visual":
                import asyncio
                print(json.dumps(asyncio.run(visual()), ensure_ascii=False, indent=2))
            elif args.mode == "assemble":
                print(json.dumps(assemble(), ensure_ascii=False, indent=2))
            else:
                print(json.dumps(verify(), ensure_ascii=False, indent=2))
            return
        if args.mode not in ("dry-run", "narration"):
            raise RuntimeError("review gate: current B-block pipeline supports only selective audio and B02 visual/assembly")
        try:
            selected = selection(spec, args.module, args.scene, args.chapter)
        except ValueError as error:
            parser.error(str(error))
        if args.mode == "dry-run":
            print(json.dumps({"content_validation": result, **plan(spec, selected, args.force),
                              "review_gate": "B01_BLOCK_APPROVED_B02_VISUAL_REVIEW",
                              "approved_audio": "B01", "preserved_b02_audio": True,
                              "visual_changes": "B02_ONLY_UNTIL_APPROVED"}, ensure_ascii=False, indent=2)); return
        if len(selected) != 1 or args.module != selected[0]["id"]:
            raise RuntimeError("review gate: select exactly one B-block for narration")
        module_id = selected[0]["id"]
        if approved_path(module_id).exists():
            validate_approval(spec, module_id)
            raise RuntimeError(f"{module_id} audio is approved and immutable; TTS is forbidden")
        index = spec['review_policy']['block_order'].index(module_id)
        if index:
            previous = spec['review_policy']['block_order'][index-1]
            from audio_approval import validate_block_approval
            validate_block_approval(previous)
            if not selected[0].get('tts', {}).get('semantic_reviewed'):
                raise RuntimeError(f"{module_id} needs a documented semantic pause review before TTS")
        info, cache = generate(spec, selected[0], force=args.force)
        print(json.dumps({"module_id": module_id, "cache": cache,
                          "duration_seconds": info["timing"]["duration_seconds"],
                          "audio_sha256": info["metadata"]["audio_sha256"],
                          "timing_sha256": info["metadata"]["timing_sha256"]}, ensure_ascii=False)); return
    if args.pilot:
        from pilot import run
        run(args.mode, spec)
        return
    if args.mode == "validate":
        print(json.dumps(result, ensure_ascii=False)); return
    if args.mode == "verify":
        from module_assemble import verify
        print(json.dumps(verify(spec), ensure_ascii=False)); return
    try:
        selected = selection(spec,args.module,args.scene,args.chapter)
    except ValueError as error:
        parser.error(str(error))
    scenes = [s for m in selected for s in members(spec,m)]
    if args.animations_only:
        scenes = [s for s in scenes if s["visual"]["type"] == "animation"]
    if args.mode == "dry-run":
        from module_visuals import cached as visual_cached, OUT
        rows=[]
        for scene in spec['scenes']:
            try:
                timing=scene_timing(spec,scene)
                hit=bool(visual_cached(spec,scene,timing))
            except RuntimeError:
                hit=False
            rows.append({'scene_id':scene['id'],'selected':scene in scenes,'visual_cache':'HIT' if hit else 'MISS',
                         'render_required':scene in scenes and not hit})
        print(json.dumps({'content_validation':result,**plan(spec,selected,args.force),'visuals':rows,
                          'assembly_output':str(OUT/'meser-audio-tutorial-v3.mp4')},ensure_ascii=False,indent=2)); return
    if args.mode in ("narration", "all"):
        for module in selected:
            info, cache = generate(spec,module,force=args.force)
            print(json.dumps({'module_id':module['id'],'cache':cache,
                              'duration_seconds':info['timing']['duration_seconds']},ensure_ascii=False),flush=True)
    if args.mode in ("visual", "all"):
        import asyncio
        from module_visuals import render
        asyncio.run(render(spec,scenes,args.base_url))
    if args.mode in ("assemble", "all"):
        from module_assemble import assemble
        # Selective builds never generate missing unselected modules to complete the master.
        print(json.dumps(assemble(spec),ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except ContentDrift as error:
        raise SystemExit(str(error)) from None
