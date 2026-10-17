#!/usr/bin/env python3
"""Real Chromium regression: pixels, native top layer, identity and outline failures."""
import asyncio,json,subprocess
from pathlib import Path
from build import demo_server
from capture_geometry import audit
from validate import ROOT

OUT=ROOT/'generated/visual-corrective-v2/evidence'

async def run(base):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={'width':1280,'height':900})
        await page.goto(base+'/login')
        await page.set_content('''<style>body{margin:0;background:white}section{padding:30px;background:#eee;width:320px;height:130px;margin:60px}dialog{transform:translate(70px,35px);padding:35px;border:0;overflow:visible}dialog section{margin:0}button{margin:20px}</style><section id="old">Source section</section><button id="open">Open</button><dialog><section id="inside">Selected files</section><button id="action">Save</button></dialog>''')
        legacy=subprocess.check_output(['git','show','48479d39d8a026f8dd5ee1006ec54ba0c0374b84:tutorial/scripts/capture_overlay.js'],cwd=ROOT.parent,text=True)
        await page.add_script_tag(content=legacy)
        await page.evaluate("window.__s11Capture.start();document.querySelector('dialog').showModal();window.__s11Capture.focus(document.querySelector('#inside').getBoundingClientRect().toJSON(),'','section',document.querySelector('#inside'))")
        await page.wait_for_timeout(80)
        old=await page.evaluate("()=>({target:document.querySelector('#inside').getBoundingClientRect().toJSON(),rendered:document.querySelector('#__s11-focus').getBoundingClientRect().toJSON()})")
        old['displacement_px']=max(abs(old['rendered']['x']-(old['target']['x']-5)),abs(old['rendered']['y']-(old['target']['y']-5)))
        assert old['displacement_px']>50,old
        await page.screenshot(path=str(OUT/'regression-legacy-dialog.png'))
        await page.close()
        page=await browser.new_page(viewport={'width':1280,'height':900})
        await page.goto(base+'/login')
        await page.set_content('''<style>body{margin:0;background:white}section{padding:30px;background:#eee;width:320px;height:130px;margin:60px}dialog{transform:translate(70px,35px);padding:35px;border:0;overflow:visible}dialog section{margin:0}button{margin:20px}</style><section id="old">Source section</section><button id="open">Open</button><dialog><section id="inside">Selected files</section><button id="action">Save</button></dialog>''')
        await page.add_script_tag(path=str(ROOT/'scripts/capture_overlay.js'))
        await page.evaluate("window.__s11Capture.start();window.__s11Capture.highlight(document.querySelector('#old'))")
        first=await audit(page,pixels=True)
        await page.evaluate("document.querySelector('dialog').showModal()")
        assert not (await audit(page))['geometry'],'Underlying section survived modal opening'
        await page.evaluate("window.__s11Capture.highlight(document.querySelector('#inside'))")
        modal=await audit(page,pixels=True,screenshot=OUT/'regression-fixed-dialog.png')
        await page.evaluate("document.querySelector('dialog').style.transform='translate(-110px,80px)'")
        reflow=await audit(page,pixels=True)
        await page.evaluate("document.querySelector('#inside').setAttribute('role','status')")
        assert not (await audit(page))['geometry'],'Changed role retained highlight'
        await page.evaluate("window.__s11Capture.highlight(document.querySelector('#inside'));document.querySelector('#inside').replaceWith(document.querySelector('#inside').cloneNode(true))")
        # A replacement node must not inherit capture-only decoration.
        cleared=await page.evaluate("document.querySelectorAll('.__s11-section-highlight').length")
        assert cleared==0,'Replacement inherited stale capture highlight'
        await page.evaluate("window.__s11Capture.aim(document.querySelector('#action'))")
        clean=await audit(page)
        await page.mouse.move(500,450)
        cursor=await page.evaluate("()=>({parent:document.querySelector('#__s11-overlay').parentElement.tagName,rect:document.querySelector('#__s11-cursor').getBoundingClientRect().toJSON()})")
        assert cursor['parent']=='BODY' and abs(cursor['rect']['x']-498)<1 and abs(cursor['rect']['y']-448)<1,cursor
        await page.evaluate("document.querySelector('#action').style.setProperty('outline','5px solid red','important')")
        try:await audit(page)
        except RuntimeError as e:outline_failure=str(e)
        else:raise AssertionError('Outlined cursor target was accepted')
        await page.evaluate("document.querySelector('#action').style.removeProperty('outline');window.__s11Capture.start();window.__s11Capture.highlight(document.querySelector('#inside'))")
        await page.evaluate("document.querySelector('#inside').style.setProperty('outline-offset','25px','important')")
        try:await audit(page,pixels=True)
        except RuntimeError as e:geometry_failure=str(e)
        else:raise AssertionError('Displaced outline was accepted')
        await browser.close()
    result={'status':'PASS','legacy_reproduction':old,'section_pixels':first['pixels'],'transformed_dialog_pixels':modal['pixels'],'reflow_pixels':reflow['pixels'],'outline_failure_detected':outline_failure,'geometry_failure_detected':geometry_failure,'modal_clears_underlying':True,'role_change_clears':True,'replacement_clears':True,'cursor_viewport_geometry':cursor}
    (OUT/'geometry-regression.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    with demo_server(None) as base:asyncio.run(run(base))
