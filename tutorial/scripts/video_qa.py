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
        arrivals=[x for x in overlay['events'] if x['type']=='cursor-arrived']
        shows=[x for x in overlay['events'] if x['type']=='cursor-show']
        sections=[x for x in events if x['type']=='section-highlight']
        actions=[x for x in events if x['type']=='action-timing']
        hides=[x for x in overlay['events'] if x['type']=='cursor-hide']
        geometry=c['geometry_checks']
        navigation=[]
        for i,event in enumerate(events):
            if event['type']!='navigation-feedback':continue
            arrival=next(x for x in reversed(events[:i]) if x['type']=='cursor-arrival')
            box=arrival['box'];x=max(0,round(box['x']+box['width']/2)-35);y=max(0,round(box['y']+box['height']/2)-35)
            def yellow_at(second):
                raw=OUT/'visuals'/f"{scene['id']}.raw.mp4"
                rgb=subprocess.check_output(['ffmpeg','-v','error','-ss',str(second),'-i',str(raw),'-frames:v','1',
                    '-vf',f'crop=70:70:{x}:{y}','-pix_fmt','rgb24','-f','rawvideo','-'])
                # H.264 4:2:0 blends the thin yellow ring into a blue button;
                # detect its yellow chroma rather than the uncompressed RGB.
                return sum(r>125 and g>110 and b<145 and min(r,g)-b>35 for r,g,b in zip(rgb[::3],rgb[1::3],rgb[2::3]))
            feedback=max(yellow_at(event['press_seconds']+offset) for offset in (.04,.07,.10))
            hidden=yellow_at(event['seconds']-.025)
            navigation.append({'feedback_yellow_pixels':feedback,'hidden_yellow_pixels':hidden,
                               'status':'PASS' if feedback>10 and hidden==0 and event['cursor_hidden_before_transition'] else 'FAIL'})
        dwell=all(x['dwell_seconds']>=.75 and (x['phrase_end_seconds'] is None or x['seconds']>=x['phrase_end_seconds']+.25) for x in actions)
        holds=[]
        for i,event in enumerate(events):
            if event['type']!='action-complete':continue
            move=next((x for x in events[i+1:] if x['type']=='move'),None)
            if move:holds.append(move['seconds']-move['actual_duration']-event['hold_until_seconds'])
        row={'scene_id':scene['id'],'cursor_present':bool(shows),'cursor_visible_at_end':overlay['cursorVisible'],
             'meaningful_targets':len(shows)+len(sections),'section_highlights':len(sections),
             'clicks':len(clicks),'actual_pointer_ripples':len(rings),
             'cursor_hides':len(hides),'hide_reasons':sorted({x['reason'] for x in hides}),
             'invalid_visible_frames':overlay['lifecycle']['invalidVisibleFrames'],
             'arrival_visibility_pass':all(x['visible'] for x in arrivals),
             'outline_audit_pass':not overlay['violations'],
             'geometry_checks':len(geometry),'geometry_max_error_px':max((x['pixels']['max_error_px'] for x in geometry),default=0),
             'dwell_pass':dwell,'minimum_action_dwell_seconds':min((x['dwell_seconds'] for x in actions),default=None),
             'post_action_hold_pass':min(holds,default=0)>=-.02,
             'visible_post_action_hold_pass':all(x['hold_until_seconds']<=meta['duration_seconds']+1/30 for x in events if x['type']=='action-complete'),
             'navigation_feedback':navigation,
             'drags':sum(x['type']=='drag-start' for x in events),'drag_ends':sum(x['type']=='drag-end' for x in events),
             'actual_move_durations':[x['actual_duration']*e['retime_factor'] for x in events if x['type'] in ('move','drag-move')],
             'cursor_points_in_view':all(0<=x['end'][0]<1920 and 0<=x['end'][1]<1080 for x in events if x['type'] in ('move','drag-move')),
             'cue_errors_seconds':[abs(x['actual_seconds']*e['retime_factor']-x['target_seconds']) for x in e['alignment_action_cues']]}
        row['status']='PASS' if (row['meaningful_targets'] and row['cursor_points_in_view'] and
            max(row['actual_move_durations'],default=0)<=.8 and row['drags']==row['drag_ends'] and len(rings)>=len(clicks) and
            not row['invalid_visible_frames'] and row['arrival_visibility_pass'] and row['outline_audit_pass'] and
            row['geometry_max_error_px']<=2 and row['dwell_pass'] and row['post_action_hold_pass'] and row['visible_post_action_hold_pass'] and
            all(x['status']=='PASS' for x in navigation) and
            max(row['cue_errors_seconds'],default=0)<=.18) else 'FAIL'
        rows.append(row)
    required={'025','036','037','038','040','042'}
    missing=[r['scene_id'] for r in rows if r['scene_id'][:3] in required and not r['drags']]
    report={'status':'PASS' if not missing and all(r['status']=='PASS' for r in rows) else 'FAIL',
            'browser_scenes':len(rows),'cursor_coverage':sum(r['cursor_present'] for r in rows),
            'semantic_target_coverage':sum(r['meaningful_targets']>0 for r in rows),
            'section_only_scenes':[r['scene_id'] for r in rows if not r['cursor_present']],
            'clicks':sum(r['clicks'] for r in rows),'actual_pointer_ripples':sum(r['actual_pointer_ripples'] for r in rows),
            'focus_coverage':sum(r['section_highlights']>0 for r in rows),
            'cursor_hides':sum(r['cursor_hides'] for r in rows),'invalid_visible_frames':sum(r['invalid_visible_frames'] for r in rows),
            'geometry_checks':sum(r['geometry_checks'] for r in rows),'geometry_max_error_px':max(r['geometry_max_error_px'] for r in rows),
            'navigation_feedback_checks':sum(len(r['navigation_feedback']) for r in rows),
            'max_actual_cursor_move_seconds':max([x for r in rows for x in r['actual_move_durations']],default=0),'missing_drag_scenes':missing,
            'max_cue_error_seconds':max([x for r in rows for x in r['cue_errors_seconds']],default=0),'scenes':rows}
    write_json(OUT/'video-qa/capture-coverage.json',report)
    if report['status']!='PASS':raise RuntimeError('Capture coverage FAIL; see video-qa/capture-coverage.json')
    return report


if __name__=='__main__':
    from modules import ROOT
    print(json.dumps(check_video(json.loads((OUT/'manifest.json').read_text())),ensure_ascii=False)[:500])
    print(json.dumps(capture_coverage(json.loads((ROOT/'tutorial.yaml').read_text())),ensure_ascii=False)[:500])
