"""Validate the pixels actually rendered around a semantic section (no PIL)."""
import asyncio
import subprocess


def rendered_outline(png, width, height, target, tolerance=2):
    rgb = subprocess.run(['ffmpeg','-v','error','-i','pipe:0','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],
                         input=png,capture_output=True,check=True).stdout
    # The outline is cyan and intentionally unlike the site's normal blue controls.
    points=[]
    for y in range(max(0,int(target['y'])-8),min(height,int(target['y']+target['height'])+9)):
        for x in range(max(0,int(target['x'])-8),min(width,int(target['x']+target['width'])+9)):
            i=(y*width+x)*3;r,g,b=rgb[i:i+3]
            if abs(r-25)<=3 and abs(g-188)<=3 and abs(b-230)<=3: points.append((x,y))
    if not points:raise RuntimeError('geometry regression: rendered section outline is missing')
    actual=[min(x for x,y in points),min(y for x,y in points),max(x for x,y in points)+1,max(y for x,y in points)+1]
    expected=[max(0,target['x']-6),max(0,target['y']-6),min(width,target['x']+target['width']+6),min(height,target['y']+target['height']+6)]
    error=max(abs(a-b) for a,b in zip(actual,expected))
    if error>tolerance:raise RuntimeError(f'geometry regression: outline {actual} != semantic target {expected}; error {error:.2f}px')
    return {'status':'PASS','tolerance_px':tolerance,'max_error_px':error,'rendered_bounds':actual,'expected_bounds':expected}


async def audit(page, *, pixels=False, screenshot=None):
    result=await page.evaluate('window.__s11Capture.audit()')
    if result['violations']:raise RuntimeError('capture regression: '+', '.join(result['violations']))
    if pixels:
        if not result['geometry']:raise RuntimeError('geometry regression: semantic section disappeared')
        png=await page.screenshot(path=str(screenshot) if screenshot else None)
        result['pixels']=await asyncio.to_thread(rendered_outline,png,*result['viewport'],result['geometry']['target'])
    return result
