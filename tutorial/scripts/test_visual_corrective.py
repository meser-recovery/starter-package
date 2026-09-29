"""Regression gates for the corrective master and capture layer."""
import unittest,json,subprocess,tempfile
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


if __name__=='__main__':unittest.main()
