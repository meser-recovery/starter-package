#!/usr/bin/env python3
"""Exercise the served complete candidate in a native browser video player."""
import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
from final_assemble import OUT, parse_srt
from modules import write_json


def visible(page,label,evidence):
    png=page.locator('video').screenshot(path=str(evidence/f'{label}.png'))
    raw=subprocess.check_output(['ffmpeg','-v','error','-f','image2pipe','-i','pipe:0',
        '-vf','crop=iw:ih*0.82:0:0,scale=64:36:flags=area,format=gray','-f','rawvideo','-'],input=png)
    if max(raw)-min(raw)<30 or sum(x>45 for x in raw)/len(raw)<.003:
        raise RuntimeError(f'{label}: black/uniform browser video surface')
    return raw


def seek(page,second):
    page.locator('video').evaluate('''async(v,t)=>{v.pause();v.currentTime=t;
      await new Promise((resolve,reject)=>{if(!v.seeking&&Math.abs(v.currentTime-t)<.05)return resolve();
        v.addEventListener('seeked',resolve,{once:true});setTimeout(()=>reject(Error('seek timeout')),10000)})}''',second)
    page.wait_for_function('document.querySelector("video").readyState>=2')
    page.wait_for_timeout(80)


def run(base):
    manifest=json.loads((OUT/'manifest.json').read_text());evidence=OUT/'browser-player-check';evidence.mkdir(exist_ok=True)
    origin=f'{base.rstrip("/")}/{OUT.name}';url=f'{origin}/S11.mp4'
    with urllib.request.urlopen(urllib.request.Request(url,headers={'Range':'bytes=1024-2047'})) as response:
        if response.status!=206 or len(response.read())!=1024 or response.headers['Content-Type']!='video/mp4':
            raise RuntimeError('Range or media MIME invalid')
        content_range=response.headers['Content-Range']
    with urllib.request.urlopen(url) as response:
        digest=hashlib.sha256()
        while chunk:=response.read(1024*1024):digest.update(chunk)
    served=digest.hexdigest()
    if served!=manifest['final_sha256']:raise RuntimeError('served MP4 differs')
    errors=[];joins=[];samples=[]
    with sync_playwright() as p:
        browser=p.chromium.launch();context=browser.new_context(viewport={'width':1000,'height':1000})
        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(f'{origin}/index.html?v={served[:12]}',wait_until='domcontentloaded')
        page.wait_for_function('document.querySelector("video").duration>1200')
        page.wait_for_function('document.querySelector("video").textTracks[0]?.cues?.length===359')
        cues=page.locator('video').evaluate('(v)=>Array.from(v.textTracks[0].cues,c=>[c.startTime,c.endTime,c.text])')
        expected=parse_srt(OUT/'S11.ru.srt')
        if len(cues)!=len(expected) or any(abs(a[0]-b[0])>.002 or abs(a[1]-b[1])>.002 or a[2]!=b[2] for a,b in zip(cues,expected)):
            raise RuntimeError('browser subtitle cue content/timing differs')
        for row in manifest['blocks']:
            label=row['block_id'];second=row['video_start_seconds']+2
            page.locator(f'button[data-seek="{row["video_start_seconds"]:.6f}"]').click()
            page.wait_for_function('(t)=>document.querySelector("video").currentTime>t+.3',arg=row['video_start_seconds'])
            seek(page,second);visible(page,label,evidence);samples.append({'label':label,'seconds':second})
        for i,join in enumerate(manifest['scene_boundaries'],1):
            t=join['seconds'];seek(page,t-.55);before=visible(page,f'join-{i:02}-before',evidence)
            page.locator('video').evaluate('(v)=>v.play()')
            page.wait_for_function('(t)=>document.querySelector("video").currentTime>=t',arg=t)
            visible(page,f'join-{i:02}-at',evidence)
            page.wait_for_function('(t)=>document.querySelector("video").currentTime>=t+.55',arg=t)
            visible(page,f'join-{i:02}-after',evidence)
            page.locator('video').evaluate('(v)=>v.pause()')
            state=page.locator('video').evaluate('(v)=>({time:v.currentTime,ready:v.readyState,error:v.error?.message||null})')
            if state['error'] or state['ready']<2:raise RuntimeError('browser decoder error at join')
            joins.append({**join,'played_before_through_after':True,'decoder_state':state})
            print(json.dumps({'browser_join_checked':i,'seconds':t}),flush=True)
        comparison=[]
        for label,t in [('beginning',3),('middle',manifest['final_duration_seconds']/2),('ending',manifest['final_duration_seconds']-.4),('after-seek',40)]:
            seek(page,t);comparison.append(visible(page,label,evidence));samples.append({'label':label,'seconds':t})
        if sum(abs(x-y) for x,y in zip(comparison[0],comparison[1]))/len(comparison[0])<3:
            raise RuntimeError('beginning/middle browser frames did not change')
        # Observe a real animated episode while the playback clock advances.
        seek(page,25);before=visible(page,'motion-before',evidence);clock=page.locator('video').evaluate('(v)=>v.currentTime')
        page.locator('video').evaluate('(v)=>v.play()')
        page.wait_for_function('(t)=>document.querySelector("video").currentTime>t+1.5',arg=clock)
        after=visible(page,'motion-after',evidence)
        if before==after:raise RuntimeError('clock advances but rendered picture frozen')
        page.locator('video').evaluate('(v)=>v.pause()')
        other=context.new_page();other.goto('about:blank');other.bring_to_front();page.wait_for_timeout(200)
        page.bring_to_front();page.wait_for_timeout(250);visible(page,'after-tab-return',evidence)
        clock=page.locator('video').evaluate('(v)=>v.currentTime');page.locator('video').evaluate('(v)=>v.play()')
        page.wait_for_function('(t)=>document.querySelector("video").currentTime>t+.4',arg=clock)
        visible(page,'playing-after-tab-return',evidence)
        page.locator('video').evaluate('(v)=>v.pause()')
        reviewed_episodes=[]
        for label,start,targets in [
            ('B03-loading-feedback',251.9,[252.53,252.60,252.70,253.3]),
            ('B10-result-scroll',755.4,[755.80,756.03,756.30,756.7]),
            ('B11-explainer-exit',877.3,[877.70,877.83,878.0,878.4])]:
            seek(page,start);page.locator('video').evaluate('(v)=>v.play()')
            for t in targets:
                page.wait_for_function('(t)=>document.querySelector("video").currentTime>=t',arg=t)
                visible(page,f'{label}-{t}',evidence)
            page.locator('video').evaluate('(v)=>v.pause()')
            reviewed_episodes.append({'label':label,'played_from':start,'visible_at':targets})
        last=expected[-1];seek(page,(last[0]+last[1])/2)
        active=page.locator('video').evaluate('(v)=>Array.from(v.textTracks[0].activeCues,c=>c.text)')
        if active!=['Спасибо за внимание.']:raise RuntimeError('last subtitle not active in browser')
        visible(page,'thanks-subtitle',evidence)
        if errors:raise RuntimeError('browser errors: '+str(errors))
        browser.close()
    result={'status':'PASS','player_url':f'{origin}/index.html?v={served[:12]}','served_sha256':served,
        'range_status':206,'content_range':content_range,'mime':'video/mp4','browser':'Chromium native video',
        'additional_transition_episodes':reviewed_episodes,'samples':samples,'played_scene_boundaries':joins,'time_advanced':True,'animated_frames_updated':True,
        'visible_after_seek':True,'visible_and_playing_after_tab_return':True,'subtitle_cues':len(cues),
        'all_browser_subtitle_text_and_times_match':True,'last_active_cue':active,'javascript_errors':errors}
    write_json(evidence/'report.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base-url',required=True);args=parser.parse_args()
    print(json.dumps(run(args.base_url),ensure_ascii=False,indent=2))
