#!/usr/bin/env python3
"""Review only the six v2 clips, synchronized with unchanged original module MP3s."""
import argparse,hashlib,json
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse
from corrective_pilot import OUT,ALLOWED,LEAD,preservation
from modules import scene_timing
from serve_pilot import Handler
from validate import ROOT


def build():
    spec=json.loads((ROOT/'tutorial.yaml').read_text());rows=[]
    for scene in spec['scenes']:
        if int(scene['id'][:3]) not in ALLOWED:continue
        meta=json.loads((OUT/'scenes'/f"{scene['id']}.json").read_text())
        timing=scene_timing(spec,scene)
        rows.append({'id':scene['id'],'text':scene['narration'],'duration':meta['duration_seconds'],
                     'module':timing['module_id'],'audio_start':timing['range_start_seconds'],
                     'spoken_duration':timing['duration_seconds'],'lead':LEAD,
                     'cues':meta['alignment_action_cues'],'geometry':meta['choreography']['geometry_checks']})
    (OUT/'review.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    (OUT/'index.html').write_text(HTML)
    return preservation()


HTML='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>S11 · Visual corrective v2 · 6 scenes</title>
<style>*{box-sizing:border-box}body{margin:0;background:#101a25;color:#e9f1f6;font:16px system-ui,sans-serif}main{max-width:1320px;margin:auto;padding:24px}h1{font-size:24px;margin:0 0 8px}p{line-height:1.55}.muted{color:#a9bfce}nav,.controls,.cues{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}button,a{font:inherit}button{color:inherit;background:#243a4c;border:1px solid #577487;border-radius:7px;padding:10px 16px;cursor:pointer}button[aria-current=true]{background:#076783;border-color:#65d7ed}button:focus-visible,a:focus-visible,input:focus-visible{outline:3px solid #6fe4ff;outline-offset:3px}video{width:100%;display:block;background:#000;max-height:72vh}input[type=range]{flex:1;min-width:180px}a{color:#8fe0f4}.panel{background:#192a38;padding:18px;border-radius:8px;margin:16px 0}.controls{align-items:center}#canonical{white-space:pre-line}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:8px;border-bottom:1px solid #3a5163}details{margin:14px 0}summary{cursor:pointer}.before{width:100%}#error{color:#ffb8ad}</style>
<main><h1>S11 · Visual corrective v2</h1><p class="muted">Только 015, 016, 029, 032, 050 и 059. Новый full candidate не собран. Озвучка воспроизводится из исходных N01–N08; видео не содержит перекодированного аудио.</p><nav aria-label="Сцены" id="scenes"></nav><h2 id="title"></h2>
<video id="visual" muted playsinline preload="metadata" aria-label="Запись реального интерфейса Meser"></video><audio id="narration" preload="auto"></audio>
<div class="controls"><button id="play">Play</button><button id="restart">С начала</button><input id="seek" type="range" min="0" step="0.01" value="0" aria-label="Позиция просмотра"><output id="clock"></output><button id="fullscreen">На весь экран</button></div><p id="error" role="alert"></p><p id="info" class="muted"></p>
<div class="panel"><strong>Alignment cues</strong><div id="cues" class="cues"></div><details><summary>Arrival / phrase end / section geometry</summary><div id="checks"></div></details></div>
<details class="panel"><summary>Canonical narration — без изменений</summary><p id="canonical"></p></details><details id="before" class="panel" hidden><summary>Дефект в предыдущем full candidate</summary><p id="beforeCaption"></p><img id="beforeImage" class="before" alt="Кадр предыдущего candidate с дефектом подсветки"></details>
<p><a href="evidence/geometry-regression.json">Geometry regression</a> · <a href="evidence/preservation.json">Audio/content preservation</a> · <a href="evidence/pilot-validation.json">Pilot validation</a></p><p class="muted">Перед озвучкой — 1,2 с для подхода курсора. Arrival привязан к началу фразы. Click: минимум 0,75 с dwell и не ранее phrase end + 0,25 с. После действия — hold 0,45 с. Approval этого pilot требуется до дальнейших recaptures.</p></main>
<script>
const $=id=>document.getElementById(id),v=$('visual'),a=$('narration');let rows=[],row,playing=false,changing=false,pendingAudio=false;
const fmt=x=>Math.floor(x/60)+':'+(x%60).toFixed(2).padStart(5,'0');
function pause(){playing=false;v.pause();a.pause();$('play').textContent='Play'}
function audioPosition(){return row.audio_start+Math.max(0,Math.min(row.spoken_duration,v.currentTime-row.lead))}
function sync(){
 if(!row||changing)return;
 $('seek').value=v.currentTime;$('clock').textContent=fmt(v.currentTime)+' / '+fmt(row.duration);
 const audible=playing&&v.currentTime>=row.lead&&v.currentTime<row.lead+row.spoken_duration&&!v.paused;
 if(!audible){if(!a.paused)a.pause();return}
 if(a.readyState<2)return;
 const desired=audioPosition();if(Math.abs(a.currentTime-desired)>.09)a.currentTime=desired;
 if(a.paused&&!pendingAudio){pendingAudio=true;a.play().catch(e=>{$('error').textContent=e.message;pause()}).finally(()=>pendingAudio=false)}
}
function tick(){sync();requestAnimationFrame(tick)}requestAnimationFrame(tick);
function seek(value){v.currentTime=Math.max(0,Math.min(row.duration,value));a.currentTime=audioPosition();sync()}
async function select(index){pause();changing=true;row=rows[index];$('error').textContent='';
 v.src='scenes/'+row.id+'.mp4';a.src='narration/'+row.module+'.mp3';a.currentTime=row.audio_start;v.currentTime=0;
 $('title').textContent=row.id;$('seek').max=row.duration;$('seek').value=0;$('canonical').textContent=row.text;
 $('info').textContent='Visual '+fmt(row.duration)+' · Narration '+fmt(row.spoken_duration)+' · '+row.module+' ['+fmt(row.audio_start)+'–'+fmt(row.audio_start+row.spoken_duration)+'] · 0 TTS · unchanged MP3';
 document.querySelectorAll('#scenes button').forEach((b,i)=>b.setAttribute('aria-current',i===index));
 $('cues').replaceChildren();for(const cue of row.cues){const b=document.createElement('button');b.textContent=cue.phrase;b.onclick=()=>seek(Math.max(0,cue.target_seconds-1));$('cues').append(b)}
 const table=document.createElement('table');table.innerHTML='<tr><th>Phrase</th><th>Type</th><th>Alignment</th><th>Actual</th></tr>';
 for(const c of row.cues){const tr=document.createElement('tr');for(const x of [c.phrase,c.kind,fmt(c.target_seconds),fmt(c.actual_seconds)]){const td=document.createElement('td');td.textContent=x;tr.append(td)}table.append(tr)}
 $('checks').replaceChildren(table);const p=document.createElement('p');p.textContent='Pixel geometry: '+row.geometry.map(g=>g.pixels.max_error_px.toFixed(2)+' px').join(', ')+' (tolerance ≤ 2 px)';$('checks').append(p);
 const old={'015':'04:24 — outline на footer','016':'04:40 — displaced outline в file selection','029':'08:10.35 — save dialog и stale underlying outline'}[row.id.slice(0,3)];
 $('before').hidden=!old;if(old){$('beforeCaption').textContent=old;$('beforeImage').src='evidence/before-'+row.id.slice(0,3)+'.png'}
 history.replaceState(null,'','#'+row.id);changing=false;sync();
}
$('play').onclick=async()=>{if(playing)return pause();if(v.ended)seek(0);playing=true;$('play').textContent='Pause';try{await v.play();sync()}catch(e){$('error').textContent=e.message;pause()}};
$('restart').onclick=()=>seek(0);$('seek').oninput=e=>seek(+e.target.value);$('fullscreen').onclick=()=>v.requestFullscreen();v.onended=pause;v.onwaiting=()=>a.pause();document.addEventListener('visibilitychange',()=>{if(document.hidden)pause()});
fetch('review.json').then(r=>r.json()).then(data=>{rows=data;data.forEach((s,i)=>{const b=document.createElement('button');b.textContent=s.id.slice(0,3);b.onclick=()=>select(i);$('scenes').append(b)});select(Math.max(0,rows.findIndex(r=>'#'+r.id===location.hash)))}).catch(e=>$('error').textContent=e.message);
</script></html>'''

class ReviewHandler(Handler):
    def translate_path(self,path):
        route=urlparse(path).path.lstrip('/')
        if route.startswith('narration/'):
            module=route.removeprefix('narration/').removesuffix('.mp3')
            if module in ('N02','N04','N05','N07','N08') and route.endswith('.mp3'):
                return str(ROOT/'generated/narration-modules'/module/'narration.mp3')
        path=(OUT/(route or 'index.html')).resolve()
        if not path.is_relative_to(OUT.resolve()):return str(OUT/'__not_found__')
        return str(path)
    def log_message(self,fmt,*args):pass

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--serve',action='store_true');parser.add_argument('--port',type=int,default=4197);args=parser.parse_args()
    print(build(),flush=True)
    if args.serve:
        server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(ReviewHandler,directory=str(ROOT/'generated')))
        print(f'Review: http://127.0.0.1:{args.port}/index.html',flush=True);server.serve_forever()
