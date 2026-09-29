"""Regression gates for the corrective master and capture layer."""
import unittest,json,subprocess,tempfile,asyncio
from types import SimpleNamespace
from capture_director import Director
from module_visuals import browser_timeline_factor
from pathlib import Path
from browser_capture import frame_listing
from video_qa import inspect_frames


class VideoBoundaryTests(unittest.TestCase):
    def test_cdp_irregular_frame_timestamps_are_not_quantized_to_25fps(self):
        with tempfile.TemporaryDirectory() as folder:
            image=Path(folder)/'frame.ppm';image.write_bytes(b'P6\n2 2\n255\n'+bytes([40,100,180])*4)
            times=[2.,2.015,2.049,2.065]
            listing=Path(folder)/'frames.ffconcat';listing.write_text(frame_listing([image]*4,times))
            raw=subprocess.check_output(['ffprobe','-v','error','-safe','0','-f','concat','-i',str(listing),'-show_packets','-of','json'])
            pts=[float(p['pts_time']) for p in json.loads(raw)['packets']]
            for actual,expected in zip(pts,times):self.assertAlmostEqual(actual,expected-times[0],places=5)

    def test_extra_idle_tail_never_speeds_up_aligned_actions(self):
        evidence={'duration_seconds':9.2,'choreography':{'events':[{'seconds':8.025}]}}
        factor=browser_timeline_factor(8.4,evidence)
        self.assertLess(abs(5.761*factor-5.733),.03)
        evidence['choreography']['events'][0]['seconds']=9.0
        with self.assertRaisesRegex(RuntimeError,'exceeds'):
            browser_timeline_factor(8.4,evidence)

    def test_normal_hard_cut_is_allowed(self):
        a=bytes([35,70,110,180]*100);b=bytes([210,150,90,40]*100)
        self.assertEqual(inspect_frames([a]*4+[b]*5)['status'],'PASS')

    def test_black_white_and_initialization_flash_fail(self):
        a=bytes([45,90,130,180]*100);b=bytes([65,95,150,195]*100)
        for bad in (bytes(400),bytes([255])*400,bytes([230,20,240,15]*100)):
            with self.subTest(frame=bad[:4]):
                self.assertEqual(inspect_frames([a,a,bad,b,b])['status'],'FAIL')

    def test_smooth_small_motion_is_allowed(self):
        frames=[bytes([40+i,90+i,140+i,190+i]*100) for i in range(9)]
        self.assertEqual(inspect_frames(frames)['status'],'PASS')


class PointerCadenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_modal_acknowledgements_do_not_stretch_movement(self):
        sent=[];loop=asyncio.get_running_loop()
        async def move(x,y):
            sent.append((loop.time(),x,y));await asyncio.sleep(.12)
        director=Director(SimpleNamespace(mouse=SimpleNamespace(move=move)),{},None,loop.time())
        await director.move(600,400,duration=.3)
        self.assertEqual(len(sent),8)
        self.assertLess(sent[-1][0]-sent[0][0],.4)
        self.assertLess(director.events[-1]['actual_duration'],.65)
        self.assertTrue(all(b[1]>a[1] for a,b in zip(sent,sent[1:])))


if __name__=='__main__':unittest.main()
