"""Offline failures for rendered geometry and alignment-driven pointer scheduling."""
import asyncio,unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from capture_geometry import rendered_outline
from capture_director import Director

class GeometryTests(unittest.TestCase):
    def image(self,shift=0):
        data=bytearray([255]*100*80*3)
        for y in range(14,56):
            for x in range(14+shift,66+shift):
                if y<17 or y>=53 or x<17+shift or x>=63+shift:
                    data[(y*100+x)*3:(y*100+x)*3+3]=bytes([25,188,230])
        return b'P6\n100 80\n255\n'+data
    def test_pixels_match_actual_target(self):
        result=rendered_outline(self.image(),100,80,{'x':20,'y':20,'width':40,'height':30})
        self.assertEqual(result['max_error_px'],0)
    def test_displaced_rectangle_fails(self):
        with self.assertRaisesRegex(RuntimeError,'geometry regression'):
            rendered_outline(self.image(6),100,80,{'x':20,'y':20,'width':40,'height':30})

class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_arrival_dwell_phrase_end_and_post_action_hold(self):
        loop=asyncio.get_running_loop();calls=[]
        async def move(x,y):calls.append(loop.time())
        locator=SimpleNamespace(scroll_into_view_if_needed=AsyncMock(),bounding_box=AsyncMock(return_value={'x':290,'y':190,'width':20,'height':20}),evaluate=AsyncMock())
        page=SimpleNamespace(mouse=SimpleNamespace(move=move),evaluate=AsyncMock())
        scene={'narration':'Save'}
        timing={'alignment':{'character_start_times_seconds':[.1,.2,.3,.4],
                             'character_end_times_seconds':[.2,.3,.4,1.2]},'visual_lead_seconds':.5,'strict_choreography':True}
        d=Director(page,scene,timing,loop.time())
        with patch('capture_director.audit',new=AsyncMock()):
            await d.cue('Save');await d.aim(locator)
            cue=d.cues[0]
            self.assertLess(cue['movement_start_seconds'],cue['target_seconds'])
            self.assertLess(abs(cue['actual_seconds']-cue['target_seconds']),.18)
            self.assertEqual(locator.evaluate.call_args.args[0],'el=>window.__s11Capture.aim(el)')
            await d.before_action()
            event=d.events[-1]
            self.assertGreaterEqual(event['dwell_seconds'],.75)
            self.assertGreaterEqual(event['seconds'],event['phrase_end_seconds']+.25)
            action_end=d.now();await d.after_action();await d.aim(locator)
            self.assertGreaterEqual(d.events[-2]['seconds']-d.events[-2]['actual_duration'],action_end+.44)
        with self.assertRaisesRegex(RuntimeError,'cursor-only'):
            await d.aim(locator,kind='section')

if __name__=='__main__':unittest.main()
