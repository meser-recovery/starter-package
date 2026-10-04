#!/usr/bin/env python3
"""Check B01/B02 review media as decoded pixels in their actual local players."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from reopen_b01_b02 import OUT

SAMPLES = {'B01': [('beginning', 4), ('figures-start', 28.9), ('figures-separated', 30.3),
                   ('middle', 60), ('editor', 119), ('ending', 120.4), ('after-seek', 20)],
           'B02': [('beginning', 4), ('storage', 12), ('wave-before-split', 18.8),
                   ('wave-after-split', 23), ('announcement', 53), ('speaker', 66),
                   ('end', 106.5), ('after-seek', 35)]}


def pixels(png: bytes) -> bytes:
    return subprocess.check_output(['ffmpeg', '-v', 'error', '-f', 'image2pipe', '-i', 'pipe:0',
                                    '-vf', 'scale=64:36:flags=area,format=gray',
                                    '-f', 'rawvideo', 'pipe:1'], input=png)


def visible(png: bytes, label: str) -> bytes:
    data = pixels(png)
    if sum(value > 45 for value in data)/len(data) < .12 or max(data)-min(data) < 30:
        raise AssertionError(f'{label}: browser video surface is black or uniform')
    return data


def seek(page, second: float, label: str, evidence: Path) -> bytes:
    page.locator('video').evaluate('''async (video, target) => {
      video.pause(); video.currentTime=target;
      await new Promise((resolve,reject)=>{
        if(!video.seeking && Math.abs(video.currentTime-target)<.1)return resolve();
        video.addEventListener('seeked',resolve,{once:true});
        setTimeout(()=>reject(new Error('seek timeout')),10000);
      });
    }''', second)
    page.wait_for_function('document.querySelector("video").readyState >= 2')
    page.wait_for_timeout(250)
    return visible(page.locator('video').screenshot(path=str(evidence/f'{label}.png')), label)


def run(block: str, base: str) -> dict:
    folder = OUT[block]
    evidence = folder/'browser-player-check'; evidence.mkdir(exist_ok=True)
    route = f'{block.lower()}-reopen-review'
    media = f'{base.rstrip("/")}/{route}/{block}.mp4'
    expected = hashlib.sha256((folder/f'{block}.mp4').read_bytes()).hexdigest()
    with urllib.request.urlopen(urllib.request.Request(media, headers={'Range':'bytes=0-1023'})) as response:
        assert response.status == 206 and len(response.read()) == 1024
        assert response.headers['Content-Type'] == 'video/mp4'
    with urllib.request.urlopen(media) as response:
        served = hashlib.sha256(response.read()).hexdigest()
    assert served == expected, f'{block} player serves different MP4'
    errors=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch()
        page=browser.new_page(viewport={'width':680,'height':900})
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(f'{base.rstrip("/")}/{route}/index.html',wait_until='domcontentloaded')
        page.wait_for_function('document.querySelector("video").duration > 100')
        samples={name:seek(page,second,name,evidence) for name,second in SAMPLES[block]}
        first=samples['beginning'];middle=samples['middle' if block=='B01' else 'speaker']
        end=samples['ending' if block=='B01' else 'end']
        for name,a,b in [('beginning-middle',first,middle),('middle-end',middle,end)]:
            if sum(abs(x-y) for x,y in zip(a,b))/len(a)<3:
                raise AssertionError(f'{block} {name} frames did not visibly change')
        before=page.locator('video').evaluate('(video)=>video.currentTime')
        page.locator('video').evaluate('(video)=>video.play()')
        page.wait_for_function('(before)=>document.querySelector("video").currentTime>before+.4',arg=before)
        page.locator('video').evaluate('(video)=>video.pause()')
        other=browser.new_page();other.goto('about:blank');other.bring_to_front()
        page.bring_to_front();page.wait_for_timeout(300)
        visible(page.locator('video').screenshot(path=str(evidence/'after-tab-return.png')),'after tab return')
        assert not errors, errors
        browser.close()
    result={'status':'PASS','served_mp4_sha256':served,'range_status':206,'mime':'video/mp4',
            'browser_visible_frames':list(samples),'time_advanced':True,
            'visible_after_seek':True,'visible_after_tab_return':True,'javascript_errors':[]}
    (evidence/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('block',choices=('B01','B02'))
    parser.add_argument('--base-url',required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.block,args.base_url),ensure_ascii=False,indent=2))
