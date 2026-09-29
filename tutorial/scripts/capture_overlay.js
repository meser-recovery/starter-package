/* Capture-only layer. Never imported by the production frontend. */
(() => {
  try { sessionStorage.getItem('s11-tutorial-capture'); } catch { return; }
  const key='s11-tutorial-capture';
  let focusTarget=null,focusKind='element';
  let root,cursor,focus,last=JSON.parse(sessionStorage.getItem(key+'-point')||'[150,180]');
  const events=()=>JSON.parse(sessionStorage.getItem(key+'-events')||'[]');
  const log=(type,extra={})=>{const rows=events();rows.push({type,t:performance.now(),...extra});sessionStorage.setItem(key+'-events',JSON.stringify(rows));};
  function install(){
    if(!document.body)return;
    if(!root){
      root=document.createElement('div');root.id='__s11-overlay';root.setAttribute('aria-hidden','true');
      root.innerHTML=`<style>#__s11-overlay{position:fixed;inset:0;pointer-events:none;z-index:2147483647}#__s11-cursor{position:fixed;width:25px;height:34px;filter:drop-shadow(0 2px 2px #0009);z-index:3;transform:translate(-2px,-2px)}#__s11-focus{position:fixed;border:3px solid #19bce6;border-radius:9px;box-shadow:0 0 0 3px #ffffffa0,0 0 18px #19bce655;display:none;z-index:1}#__s11-focus span{position:absolute;top:-30px;left:0;white-space:nowrap;background:#073448;color:white;padding:2px 9px;border-radius:4px;font:17px Arial}.s11-ring{position:fixed;width:20px;height:20px;border:3px solid #ffc63d;border-radius:50%;transform:translate(-50%,-50%);animation:s11-click .5s ease-out forwards;z-index:2}@keyframes s11-click{to{width:48px;height:48px;opacity:0}}#__s11-cursor[data-down=true]{filter:drop-shadow(0 0 5px #ffc63d)} </style><div id="__s11-focus"><span></span></div><svg id="__s11-cursor" viewBox="0 0 25 34"><path d="M3 2L3 27L9 21L14 32L19 29L14 19L23 18Z" fill="#172e40" stroke="white" stroke-width="2" stroke-linejoin="round"/></svg>`;
      cursor=root.querySelector('#__s11-cursor');focus=root.querySelector('#__s11-focus');
    }
    const modal=Array.from(document.querySelectorAll('dialog[open]')).at(-1);const host=modal||document.body;
    if(root.parentElement!==host)host.append(root);
    root.style.display=sessionStorage.getItem(key)==='on'?'block':'none';
    cursor.style.left=last[0]+'px';cursor.style.top=last[1]+'px';
  }
  function paintFocus(rect,kind){Object.assign(focus.style,{display:'block',left:Math.max(3,rect.x-5)+'px',top:Math.max(32,rect.y-5)+'px',width:Math.min(innerWidth-8,rect.width+10)+'px',height:Math.min(innerHeight-38,rect.height+10)+'px',boxShadow:kind==='element'?'0 0 0 3px #ffffffa0,0 0 18px #19bce655':'0 0 0 3000px #051d301c,0 0 0 3px #ffffffa0'});}
  function followFocus(){
    if(focusTarget){
      const rect=focusTarget.getBoundingClientRect();
      if(!focusTarget.isConnected||!rect.width||!rect.height){focus.style.display='none';focusTarget=null;}
      else paintFocus(rect,focusKind);
    }
    requestAnimationFrame(followFocus);
  }
  requestAnimationFrame(followFocus);
  const move=e=>{last=[e.clientX,e.clientY];sessionStorage.setItem(key+'-point',JSON.stringify(last));install();};
  document.addEventListener('pointermove',move,true);
  document.addEventListener('pointerdown',e=>{move(e);if(root.style.display==='none')return;cursor.dataset.down='true';const r=document.createElement('div');r.className='s11-ring';r.style.left=e.clientX+'px';r.style.top=e.clientY+'px';root.append(r);setTimeout(()=>r.remove(),520);log('pointerdown',{x:e.clientX,y:e.clientY,ring:true});},true);
  document.addEventListener('pointerup',()=>{if(cursor)cursor.dataset.down='false';if(sessionStorage.getItem(key)==='on')log('pointerup');},true);
  window.__s11Capture={
    start(){if(sessionStorage.getItem(key)!=='on')sessionStorage.setItem(key+'-events','[]');sessionStorage.setItem(key,'on');install();},
    focus(rect,label,kind,target=null){install();focusTarget=target;focusKind=kind;paintFocus(rect,kind);focus.querySelector('span').textContent=label||'';focus.querySelector('span').style.display=label?'block':'none';log('focus',{kind,label});},
    setPoint(point){last=point;sessionStorage.setItem(key+'-point',JSON.stringify(last));install();},
    clear(){focusTarget=null;if(focus)focus.style.display='none';},
    evidence(){return {events:events(),cursorVisible:!!cursor&&root.style.display!=='none',point:last};}
  };
  document.addEventListener('DOMContentLoaded',()=>{install();new MutationObserver(()=>{const host=Array.from(document.querySelectorAll('dialog[open]')).at(-1)||document.body;if(root?.parentElement!==host)install();}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open'],childList:true});});
  install();
})();
