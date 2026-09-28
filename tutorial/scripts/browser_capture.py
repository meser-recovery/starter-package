#!/usr/bin/env python3
"""Record real Meser actions in an isolated Chrome context against loopback only."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from capture import output_paths, probe
from narration import cached
from scenes import FIXTURES, perform, prepare
from validate import ROOT

FRONTEND = ROOT.parent / "service/frontend"


def visual_hash(scene: dict) -> str:
    digest = hashlib.sha256()
    for path in sorted([*FRONTEND.glob("Audio-*.html"), *FRONTEND.glob("scripts/*.mjs"),
                        *FRONTEND.glob("scripts/*.js"), *FRONTEND.glob("styles/*.css"),
                        ROOT / "fixtures/recipes/synthetic-zoom-v1.json", ROOT / "scripts/fixtures.py",
                        *FIXTURES.glob("*.wav"), Path(__file__), ROOT / "scripts/scenes.py"]):
        digest.update(str(path.relative_to(ROOT.parent)).encode())
        digest.update(path.read_bytes())
    payload = {"visual": scene["visual"], "initial_state": scene["initial_state"],
               "expected_state": scene["expected_state"], "assertions": scene["assertions"],
               "fixture_set": scene["fixture_set"], "frontend_and_recipes_sha256": digest.hexdigest(),
               "demo_state_version": "s10b-in-memory-v1", "viewport": [1920, 1080], "fps": 30}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def capture(scene: dict, settings: dict, base_url: str) -> dict:
    from playwright.async_api import async_playwright

    if scene["visual"]["type"] != "browser":
        raise RuntimeError("browser_capture received non-browser scene")
    narration = cached(scene, settings)
    if not narration:
        raise RuntimeError(f"narration missing or stale: {scene['id']}")
    if not all(path.exists() for path in FIXTURES.glob("*.wav")) or len(list(FIXTURES.glob("*.wav"))) != 4:
        raise RuntimeError("synthetic fixtures missing")
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1"):
        raise RuntimeError("browser capture requires loopback demo server")
    target_duration = narration["duration_seconds"] + sum(scene["padding"].values())
    dest, meta_path = output_paths(scene)
    current_hash = visual_hash(scene)
    if dest.is_file() and meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
            if meta["visual_hash"] == current_hash and probe(dest)["duration_seconds"] >= target_duration - .1:
                return {**meta, "cache": "HIT"}
        except (KeyError, ValueError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError):
            pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    network = Counter()
    with tempfile.TemporaryDirectory(prefix="meser-s11-browser-") as temp:
        folder = Path(temp)
        frames = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1,
                                                color_scheme="light", service_workers="block", accept_downloads=False)
            # A capture-only ring makes actual DOM-driven pointer clicks visible.
            await context.add_init_script("""(() => {
              document.addEventListener('pointerdown', event => {
                const old=document.getElementById('__s11click'); old?.remove();
                const ring=document.createElement('div'); ring.id='__s11click';
                ring.style=`position:fixed;left:${event.clientX-15}px;top:${event.clientY-15}px;width:30px;height:30px;
                  border:3px solid #0b76e0;border-radius:50%;box-shadow:0 0 0 5px #fff9;z-index:2147483647;pointer-events:none`;
                document.body.append(ring); setTimeout(()=>ring.remove(),900);
              },true);
            })()""")
            context.on("page", lambda opened: opened.on("pageerror", lambda error: errors.append(str(error))))
            page = await context.new_page()

            async def guard(route):
                url = route.request.url
                if url.startswith(base_url + "/"):
                    network[f"{route.request.method} {urlparse(url).path}"] += 1
                    await route.continue_()
                else:
                    errors.append(f"outbound request blocked: {urlparse(url).hostname}")
                    await route.abort()
            await context.route("http://**/*", guard)
            await context.route("https://**/*", guard)
            await prepare(page, scene, base_url)
            if errors:
                raise RuntimeError(f"browser preparation errors: {errors[:3]}")
            cdp = await context.new_cdp_session(page)
            pending = []
            stopping = False
            async def receive(event):
                frame = folder / f"{len(frames):06d}.jpg"
                frame.write_bytes(base64.b64decode(event["data"]))
                frames.append(frame)
                try:
                    await cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
                except Exception:
                    if not stopping:
                        raise
            cdp.on("Page.screencastFrame", lambda event: pending.append(asyncio.create_task(receive(event))))
            await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88,
                                                     "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
            started = asyncio.get_running_loop().time()
            repaint = """() => {if(window.__s11paint)clearInterval(window.__s11paint);let n=0;window.__s11paint=setInterval(()=>{
              let e=document.getElementById('__s11paint');
              if(!e){e=document.createElement('div');e.id='__s11paint';
                e.style='position:fixed;bottom:0;right:0;width:1px;height:1px;z-index:2147483647';document.body.append(e)}
              e.style.backgroundColor=n++%2?'#fff':'#000';},33)}"""
            await page.evaluate(repaint)
            opened = await perform(page, scene, base_url)
            if opened is not None:
                stopping = True
                await cdp.send("Page.stopScreencast")
                if pending:
                    await asyncio.gather(*pending)
                page = opened
                cdp = await context.new_cdp_session(page)
                stopping = False
                cdp.on("Page.screencastFrame", lambda event: pending.append(asyncio.create_task(receive(event))))
                await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88,
                                                         "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
            await page.evaluate(repaint)
            await asyncio.sleep(max(1.0, target_duration - (asyncio.get_running_loop().time() - started)))
            alerts = page.locator('[role="alert"]:visible')
            if await alerts.count():
                raise RuntimeError(f"unexpected browser error banner: {await alerts.first.inner_text()}")
            stopping = True
            await cdp.send("Page.stopScreencast")
            await asyncio.sleep(.15)
            if pending:
                await asyncio.gather(*pending)
            await browser.close()
        if errors:
            raise RuntimeError(f"browser errors: {errors[:3]}")
        if len(frames) < 20:
            raise RuntimeError(f"browser capture produced only {len(frames)} frames")
        elapsed = max(target_duration, asyncio.get_running_loop().time() - started)
        tail_pad = max(2.0, elapsed - len(frames) / 30 + 1)
        candidate = dest.with_suffix(".tmp.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-i",
                        str(folder / "%06d.jpg"), "-t", str(elapsed),
                        "-vf", f"scale=1920:1080,tpad=stop_mode=clone:stop_duration={tail_pad:.3f},fps=30",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                        str(candidate)], check=True)
        info = probe(candidate)
        if info["duration_seconds"] < target_duration - .1:
            raise RuntimeError("browser capture shorter than narration")
        candidate.replace(dest)
        meta = {"scene_id": scene["id"], "visual_hash": current_hash,
                "duration_seconds": info["duration_seconds"], "frame_count": len(frames),
                "network_requests": dict(network), "production_mutation_requests": 0,
                "expected_state": "PASS", "browser_errors": 0}
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        return {**meta, "cache": "MISS"}
