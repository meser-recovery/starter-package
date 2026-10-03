#!/usr/bin/env python3
"""Browser regression for automatic semantic cursor lifecycle across UI transitions."""
import asyncio,json
from build import demo_server
from capture_geometry import audit
from validate import ROOT

OUT=ROOT/'generated/visual-corrective-v2-full/evidence'

async def run(base):
    from playwright.async_api import async_playwright
    import verify_capture_v2
    verify_capture_v2.OUT=OUT
    await verify_capture_v2.run(base)
    results=[]
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        context=await browser.new_context(viewport={'width':1280,'height':900})
        await context.add_init_script(path=str(ROOT/'scripts/capture_overlay.js'))
        page=await context.new_page()
        await page.goto(base+'/login')
        # These are regression fixtures, never substituted into tutorial captures.
        await page.set_content('''<style>body{margin:80px;background:white}button{padding:18px;margin:15px}dialog{transform:translate(80px,40px);padding:50px}#menu{position:absolute;left:500px;top:100px;background:#ddd}#range:focus{outline:3px dashed blue}</style>
          <section id="screen"><button id="stay">Same action</button><button id="open" onclick="document.querySelector('#modal').showModal()">Open dialog</button><button id="replace">Replace screen</button><div id="range" role="group" tabindex="0">Keyboard-operable waveform region</div></section>
          <dialog id="modal"><button id="close" onclick="document.querySelector('#modal').close()">Close dialog</button><section id="area">Current semantic section</section></dialog><div id="menu" role="menu" hidden>Actual open menu</div>''')
        await page.add_script_tag(path=str(ROOT/'scripts/capture_overlay.js'))
        await page.evaluate('window.__s11Capture.start()')
        assert not (await audit(page))['cursorVisible']
        async def aim(selector):
            locator=page.locator(selector)
            entry=await locator.evaluate('el=>window.__s11Capture.aim(el)')
            r=await locator.bounding_box()
            await page.mouse.move(r['x']+r['width']/2,r['y']+r['height']/2)
            await page.evaluate('window.__s11Capture.arrived()')
            assert (await audit(page))['cursorVisible'],selector
            return entry
        async def hidden(name):
            a=await audit(page);assert not a['cursorVisible'],name
            results.append({'scenario':name,'status':'PASS','state':a['cursorState']})
        await aim('#stay');await page.locator('#stay').click(delay=130)
        await page.evaluate('window.__s11Capture.afterAction()')
        assert (await audit(page))['cursorVisible']
        results.append({'scenario':'unchanged target remains visible','status':'PASS'})
        await aim('#range');await page.locator('#range').focus()
        assert (await audit(page))['cursorVisible']
        assert await page.locator('#range').evaluate("el=>getComputedStyle(el).outlineStyle==='none'")
        results.append({'scenario':'keyboard-operable region is a cursor-only control','status':'PASS'})
        await aim('#open');await page.locator('#open').click(delay=130)
        await hidden('native top-layer dialog hides underlying target')
        entry=await aim('#close');assert entry['freshEntry']
        await page.locator('#close').click(delay=130)
        await hidden('closed dialog never resurrects its cursor')
        await aim('#stay');await page.evaluate("document.querySelector('#menu').hidden=false")
        await hidden('opening menu hides old target')
        await page.evaluate("document.querySelector('#menu').hidden=true")
        await hidden('closing menu does not auto-show cursor')
        await aim('#stay');await page.evaluate("document.querySelector('#stay').setAttribute('aria-label','New unrelated operation')")
        await hidden('same DOM node changes semantic identity')
        await aim('#stay');await page.evaluate("document.querySelector('#stay').style.transform='translateY(180px)'")
        await hidden('reflow cannot point at unrelated coordinates')
        await aim('#replace');await page.evaluate("document.querySelector('#screen').innerHTML='<button id=next>Unrelated new screen</button>'")
        await hidden('section replacement discards old target')
        fresh=await aim('#next');assert fresh['freshEntry']
        await page.locator('#next').evaluate("el=>{el.disabled=true}")
        await hidden('disabled target becomes semantically inactive')
        await page.locator('#next').evaluate("el=>{el.disabled=false}")
        await hidden('re-enabled target waits for explicit next aim')
        await aim('#next');await page.locator('#next').evaluate('el=>el.remove()')
        await hidden('removed target immediately hides')
        await page.goto(base+'/login')
        await page.evaluate('window.__s11Capture.start()')
        await hidden('navigation begins with hidden cursor')
        await page.evaluate("document.querySelector('#__s11-cursor').style.visibility='visible'")
        try:await audit(page)
        except RuntimeError as error:results.append({'scenario':'orphan visible cursor fails capture','status':'PASS','caught':str(error)})
        else:raise AssertionError('Orphan visible cursor was accepted')
        await browser.close()
    report={'status':'PASS','automatic_lifecycle':True,'scenarios':results}
    (OUT/'cursor-lifecycle-regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    with demo_server(None) as base:asyncio.run(run(base))
