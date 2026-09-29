"""Capture-only pointer/focus choreography around real Playwright controls."""
import asyncio,math
from capture_geometry import audit


class Director:
    def __init__(self,page,scene,timing,started):
        self.page=page;self.scene=scene;self.timing=timing;self.started=started
        self.pending=None;self.arrival=None;self.post_until=0;self.geometry=[];self.events=[];self.cues=[];self.ready=True;self.point=(150,180);self.down=False;self.file_picker_id=None;self.overlay_pages=[]
    def now(self):return asyncio.get_running_loop().time()-self.started
    async def cue(self,phrase):
        index=self.scene['narration'].find(phrase)
        if index<0:raise RuntimeError('unknown capture cue: '+phrase)
        lead=self.timing.get('visual_lead_seconds',0)
        self.pending=(phrase,lead+self.timing['alignment']['character_start_times_seconds'][index],lead+self.timing['alignment']['character_end_times_seconds'][index+len(phrase)-1])
    async def move(self,x,y,*,duration=None):
        a,b=self.point;duration=duration or min(.7,max(.3,math.hypot(x-a,y-b)/1800))
        count=max(8,round(duration*20));start=asyncio.get_running_loop().time()
        dispatched=[]
        for i in range(1,count+1):
            t=i/count;u=t*t*(3-2*t)
            await asyncio.sleep(max(0,start+duration*t-asyncio.get_running_loop().time()))
            # Dispatch at the planned cadence. A modal/backdrop can delay CDP
            # acknowledgements; serially awaiting each would stretch the gesture.
            dispatched.append(asyncio.create_task(self.page.mouse.move(a+(x-a)*u,b+(y-b)*u)))
        await asyncio.gather(*dispatched)
        self.point=(x,y)
        self.events.append({'type':'drag-move' if self.down else 'move','seconds':self.now(),'duration':duration,'actual_duration':asyncio.get_running_loop().time()-start,'start':[a,b],'end':[x,y]})
    async def aim(self,locator,kind='element',label='',consume=True):
        if kind!='element':raise RuntimeError('aim is cursor-only; use highlight for semantic sections')
        await asyncio.sleep(max(0,self.post_until-self.now()))
        await locator.scroll_into_view_if_needed()
        box=await locator.bounding_box()
        if not box:raise RuntimeError('Real UI target unavailable: '+str(locator))
        x=box['x']+box['width']/2;y=box['y']+box['height']/2
        duration=min(.7,max(.3,math.hypot(x-self.point[0],y-self.point[1])/1800))
        pending=self.pending if consume else None
        if pending:await asyncio.sleep(max(0,pending[1]-duration-self.now()))
        await locator.evaluate('el=>window.__s11Capture.aim(el)')
        await audit(self.page)
        movement_start=self.now()
        await self.move(x,y,duration=duration)
        arrival=self.now()
        self.arrival={'seconds':arrival,'phrase_end':pending[2] if pending else None,'phrase':pending[0] if pending else None}
        if pending:
            error=arrival-pending[1]
            self.cues.append({'phrase':pending[0],'target_seconds':pending[1],'phrase_end_seconds':pending[2],
                             'actual_seconds':arrival,'movement_start_seconds':movement_start,'kind':'cursor-arrival','error_seconds':error})
            self.pending=None
            if self.timing.get('strict_choreography') and abs(error)>.18:
                raise RuntimeError(f'cursor arrival missed {pending[0]!r} by {error:.3f}s')
        self.events.append({'type':'cursor-arrival','seconds':arrival,'target':str(locator),'box':box,'label':label})
        await audit(self.page)
    async def highlight(self,locator,phrase=None,label=''):
        locator=getattr(locator,'raw',locator)
        if phrase:await self.cue(phrase)
        await locator.scroll_into_view_if_needed()
        if self.pending:
            phrase,target,end=self.pending
            await asyncio.sleep(max(0,target-self.now()))
            self.cues.append({'phrase':phrase,'target_seconds':target,'actual_seconds':self.now(),'kind':'section'})
            self.pending=None
        await locator.evaluate('(el,label)=>window.__s11Capture.highlight(el,label)',label)
        screenshot=None
        if self.timing and self.timing.get('evidence_directory'):
            from pathlib import Path
            screenshot=Path(self.timing['evidence_directory'])/f"{self.scene['id']}-section-{len(self.geometry)+1}.png"
        result=await audit(self.page,pixels=True,screenshot=screenshot)
        self.geometry.append({'seconds':self.now(),'target':str(locator),**result})
        self.events.append({'type':'section-highlight','seconds':self.now(),'target':str(locator),'label':label,'cursor_emphasis':False})
    async def focus(self,locator,phrase=None,kind='section',label=''):
        # Compatibility for existing scene recipes. The primitives remain separate.
        if kind=='element':
            if phrase:await self.cue(phrase)
            await self.aim(getattr(locator,'raw',locator),label=label)
        else:await self.highlight(locator,phrase,label)
    async def before_action(self):
        if not self.arrival:raise RuntimeError('action without cursor arrival')
        earliest=max(self.arrival['seconds']+.75,(self.arrival['phrase_end'] or 0)+.25)
        await asyncio.sleep(max(0,earliest-self.now()))
        await audit(self.page)
        self.events.append({'type':'action-timing','seconds':self.now(),'arrival_seconds':self.arrival['seconds'],
                            'phrase_end_seconds':self.arrival['phrase_end'],'minimum_dwell_seconds':.75,
                            'dwell_seconds':self.now()-self.arrival['seconds'],'phrase':self.arrival['phrase']})
        await self.page.evaluate("window.__s11Capture.clear('action')")
    async def after_action(self):
        self.post_until=self.now()+.45
        await audit(self.page)
        await asyncio.sleep(max(0,self.post_until-self.now()))
    async def wait_pending(self):
        if self.pending:
            phrase,target,end=self.pending
            await asyncio.sleep(max(0,target-self.now()))
            self.cues.append({'phrase':phrase,'target_seconds':target,'actual_seconds':self.now(),'kind':'gesture'})
            self.pending=None
    async def stable(self):
        await self.page.evaluate('async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));}')
        self.ready=True
    async def snapshot(self):
        overlay=await self.page.evaluate('window.__s11Capture.evidence()')
        overlay['events']=[e for page in self.overlay_pages for e in page['events']]+overlay['events']
        overlay['cursorVisible']=overlay['cursorVisible'] and all(p['cursorVisible'] for p in self.overlay_pages)
        await audit(self.page)
        return {'events':self.events,'alignment_action_cues':self.cues,'geometry_checks':self.geometry,'overlay':overlay}


class CaptureLocator:
    def __init__(self,raw,director):self.raw=raw;self.d=director
    def __getattr__(self,name):
        from playwright.async_api import Locator
        item=getattr(self.raw,name)
        if isinstance(item,Locator):return CaptureLocator(item,self.d)
        if name in ('locator','get_by_role','get_by_text','get_by_label','filter','nth'):
            return lambda *a,**kw:CaptureLocator(item(*a,**kw),self.d)
        return item
    async def click(self,**kwargs):
        await self.d.aim(self.raw)
        href=await self.raw.get_attribute('href');nav=bool(href and not href.startswith(('#','blob:','data:')) and not await self.raw.get_attribute('download'))
        if nav:self.d.ready=False
        element_id=await self.raw.get_attribute('id')
        if element_id in ('archive-create-pick','archive-create-add','archive-create-replace','import-replace','import-add'):self.d.file_picker_id=element_id
        await self.d.before_action()
        start=self.d.now();await self.raw.click(**kwargs)
        self.d.events.append({'type':'click','seconds':start,'target':str(self.raw),'ripple':True})
        if not nav:await self.d.after_action()
    async def check(self,**kwargs):
        if not await self.raw.is_checked():await self.click(**kwargs)
    async def fill(self,value,**kwargs):
        await self.d.aim(self.raw);await self.d.before_action();await self.raw.focus()
        typ=await self.raw.get_attribute('type')
        if typ in ('text','search'):
            await self.raw.fill('');await self.raw.press_sequentially(value,delay=24)
        else:await self.raw.fill(value,**kwargs)
        self.d.events.append({'type':'field-input','seconds':self.d.now(),'target':str(self.raw)});await self.d.after_action()
    async def set_input_files(self,files,**kwargs):
        element_id=await self.raw.get_attribute('id')
        candidates={'archive-create-files':'#archive-create-pick:visible, #archive-create-add:visible','processor-file':'#import-replace','import-add-files':'#import-add'}
        if self.d.file_picker_id:
            target=self.d.page.locator('#'+self.d.file_picker_id)
        else:
            target=self.d.page.locator(candidates[element_id]).first
            await self.d.aim(target)
            await self.d.before_action()
            await self.d.page.mouse.down();await self.d.page.mouse.up()
        self.d.file_picker_id=None
        await self.raw.set_input_files(files,**kwargs)
        self.d.events.append({'type':'file-selection','seconds':self.d.now(),'target':str(target),'synthetic_only':True});await self.d.after_action()
    async def select_option(self,value,**kwargs):
        await self.d.aim(self.raw);await self.d.before_action();await self.raw.click()
        await asyncio.sleep(.25)
        await self.raw.select_option(value,**kwargs)
        await self.raw.press('Tab')
        if await self.raw.input_value()!=value:raise RuntimeError('real dropdown selection failed')
        self.d.events.append({'type':'select','seconds':self.d.now(),'target':str(self.raw)})
    async def focus(self,**kwargs):
        await self.d.aim(self.raw);await self.raw.focus(**kwargs)
    async def press(self,key,**kwargs):
        await self.d.aim(self.raw);await self.d.before_action();await self.raw.press(key,**kwargs);await self.d.after_action()
        self.d.events.append({'type':'key','key':key,'seconds':self.d.now(),'target':str(self.raw)})
    async def scroll_into_view_if_needed(self,**kwargs):
        await self.raw.scroll_into_view_if_needed(**kwargs)
        await self.d.highlight(self.raw)
    async def wait_for(self,**kwargs):
        await self.raw.wait_for(**kwargs)
        if not self.d.ready:await self.d.stable()


class CaptureMouse:
    def __init__(self,d):self.d=d
    async def move(self,x,y,**kwargs):await self.d.move(x,y)
    async def down(self,**kwargs):
        await self.d.wait_pending()
        await self.d.page.mouse.down(**kwargs);self.d.down=True;self.d.events.append({'type':'drag-start','seconds':self.d.now(),'point':self.d.point})
    async def up(self,**kwargs):
        await self.d.page.mouse.up(**kwargs);self.d.down=False;self.d.events.append({'type':'drag-end','seconds':self.d.now(),'point':self.d.point});await asyncio.sleep(.2)


class CapturePage:
    def __init__(self,page,d):self.raw=page;self.tutorial=d;self.mouse=CaptureMouse(d)
    def __getattr__(self,name):
        item=getattr(self.raw,name)
        if name in ('locator','get_by_role','get_by_text','get_by_label'):
            return lambda *a,**kw:CaptureLocator(item(*a,**kw),self.tutorial)
        return item
