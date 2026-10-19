#!/usr/bin/env python3
"""Check the served B14 player pixels, not just its MP4 metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from b14_outro import OUT


def gray(png: bytes) -> bytes:
    return subprocess.check_output(
        ['ffmpeg', '-v', 'error', '-f', 'image2pipe', '-i', 'pipe:0',
         '-vf', 'scale=64:36:flags=area,format=gray', '-f', 'rawvideo', '-'],
        input=png,
    )


def visible_frame(png: bytes, label: str) -> bytes:
    pixels = gray(png)
    bright = sum(value > 45 for value in pixels) / len(pixels)
    if bright < .12 or max(pixels) - min(pixels) < 30:
        raise AssertionError(f'{label}: player is black despite loaded media ({bright:.3f} bright pixels)')
    return pixels


def seek(page, seconds: float, label: str, evidence: Path) -> bytes:
    page.locator('video').evaluate('''async (video, target) => {
      video.pause();
      video.currentTime = target;
      await new Promise((resolve, reject) => {
        if (!video.seeking && Math.abs(video.currentTime - target) < .1) return resolve();
        video.addEventListener('seeked', resolve, {once:true});
        setTimeout(() => reject(new Error('seek timed out')), 10000);
      });
    }''', seconds)
    page.wait_for_function('document.querySelector("video").readyState >= 2')
    # Media readiness is not a picture check. Give the compositor one frame,
    # then inspect the actual browser screenshot of the video element.
    page.wait_for_timeout(300)
    png = page.locator('video').screenshot(path=str(evidence / f'{label}.png'))
    return visible_frame(png, label)


def run(base: str, evidence: Path) -> dict:
    evidence.mkdir(parents=True, exist_ok=True)
    mp4 = OUT / 'B14.mp4'
    expected = hashlib.sha256(mp4.read_bytes()).hexdigest()
    media = base.rstrip('/') + '/B14.mp4'
    with urllib.request.urlopen(urllib.request.Request(media, headers={'Range': 'bytes=0-1023'})) as response:
        first = response.read()
        assert response.status == 206 and len(first) == 1024
        assert response.headers['Content-Type'] == 'video/mp4'
        assert response.headers['Content-Range'].startswith('bytes 0-1023/')
    with urllib.request.urlopen(media) as response:
        served = hashlib.sha256(response.read()).hexdigest()
    assert served == expected, 'player serves a different MP4'

    # This fixture reproduces the symptom: a loaded player surface that is
    # black apart from a narrow white subtitle stripe. Metadata tests pass
    # such a frame; the browser-pixel check must reject it.
    black = subprocess.check_output(
        ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=black:s=640x360',
         '-vf', 'drawbox=x=100:y=315:w=440:h=10:color=white:t=fill',
         '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-'])
    try:
        visible_frame(black, 'black-video regression fixture')
    except AssertionError:
        pass
    else:
        raise AssertionError('browser-pixel check failed to detect a black video with subtitles')

    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 644, 'height': 900})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base.rstrip('/') + '/index.html', wait_until='domcontentloaded')
        page.wait_for_function('document.querySelector("video").duration > 115')
        source = page.locator('video source').get_attribute('src')
        assert source.startswith('B14.mp4?v='), source
        samples = {name: seek(page, second, name, evidence) for name, second in
                   [('beginning', 4), ('archive-before-summary', 60),
                    ('separate-tracks', 80), ('announcement', 89),
                    ('speaker', 97), ('archive-summary', 107),
                    ('ending', 118), ('after-seek', 22)]}
        progression = ['beginning', 'archive-before-summary', 'separate-tracks',
                       'announcement', 'speaker', 'archive-summary', 'ending']
        for left, right in zip(progression, progression[1:]):
            change = sum(abs(a-b) for a,b in zip(samples[left], samples[right])) / len(samples[left])
            if change < 3:
                raise AssertionError(f'{left} and {right} browser frames did not update')
        before = page.locator('video').evaluate('(video) => video.currentTime')
        page.locator('video').evaluate('(video) => video.play()')
        page.wait_for_function('(before) => document.querySelector("video").currentTime > before + .4', arg=before)
        page.locator('video').evaluate('(video) => video.pause()')
        page.get_by_role('button', name='Восстановить изображение').click()
        page.wait_for_function('(before) => Math.abs(document.querySelector("video").currentTime - before) < 1', arg=before)
        page.wait_for_timeout(300)
        visible_frame(page.locator('video').screenshot(path=str(evidence/'after-recovery.png')), 'after recovery')
        page.evaluate('window.__playerBeforeReturn = document.querySelector("video")')
        # Headless Chromium does not always emit visibility events when a
        # second page becomes active. Exercise the same blur/focus lifecycle.
        page.evaluate('window.dispatchEvent(new Event("blur"))')
        page.wait_for_timeout(1200)
        page.evaluate('window.dispatchEvent(new Event("focus"))')
        page.wait_for_function('document.querySelector("video") !== window.__playerBeforeReturn')
        page.wait_for_function('(before) => Math.abs(document.querySelector("video").currentTime - before) < 1', arg=before)
        page.wait_for_timeout(300)
        visible_frame(page.locator('video').screenshot(path=str(evidence/'after-tab-return.png')), 'after tab return')
        if errors:
            raise AssertionError('player JavaScript errors: ' + '; '.join(errors))
        browser.close()
    return {'status': 'PASS', 'served_mp4_sha256': served, 'range_status': 206,
            'content_type': 'video/mp4', 'visible_frames': list(samples),
            'time_advanced': True, 'recovery_preserved_position': True,
            'tab_return_recreated_player': True,
            'black_fixture_rejected': True, 'javascript_errors': []}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--evidence', type=Path, default=OUT/'browser-player-check')
    args = parser.parse_args()
    report = run(args.base_url, args.evidence)
    (args.evidence/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
