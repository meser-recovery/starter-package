#!/usr/bin/env python3
"""Isolated Chrome capture of approved graphics or the real local Meser frontend."""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from narration import cached
from validate import ROOT, validate

ANIMATIONS = ROOT / "animations/explanations.html"
FRONTEND = ROOT.parent / "service/frontend"


def visual_hash(scene: dict) -> str:
    inputs = {"visual": scene["visual"], "initial_state": scene["initial_state"],
              "expected_state": scene["expected_state"], "assertions": scene["assertions"],
              "fixture_set": scene["fixture_set"], "viewport": [1920, 1080], "fps": 30,
              "demo_state_version": "s10b-in-memory-v1"}
    source = ANIMATIONS if scene["visual"]["type"] == "animation" else FRONTEND / (
        "Audio-Archive.html" if scene["chapter"] in ("archive", "management") else "Audio-Editor.html")
    inputs["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    inputs["capture_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def output_paths(scene: dict) -> tuple[Path, Path]:
    folder = "animations" if scene["visual"]["type"] == "animation" else "captures"
    path = ROOT / "generated" / folder / f"{scene['id']}.mp4"
    return path, path.with_suffix(".json")


def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                             "-of", "json", str(path)], capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    stream = info["streams"][0]
    if (stream["width"], stream["height"], stream["r_frame_rate"]) != (1920, 1080, "30/1"):
        raise RuntimeError("capture resolution/fps mismatch")
    return {"duration_seconds": float(info["format"]["duration"]), "resolution": [1920, 1080], "fps": 30}


async def capture(scene: dict, settings: dict, base_url: str) -> dict:
    from playwright.async_api import async_playwright
    narration = cached(scene, settings)
    if not narration:
        raise RuntimeError(f"narration missing or stale: {scene['id']}")
    duration = narration["duration_seconds"] + sum(scene["padding"].values())
    dest, meta_path = output_paths(scene)
    hash_value = visual_hash(scene)
    if dest.is_file() and meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
            if meta["visual_hash"] == hash_value and probe(dest)["duration_seconds"] >= duration - .1:
                return {**meta, "cache": "HIT"}
        except (KeyError, ValueError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError):
            pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(base_url)
    if parsed.hostname not in ("localhost", "127.0.0.1") or parsed.scheme != "http":
        raise RuntimeError("browser capture requires loopback demo server")
    network = []
    errors = []
    with tempfile.TemporaryDirectory(prefix="meser-s11-capture-") as temp:
        frames_dir = Path(temp)
        frames = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1920, "height": 1080},
                                                device_scale_factor=1, color_scheme="dark",
                                                service_workers="block", accept_downloads=False)
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            async def guard(route):
                url = route.request.url
                if url.startswith(base_url + "/"):
                    network.append({"method": route.request.method, "path": url.removeprefix(base_url)})
                    await route.continue_()
                else:
                    errors.append(f"blocked outbound request: {urlparse(url).hostname}")
                    await route.abort()
            await page.route("http://**/*", guard)
            await page.route("https://**/*", guard)

            if scene["visual"]["type"] == "animation":
                await page.goto(ANIMATIONS.as_uri() + f"?kind={scene['visual']['animation']}")
                if await page.title() != "Meser tutorial explanatory animation":
                    raise RuntimeError("animation source failed to load")
            elif scene["id"] == "006-archive-open":
                await page.goto(base_url + "/Audio-Archive.html")
                await page.locator("#admin-password").fill("local-test-password")
                await page.locator("#admin-access-form button[type=submit]").click()
                await page.wait_for_url("**/Audio-Archive.html")
                await page.goto(base_url + "/Audio-Editor.html")
                await page.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Archive.html"]').wait_for()
            else:
                raise RuntimeError(f"browser action not implemented: {scene['id']}")

            cdp = await context.new_cdp_session(page)
            pending = []
            async def receive(event):
                index = len(frames)
                frame = frames_dir / f"{index:06d}.jpg"
                frame.write_bytes(base64.b64decode(event["data"]))
                frames.append((frame, event["metadata"].get("timestamp")))
                await cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
            cdp.on("Page.screencastFrame", lambda event: pending.append(asyncio.create_task(receive(event))))
            await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88,
                                                     "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
            start_time = asyncio.get_running_loop().time()
            # A one-pixel capture-only repaint keeps CDP producing frames while the UI is still.
            await page.evaluate("""() => {let n=0; window.__s11paint=setInterval(()=>{
              let e=document.getElementById('__s11paint');
              if(!e){e=document.createElement('div');e.id='__s11paint';
                e.style='position:fixed;bottom:0;right:0;width:1px;height:1px;z-index:2147483647';document.body.append(e)}
              e.style.backgroundColor=n++%2?'#fff':'#000';},33)}""")
            if scene["visual"]["type"] == "animation":
                await page.evaluate("""ms => {const start=performance.now(); window.__s11progress=setInterval(()=>
                  window.setProgress(Math.min(1,(performance.now()-start)/ms)),100)}""", duration * 800)
            else:
                await asyncio.sleep(1)
                link = page.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Archive.html"]')
                box = await link.bounding_box()
                if not box:
                    raise RuntimeError("Archive link unavailable")
                await page.evaluate("""([x,y])=>{let p=document.createElement('div');p.id='__s11pointer';
                  p.style=`position:fixed;left:${x}px;top:${y}px;width:20px;height:20px;border:3px solid #fff;
                  border-radius:50%;box-shadow:0 0 0 5px #1d84fa;z-index:2147483647;pointer-events:none`;
                  document.body.append(p)}""", [box["x"] + box["width"]/2, box["y"] + box["height"]/2])
                await asyncio.sleep(.5)
                await link.click()
                await page.get_by_role("heading", name="Аудиоархив").wait_for()
                await page.evaluate("""() => {let n=0; window.__s11paint=setInterval(()=>{
                  let e=document.getElementById('__s11paint');
                  if(!e){e=document.createElement('div');e.id='__s11paint';
                    e.style='position:fixed;bottom:0;right:0;width:1px;height:1px;z-index:2147483647';document.body.append(e)}
                  e.style.backgroundColor=n++%2?'#fff':'#000';},33)}""")
            await asyncio.sleep(max(.1, duration - (asyncio.get_running_loop().time() - start_time)))
            await cdp.send("Page.stopScreencast")
            if pending:
                await asyncio.gather(*pending)
            if scene["visual"]["type"] == "browser":
                if not await page.get_by_role("heading", name="Аудиоархив").is_visible():
                    raise RuntimeError("expected Archive UI state missing")
            else:
                if not await page.locator(".visible").count():
                    raise RuntimeError("animation expected state missing")
            await browser.close()
        if errors:
            raise RuntimeError(f"capture browser errors: {errors[:3]}")
        if len(frames) < 30:
            raise RuntimeError(f"capture produced only {len(frames)} frames")
        candidate = dest.with_suffix(".tmp.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-i",
                        str(frames_dir / "%06d.jpg"), "-t", str(duration), "-vf", "scale=1920:1080,tpad=stop_mode=clone:stop_duration=2,fps=30",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                        str(candidate)], check=True)
        info = probe(candidate)
        if info["duration_seconds"] < narration["duration_seconds"]:
            raise RuntimeError("capture shorter than narration")
        candidate.replace(dest)
        meta = {"scene_id": scene["id"], "visual_hash": hash_value, "duration_seconds": info["duration_seconds"],
                "frame_count": len(frames), "network_requests": network,
                "production_mutation_requests": 0, "expected_state": "PASS", "browser_errors": 0}
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        return {**meta, "cache": "MISS"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--base-url", default="http://localhost:4185")
    args = parser.parse_args()
    validate()
    spec = json.loads((ROOT / "tutorial.yaml").read_text())
    scene = next((item for item in spec["scenes"] if item["id"] == args.scene), None)
    if scene is None:
        parser.error("unknown scene")
    result = asyncio.run(capture(scene, spec["narration"], args.base_url))
    print(json.dumps({key: value for key, value in result.items() if key != "network_requests"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
