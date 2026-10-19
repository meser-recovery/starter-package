(() => {
  const C = {bg:'#0c1e30', ink:'#f2f6fa', muted:'#9bb1c3', line:'#426078',
    blue:'#58b7ee', teal:'#5fd7bd', amber:'#f6b853', violet:'#ba9cf4'};
  let canvas,ctx,mode='local',started=0,active=false;
  const ease=x=>{x=Math.max(0,Math.min(1,x));return x*x*(3-2*x)};
  const round=(x,y,w,h,r,fill,stroke)=>{ctx.beginPath();ctx.roundRect(x,y,w,h,r);
    if(fill){ctx.fillStyle=fill;ctx.fill()}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=2;ctx.stroke()}};
  function label(text,x,y,size=22,color=C.ink,align='center'){
    ctx.fillStyle=color;ctx.font=`600 ${size}px system-ui, sans-serif`;ctx.textAlign=align;ctx.fillText(text,x,y);
  }
  function track(x,y,w,color,seed=0){
    ctx.strokeStyle=color;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+w,y);ctx.stroke();
    for(let i=0;i<27;i++){const xx=x+8+i*(w-16)/27;const a=6+11*Math.abs(Math.sin(i*.79+seed)*Math.sin(i*.31+seed));
      ctx.strokeStyle=color;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(xx,y-a);ctx.lineTo(xx,y+a);ctx.stroke()}
  }
  function computer(x,y,w,kind='desktop'){
    const h=w*.65;round(x,y,w,h,14,'#102d43','#8eb4ca');
    round(x+12,y+12,w-24,h-28,7,'#082238');
    if(kind==='desktop'){
      ctx.strokeStyle='#8eb4ca';ctx.lineWidth=6;ctx.beginPath();ctx.moveTo(x+w/2,y+h);ctx.lineTo(x+w/2,y+h+20);ctx.moveTo(x+w*.34,y+h+22);ctx.lineTo(x+w*.66,y+h+22);ctx.stroke();
    }else{round(x-10,y+h,w+20,11,5,'#8eb4ca')}
    return {x:x+14,y:y+14,w:w-28,h:h-32};
  }
  function person(x,y,color){ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,27,0,Math.PI*2);ctx.fill();
    ctx.beginPath();ctx.roundRect(x-45,y+35,90,73,[44,44,10,10]);ctx.fill()}
  function archive(x,y,w,h){
    round(x,y,w,h,26,'#15364a','#62a4bd');
    ctx.fillStyle=C.teal;ctx.beginPath();ctx.arc(x+w/2,y+79,34,0,Math.PI*2);ctx.fill();
    ctx.strokeStyle='#0b2637';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(x+w/2-16,y+79);ctx.lineTo(x+w/2+17,y+79);ctx.moveTo(x+w/2,y+63);ctx.lineTo(x+w/2,y+96);ctx.stroke();
    label('Аудиоархив',x+w/2,y+152,28);label('портал Мэсэр',x+w/2,y+183,18,C.muted);
  }
  function movedTrack(x1,y1,x2,y2,p,color,seed){
    const t=ease(p);track(x1+(x2-x1)*t,y1+(y2-y1)*t,185,color,seed);
  }
  function render(now){
    if(!active)return;
    const dpr=window.devicePixelRatio||1,w=canvas.width/dpr,h=canvas.height/dpr;
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle=C.bg;ctx.fillRect(0,0,w,h);
    const sx=w/1728,sy=h/972;ctx.save();ctx.scale(sx,sy);
    const t=(now-started)/1000;
    label(mode==='local'?'Обработка на этом устройстве':mode==='archive'?'Исходники, проект и результат':mode==='handoff'?'Работу продолжает другой служащий':'Продолжение с другого устройства',864,112,36);
    if(mode==='local'){
      const screen=computer(175,285,520);label('Этот компьютер',435,675,26);
      [C.blue,C.amber,C.violet].forEach((color,i)=>track(screen.x+32,screen.y+65+i*70,screen.w-65,color,i));
      const p=ease((t-1.5)/2.5);ctx.globalAlpha=p;round(805,368,210,180,24,'#16435a','#58b7ee');
      track(831,429,155,C.blue,3);label('MP3',911,513,30);ctx.globalAlpha=1;
      ctx.globalAlpha=.35;archive(1190,280,350,370);ctx.globalAlpha=1;
      label('Архив не требуется',1365,715,22,C.muted);
    } else {
      const left=computer(96,318,430);const right=computer(1202,318,430,'laptop');
      archive(661,255,406,440);
      if(mode==='archive'){
        label('Исходные дорожки',310,675,22,C.muted);
        [C.blue,C.amber,C.violet].forEach((color,i)=>movedTrack(left.x+22,left.y+61+i*64,770,480+i*54,(t-1-i*.35)/3,color,i));
        const p=ease((t-5)/2);ctx.globalAlpha=p;label('Проект',865,630,22,C.teal);label('MP3',865,663,22,C.blue);ctx.globalAlpha=1;
      }else if(mode==='handoff'){
        person(315,222,C.blue);person(1417,222,C.teal);
        [C.blue,C.amber,C.violet].forEach((color,i)=>{
          const p=ease((t-1.3-i*.25)/3);movedTrack(750,485+i*53,right.x+38,right.y+67+i*61,p,color,i);
        });
        label('Сохранено',864,765,22,C.muted);
      }else{
        person(315,222,C.blue);
        [C.blue,C.amber,C.violet].forEach((color,i)=>{
          const p=ease((t-1-i*.22)/2.6);movedTrack(750,485+i*53,right.x+38,right.y+67+i*61,p,color,i);
        });
        label('Первый компьютер',310,675,21,C.muted);label('Другое устройство',1417,675,21,C.muted);
      }
    }
    ctx.restore();requestAnimationFrame(render);
  }
  window.B11Concept={
    mount(next,elapsed=0){
      if(!canvas){canvas=document.createElement('canvas');canvas.id='b11-concept';
        canvas.style='position:fixed;inset:0;width:100vw;height:100vh;z-index:9999;pointer-events:none;opacity:1;transition:opacity .45s';
        document.body.append(canvas);ctx=canvas.getContext('2d');
        const resize=()=>{const dpr=window.devicePixelRatio||1;canvas.width=Math.round(innerWidth*dpr);canvas.height=Math.round(innerHeight*dpr)};
        resize();addEventListener('resize',resize);active=true;requestAnimationFrame(render);
      }
      mode=next;started=performance.now()-elapsed*1000;canvas.style.opacity='1';
    },
    mode(next){mode=next;started=performance.now()},
    hide(){if(canvas){canvas.style.opacity='0';setTimeout(()=>{active=false;canvas.remove();canvas=null},500)}}
  };
})();
