import test from 'node:test';
import assert from 'node:assert/strict';
import { drawWaveformViewport } from '../../scripts/audio-waveform-view.mjs';
import { waveformImageSpec } from '../../scripts/audio-waveform-image.mjs';
function canvas() {
  const points = []; let paints = 0;
  const context = { fillRect() { paints++; }, beginPath() { points.length = 0; },
    moveTo(...p) { points.push(p); }, lineTo(...p) { points.push(p); }, closePath() {}, fill() {} };
  return { style: {}, points, get paints() { return paints; }, getContext: () => context };
}
test('FFmpeg columns retain the actual padded sample clock', () => {
  for (const duration of [32,17.3,9.37,129.37,3747]) {
    const width = Math.min(65536, Math.floor(duration * 4000));
    const spec = waveformImageSpec(duration,width,100);
    assert.ok(spec.duration >= duration && spec.duration-duration < width/48000);
    assert.ok(Math.abs(spec.duration*spec.sampleRate-width)<1e-8);
    assert.match(spec.filter,/scale=lin:filter=peak:draw=full/);
  }
});
test('Retina bitmap stays bounded by viewport plus a fixed guard, even for hours', () => {
  const c=canvas();drawWaveformViewport(c,new Float32Array(65536).fill(.5),3600,1000,100000,900,112,2);
  assert.ok(c.width >= 1800 && c.width <= (900+640)*2);assert.equal(c.height,224);
  assert.equal(c.width,parseFloat(c.style.width)*2);
});
test('a narrow transient survives overview aggregation without spaced bars', () => {
  const c=canvas(),s=new Float32Array(1000);s[79]=1;
  drawWaveformViewport(c,s,10,1,0,10,100,1);
  assert.ok(c.points.some(([x,y])=>x===.5&&y===4));
  assert.ok(c.points.some(([x,y])=>x===1.5&&y===49.5));
});
test('panning retains the existing bitmap until its guard is exhausted', () => {
  const c=canvas(),s=new Float32Array(64000).fill(.4);
  drawWaveformViewport(c,s,32,1000,1000,800,100,2);
  const origin=c.style.left,paints=c.paints;
  for(const left of [1001,1007.5,1100,1190]) drawWaveformViewport(c,s,32,1000,left,800,100,2);
  assert.equal(c.paints,paints);assert.equal(c.style.left,origin);
  drawWaveformViewport(c,s,32,1000,1500,800,100,2);assert.equal(c.paints,paints+1);
});
test('source contour is identical across guard replacement and detail-window replacement', () => {
  const s=Float32Array.from({length:64000},(_,i)=>((i*37)%101)/101);s.sampleRate=2000;
  const c=canvas(),d=canvas();
  drawWaveformViewport(c,s,32,300,2500,900,100,2);
  const tail=s.slice(16000);tail.sampleRate=2000;
  drawWaveformViewport(d,tail,24,300,2600,900,100,2,8);
  const world=(v)=>new Map(v.points.map(([x,y])=>[x+parseFloat(v.style.left)*2+':'+(y<100?'upper':'lower'),y]));
  const first=world(c),second=world(d);let compared=0;
  for(const [x,y] of first) if(second.has(x)){assert.equal(second.get(x),y);compared++;}
  assert.ok(compared>1000);
});
test('every zoom uses the same connected contour and never a bar-style threshold', () => {
  const old=globalThis.getComputedStyle;
  globalThis.getComputedStyle=()=>({getPropertyValue:k=>k==='--wave-bar-step'?'3':''});
  try {
    for(const pps of [1,80,159,160,300,1000])for(const dpr of [1,2]) {
      const c=canvas();drawWaveformViewport(c,new Float32Array(65536).fill(.5),73,pps,0,500,100,dpr);
      const upper=c.points.filter(([,y])=>y<50*dpr);
      for(let i=2;i<upper.length-1;i++)assert.equal(upper[i][0]-upper[i-1][0],dpr);
      assert.equal(Math.min(...upper.map(([,y])=>y))/dpr,27);
    }
  } finally {if(old)globalThis.getComputedStyle=old;else delete globalThis.getComputedStyle;}
});
test('a changed theme repaints a stationary waveform', () => {
  const old=globalThis.getComputedStyle;let color='#123456';
  globalThis.getComputedStyle=()=>({getPropertyValue:k=>k==='--track-wave'?color:''});
  try {
    const c=canvas(),s=new Float32Array(32).fill(.4);
    drawWaveformViewport(c,s,32,10,0,100);const count=c.paints;
    drawWaveformViewport(c,s,32,10,0,100);assert.equal(c.paints,count);
    color='#654321';drawWaveformViewport(c,s,32,10,0,100);assert.equal(c.paints,count+1);
  } finally {if(old)globalThis.getComputedStyle=old;else delete globalThis.getComputedStyle;}
});

test('a shorter track ends at its source time instead of stretching into the shared timeline', () => {
  const c=canvas();drawWaveformViewport(c,new Float32Array([.2,.5,1,.3]),4,10,20,400,100,2);
  assert.equal(Math.max(...c.points.map(([x])=>x/2+parseFloat(c.style.left))),40);
});
