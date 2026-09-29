"""Decoded final-frame seam checks; normal hard cuts are explicitly permitted."""
import json,math,struct,subprocess,zlib
from pathlib import Path
from modules import write_json
from module_visuals import OUT


def frame_stats(frame):
    n=len(frame);mean=sum(frame)/n
    deviation=math.sqrt(sum((v-mean)**2 for v in frame)/n)
    return {'mean':mean,'stddev':deviation,'black':sum(v<8 for v in frame)/n>.995,
            'white':sum(v>247 for v in frame)/n>.995}


def difference(a,b):return sum(abs(x-y) for x,y in zip(a,b))/len(a)


def inspect_frames(frames):
    stats=[frame_stats(f) for f in frames];issues=[]
    for i,s in enumerate(stats):
        if s['black'] or s['white']:issues.append({'frame':i,'reason':'black' if s['black'] else 'white'})
    for i in range(1,len(frames)-1):
        left=difference(frames[i-1],frames[i]);right=difference(frames[i],frames[i+1]);stable=difference(frames[i-1],frames[i+1])
        # A,A,B,B is valid. A,X,A and a large excursion A,X,B fail.
        if min(left,right)>max(14,stable*1.2+5):
            issues.append({'frame':i,'reason':'isolated-outlier','left_mae':left,'right_mae':right,'neighbors_mae':stable})
    return {'status':'FAIL' if issues else 'PASS','issues':issues,'frame_stats':stats}


def png_gray(path,frames,width,height):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    # Nine decoded samples in one strip; no generated/interpolated frames.
    scan=b''.join(b'\0'+b''.join(f[y*width:(y+1)*width] for f in frames) for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width*len(frames),height,8,0,0,0,0))+chunk(b'IDAT',zlib.compress(scan))+chunk(b'IEND',b''))


def check_video(manifest):
    folder=OUT/'video-qa';folder.mkdir(exist_ok=True)
    # Four frames before, transition frame, four after, all from the final H.264 decode.
    boundaries=[];cursor=0
    for previous,current in zip(manifest['scenes'],manifest['scenes'][1:]):
        cursor+=previous['video_frames'];boundaries.append({'from':previous['scene_id'],'to':current['scene_id'],
            'frame':cursor,'seconds':cursor/30,'review_start_seconds':max(0,cursor/30-2),'samples':list(range(cursor-4,cursor+5))})
    indices=sorted({n for b in boundaries for n in b['samples']});expression='+'.join(f'eq(n,{n})' for n in indices)
    command=['ffmpeg','-v','error','-i',manifest['final'],'-an','-vf',f"select='{expression}',scale=160:90,format=gray",'-fps_mode','passthrough','-f','rawvideo','-']
    raw=subprocess.check_output(command);size=160*90
    if len(raw)!=len(indices)*size:raise RuntimeError('boundary frame coverage mismatch')
    decoded={index:raw[i*size:(i+1)*size] for i,index in enumerate(indices)}
    for i,b in enumerate(boundaries):
        frames=[decoded[n] for n in b['samples']];b.update(inspect_frames(frames))
        b['contact_sheet']=f'video-qa/{i+1:02d}.png';png_gray(OUT/b['contact_sheet'],frames,160,90)
    report={'status':'PASS' if all(b['status']=='PASS' for b in boundaries) else 'FAIL',
            'final_sha256':manifest['final_sha256'],
            'boundaries_checked':len(boundaries),'frames_per_boundary':9,'decoded_samples':len(indices),
            'first_five_minutes_checked':sum(b['seconds']<=300 for b in boundaries),
            'black_frames':sum(x['reason']=='black' for b in boundaries for x in b['issues']),
            'white_frames':sum(x['reason']=='white' for b in boundaries for x in b['issues']),
            'isolated_outliers':sum(x['reason']=='isolated-outlier' for b in boundaries for x in b['issues']),
            'hard_cuts_allowed':True,'method':'Final decode; frames −4…+4; 99.5% near-black/white; adjacent MAE excursion detector',
            'limitations':'Automated checks detect obvious flashes; semantic continuity and visual comfort require human review.',
            'boundaries':boundaries}
    write_json(folder/'boundaries.json',report)
    if report['status']!='PASS':raise RuntimeError('Video boundary QA FAIL; see video-qa/boundaries.json')
    return report


def capture_coverage(spec):
    rows=[]
    for scene in spec['scenes']:
        if scene['visual']['type']!='browser':continue
        meta=json.loads((OUT/'visuals'/f"{scene['id']}.json").read_text());e=meta['browser_evidence'];c=e['choreography'];events=c['events'];overlay=c['overlay']
        clicks=[x for x in events if x['type']=='click'];rings=[x for x in overlay['events'] if x['type']=='pointerdown' and x.get('ring')]
        row={'scene_id':scene['id'],'cursor_present':overlay['cursorVisible'],
             'clicks':len(clicks),'actual_pointer_ripples':len(rings),
             'focus_events':sum(x['type']=='focus' for x in events),'focus_kinds':sorted({x['kind'] for x in events if x['type']=='focus'}),
             'drags':sum(x['type']=='drag-start' for x in events),'drag_ends':sum(x['type']=='drag-end' for x in events),
             'moves':sum(x['type']=='move' for x in events),'move_durations':sorted({x['duration'] for x in events if x['type'] in ('move','drag-move')}),
             'cue_errors_seconds':[abs(x['actual_seconds']*e['retime_factor']-x['target_seconds']) for x in e['alignment_action_cues']]}
        row['status']='PASS' if row['cursor_present'] and row['focus_events'] and row['drags']==row['drag_ends'] and len(rings)>=len(clicks) else 'FAIL'
        rows.append(row)
    required={'025','036','037','038','040','042'}
    missing=[r['scene_id'] for r in rows if r['scene_id'][:3] in required and not r['drags']]
    report={'status':'PASS' if not missing and all(r['status']=='PASS' for r in rows) else 'FAIL',
            'browser_scenes':len(rows),'cursor_coverage':sum(r['cursor_present'] for r in rows),
            'clicks':sum(r['clicks'] for r in rows),'actual_pointer_ripples':sum(r['actual_pointer_ripples'] for r in rows),
            'focus_coverage':sum(r['focus_events']>0 for r in rows),'missing_drag_scenes':missing,
            'max_cue_error_seconds':max([x for r in rows for x in r['cue_errors_seconds']],default=0),'scenes':rows}
    write_json(OUT/'video-qa/capture-coverage.json',report)
    if report['status']!='PASS':raise RuntimeError('Capture coverage FAIL; see video-qa/capture-coverage.json')
    return report


if __name__=='__main__':
    from modules import ROOT
    print(json.dumps(check_video(json.loads((OUT/'manifest.json').read_text())),ensure_ascii=False)[:500])
    print(json.dumps(capture_coverage(json.loads((ROOT/'tutorial.yaml').read_text())),ensure_ascii=False)[:500])
