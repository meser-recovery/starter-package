"""Local review controls for scenes, real UI captures and decoded boundaries."""
import html,json
from pathlib import Path
from module_visuals import OUT


def review(spec,manifest):
    modules=manifest['timeline']['modules'];boundaries=manifest['timeline']['boundaries']
    def button(second,label):return f'<button data-seek="{second}">{html.escape(label)}</button>'
    module_buttons=''.join(button(m['start_seconds'],f"{m['module_id']} · {m['duration_seconds']:.2f} с") for m in modules)
    audio_buttons=''.join(button(b['review_start_seconds'],f"{b['from']} → {b['to']} · −5 с") for b in boundaries)
    types={s['id']:s['visual']['type'] for s in spec['scenes']}
    rows=[];browser=[];transitions=[];frame=0
    for i,s in enumerate(manifest['scenes']):
        sid=s['scene_id'];start=s['start_seconds']
        rows.append(f'<tr id="{sid}"><td><a href="?scene={sid}">{sid}</a>{button(start,"Смотреть")}</td><td>{s["module_id"]}<br>{types[sid]}<br>{start:.3f} с</td><td>{html.escape(s["canonical_text"])}</td></tr>')
        if types[sid]=='browser':browser.append(button(start,sid))
        if i:
            previous=manifest['scenes'][i-1]['scene_id'][:3]
            transitions.append(f'<article>{button(max(0,frame/30-2),f"{previous} / {sid[:3]} · −2 с")}<img loading="lazy" src="video-qa/{i:02d}.png" alt="Девять декодированных кадров вокруг перехода {i}"></article>')
        frame+=s.get('video_frames',round((s['end_seconds']-start)*30))
    data=json.dumps([{'id':s['scene_id'],'seconds':s['start_seconds']} for s in manifest['scenes']],ensure_ascii=False)
    template=(Path(__file__).with_suffix('.html.in')).read_text()
    for key,value in {'MODULES':module_buttons,'AUDIO':audio_buttons,'BROWSER':''.join(browser),'ROWS':''.join(rows),'TRANSITIONS':''.join(transitions),'SCENES':data,'PROFILE':html.escape(json.dumps(spec['narration'],ensure_ascii=False,indent=2))}.items():template=template.replace('{{'+key+'}}',value)
    (OUT/'index.html').write_text(template)
