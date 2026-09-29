"""Offline contract tests: paid calls mocked, real MP3 decode and PCM assembly."""
import array,base64,copy,io,json,subprocess,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch
import modules
import module_assemble as assembly
import module_visuals
from validate import ROOT


class ModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=json.loads((ROOT/'tutorial.yaml').read_text())
        cls.audio=subprocess.check_output(['ffmpeg','-v','error','-f','lavfi','-i','anullsrc=r=44100:cl=mono','-t','2','-f','mp3','-'])

    def response(self,spec,module):
        text=modules.request_body(spec,module)['text']; n=len(text)
        alignment={'characters':list(text),'character_start_times_seconds':[i/n for i in range(n)],
                   'character_end_times_seconds':[(i+1)/n for i in range(n)]}
        response=io.BytesIO(json.dumps({'audio_base64':base64.b64encode(self.audio).decode(),'alignment':alignment}).encode())
        response.headers={'request-id':'offline-test'};response.status=200
        return response

    def test_cold_hit_selective_and_pcm(self):
        spec=copy.deepcopy(self.spec)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'cache';out=Path(temp)/'candidate';out.mkdir()
            with patch('modules.api_key',return_value='not-a-real-key'),patch('modules.urllib.request.urlopen') as request:
                for module in spec['narration_modules']:
                    request.return_value=self.response(spec,module)
                    hit,state=modules.generate(spec,module,root=root)
                    self.assertEqual(state,'MISS')
                self.assertEqual(request.call_count,8)
                for module in spec['narration_modules']:
                    self.assertEqual(modules.generate(spec,module,root=root)[1],'HIT')
                self.assertEqual(request.call_count,8)
                before={p:modules.sha(p) for p in root.rglob('*') if p.is_file()}
                n03=spec['narration_modules'][2]
                request.return_value=self.response(spec,n03)
                self.assertEqual(modules.generate(spec,n03,force=True,root=root)[1],'MISS')
                self.assertEqual(request.call_count,9)
                self.assertTrue(all(modules.sha(p)==digest for p,digest in before.items() if 'N03' not in p.parts and p.name!='requests.jsonl'))
                plan=modules.plan(spec,[n03],force=True,root=root)
                self.assertEqual(plan['tts_requests'],1)
                self.assertEqual([r['module_id'] for r in plan['modules'] if r['tts_requests']],['N03'])
                self.assertEqual(len((root/'requests.jsonl').read_text().splitlines()),9)
            local_cache=lambda s,m:modules.cached(s,m,root)
            local_timing=lambda s,scene:modules.scene_timing(s,scene,root)
            with patch.object(assembly,'OUT',out),patch.object(assembly,'cached',local_cache),patch.object(assembly,'scene_timing',local_timing):
                timeline=assembly.pcm_timeline(spec)
                rows,count=assembly.subtitles(spec,timeline)
                assembly.review(spec,{'timeline':timeline,'scenes':rows})
            with wave.open(str(out/'audio/master.wav')) as wav:
                self.assertEqual(wav.getnframes(),timeline['frames'])
                self.assertEqual((wav.getnchannels(),wav.getframerate()),(1,48000))
                for boundary in timeline['boundaries']:
                    wav.setpos(round(boundary['seconds']*48000))
                    self.assertEqual(wav.readframes(16800),bytes(33600))
            self.assertEqual(len(rows),60);self.assertGreater(count,133)
            self.assertEqual(timeline['aac_encodes'],0)
            self.assertNotIn('[calm]',(out/'tutorial.ru.srt').read_text())
            self.assertEqual((out/'index.html').read_text().count(' → '),7)
            # Tampered evidence fails closed without any paid recovery request.
            (root/'N03/timing.json').write_text('{}')
            self.assertIsNone(modules.cached(spec,n03,root))

    def test_hash_scope_all_settings_and_pronunciation(self):
        spec=copy.deepcopy(self.spec);before=[modules.narration_hash(spec,m) for m in spec['narration_modules']]
        spec['narration_modules'][2]['pronunciation_dictionary_locators']=[{'pronunciation_dictionary_id':'example','version_id':'v2'}]
        after=[modules.narration_hash(spec,m) for m in spec['narration_modules']]
        self.assertEqual([i for i,(a,b) in enumerate(zip(before,after)) if a!=b],[2])
        for key,value in [('voice_id','other'),('model_id','other'),('language_code','en'),('output_format','other'),('voice_settings',{'stability':1}),('delivery_prefix','[calm]')]:
            changed=copy.deepcopy(self.spec);changed['narration'][key]=value
            self.assertNotEqual(modules.narration_hash(changed,changed['narration_modules'][0]),before[0])
        changed=copy.deepcopy(self.spec);changed['scenes'][19]['narration']+=' '
        self.assertEqual([i for i,m in enumerate(changed['narration_modules']) if modules.narration_hash(changed,m)!=before[i]],[2])

    def test_alignment_and_visual_invalidation(self):
        module=self.spec['narration_modules'][2]
        a=json.loads(self.response(self.spec,module).getvalue())['alignment']
        timing=modules.map_timing(self.spec,module,a,2)
        self.assertEqual(len(timing['scenes']),4)
        self.assertEqual(timing['scenes'][0]['range_start_seconds'],0)
        self.assertEqual(timing['scenes'][-1]['range_end_seconds'],2)
        text=modules.spoken_text(self.spec,module)
        for row in timing['scenes']:
            self.assertEqual(text[row['canonical_start_offset']:row['canonical_end_offset']],next(s['narration'] for s in self.spec['scenes'] if s['id']==row['scene_id']))
        broken=copy.deepcopy(a);broken['characters'][0]='x'
        with self.assertRaises(RuntimeError):modules.map_timing(self.spec,module,broken,2)
        scene=self.spec['scenes'][19]
        self.assertNotEqual(module_visuals.visual_hash(self.spec,scene,{'timing_identity':'take1'}),module_visuals.visual_hash(self.spec,scene,{'timing_identity':'take2'}))
        self.assertEqual(module_visuals.phase_at(2,[{'seconds':2,'phase':.4}],10),.4)

    def test_selection_and_exact_request(self):
        self.assertEqual([m['id'] for m in modules.selection(self.spec,scene_id='020-one-translator')],['N03'])
        for module in self.spec['narration_modules']:
            request=modules.request_body(self.spec,module)
            self.assertEqual(request['text'],'[calm] [conversational]\n'+'\n\n'.join(s['narration'] for s in modules.members(self.spec,module)))
            self.assertEqual(request['voice_settings'],{'stability':.5})
            self.assertEqual(set(request),{'text','model_id','language_code','voice_settings'})

    def test_asr_missing_opening_words_fails_boundary_check(self):
        from module_audio_qa import speech_checks
        rows=[{'module_id':f'N{i:02}','window':w,'expected_boundary_phrase':'В Аудиоархиве можно работать.',
               'transcript':'В Аудиоархиве можно работать.'} for i in range(1,9) for w in ('opening','ending')]
        self.assertEqual(speech_checks({'windows':rows})['status'],'PASS')
        rows[-2]['transcript']='Можно работать.'
        self.assertEqual(speech_checks({'windows':rows})['status'],'REVIEW')

    def test_nonzero_source_tail_has_no_step_and_speech_is_unchanged(self):
        source=array.array('h',[1000,-2000,12000]);original=source.tobytes()
        result=source+assembly.boundary_padding(source[-1],2400,48000)
        self.assertEqual(result[:len(source)].tobytes(),original)
        self.assertLess(max(abs(result[i]-result[i-1]) for i in range(len(source),len(result))),.02*32768)
        self.assertFalse(any(result[len(source)+240:]))
        self.assertGreater(abs(source[-1]),.02*32768)  # Old zero padding had a real discontinuity.

    def test_capture_clock_jump_cannot_pass_after_video_retiming(self):
        evidence={'retime_factor':1,'alignment_action_cues':[{'target_seconds':5.44,'actual_seconds':5.440768}]}
        assembly.browser_action_errors('049-final-download-save',evidence)
        # Observed interrupted capture: action happened on time, but video was compressed 67x.
        evidence['retime_factor']=.015000659
        with self.assertRaisesRegex(AssertionError,'browser action timing drift'):
            assembly.browser_action_errors('049-final-download-save',evidence)

if __name__=='__main__':unittest.main()
