"""Offline final assembly regression checks; no provider or large binary cache."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from audio_approval import approval_records, checked_file
from final_assemble import CURRENT, make_timeline, pcm, QUIET
from validate import ROOT


class FinalAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.spec=json.loads((ROOT/'tutorial.yaml').read_text())

    def test_all_fourteen_current_approvals_and_latest_reopened_versions(self):
        for bid,digest in CURRENT.items():
            records=approval_records(self.spec,bid)
            self.assertEqual(records['block']['video_sha256'],digest)
            self.assertEqual(records['block']['approved_alignment_sha256'],records['audio']['approved_take']['alignment_sha256'])

    def test_changed_audio_record_and_canonical_text_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            for name in ('B02-audio.json','B02-block.json'):
                (directory/name).write_bytes((ROOT/'approvals'/name).read_bytes())
            (directory/'B02-audio.json').write_text((directory/'B02-audio.json').read_text()+'\n')
            with self.assertRaisesRegex(RuntimeError,'record changed'):
                approval_records(self.spec,'B02',directory)
        spec=copy.deepcopy(self.spec);spec['narration_modules'][1]['narration']+=' changed'
        with self.assertRaisesRegex(RuntimeError,'canonical narration'):
            approval_records(spec,'B02')

    def test_transition_review_cannot_ignore_new_or_uncovered_findings(self):
        from final_verify import review_is_valid
        m={'final_sha256':'final','blocks':[{'block_id':'B03','video_source_sha256':'source'}]}
        findings=[{'start_frame':12}]
        r={'video_sha256':'final','candidates':findings,'reviews':[{'candidate_indices':[0],
           'decision':'EXPECTED_APPROVED_ACTION','block_id':'B03','source_sha256':'source'}]}
        self.assertTrue(review_is_valid(m,findings,r))
        self.assertFalse(review_is_valid(m,findings+[{'start_frame':44}],r))
        r['reviews']=[]
        self.assertFalse(review_is_valid(m,findings,r))

    def test_binary_digest_remains_mandatory(self):
        (ROOT/'generated').mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=ROOT/'generated') as source:
            source.write(b'fixture');source.flush()
            with self.assertRaisesRegex(RuntimeError,'artifact changed'):
                checked_file(str(Path(source.name).relative_to(ROOT)),'0'*64)

    def test_pause_counts_existing_quiet_and_preserves_every_source_sample(self):
        import array
        sources={'one':array.array('h',[123]*44100+[0]*441).tobytes(),
                 'two':array.array('h',[0]*2205+[222]*44100).tobytes()}
        manifest={'blocks':[{'block_id':bid,'wav_source':name,'video_source_frames':50 if bid=='B01' else 55} for bid,name in [('B01','one'),('B02','two')]]}
        with tempfile.TemporaryDirectory() as folder,patch('final_assemble.OUT',Path(folder)),patch('final_assemble.pcm',side_effect=lambda p:sources[p.name]):
            timeline=make_timeline(manifest)
            data=pcm(Path(folder)/'S11-master.wav')
            for row in manifest['blocks']:
                expected=sources[row['wav_source']];start=2*row['pcm_start_sample']
                self.assertEqual(data[start:start+len(expected)],expected)
            gap=timeline['boundaries'][0];samples=array.array('h');samples.frombytes(data)
            quiet=samples[gap['last_signal_sample']+1:gap['first_signal_sample']]
            self.assertEqual(len(quiet),35280)
            self.assertTrue(all(abs(x)<=QUIET for x in quiet))
            self.assertLess(gap['added_zero_samples'],35280)


if __name__=='__main__':unittest.main()
