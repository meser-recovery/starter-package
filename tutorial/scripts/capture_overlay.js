/* Capture-only instrumentation. Never imported by the production frontend. */
(() => {
  const key = 's11-tutorial-capture';
  try { sessionStorage.getItem(key); } catch { return; }
  const sectionClass = '__s11-section-highlight';
  const controls = 'button,a,input,select,textarea,summary,[tabindex]:not([tabindex="-1"]),[role="button"],[role="link"],[role="switch"],[role="checkbox"],[role="textbox"],[role="slider"]';
  let root, cursor, section = null, control = null, identity = null, parent = null;
  let cursorState = 'hidden', cursorIdentity = null, cursorParent = null, cursorContext = '';
  let actionPoint = null, lastAction = 0;
  const lifecycle = {visibleFrames:0, hiddenFrames:0, invalidVisibleFrames:0};
  const failures = new Set();
  let last = JSON.parse(sessionStorage.getItem(key + '-point') || '[150,180]');
  const events = () => JSON.parse(sessionStorage.getItem(key + '-events') || '[]');
  const log = (type, extra = {}) => {
    const rows = events(); rows.push({type, t: performance.now(), ...extra});
    sessionStorage.setItem(key + '-events', JSON.stringify(rows));
  };
  const active = () => sessionStorage.getItem(key) === 'on';
  const signature = el => [el.tagName, el.id, el.getAttribute('role'), el.getAttribute('type'), el.getAttribute('href'), el.getAttribute('aria-label') || el.textContent.trim().replace(/\s+/g, ' ')].join('|');
  const gestureSignature = el => [el.tagName,el.id,el.getAttribute('role'),el.getAttribute('aria-label'),el.getAttribute('data-track-id')].join('|');
  const contexts = () => [...document.querySelectorAll('dialog[open],[role="dialog"][aria-modal="true"],[role="menu"],[role="listbox"]')]
    .filter(el => el.checkVisibility()).map(el => [el.tagName,el.id,el.getAttribute('role')].join(':')).join('|');
  function hideCursor(reason) {
    if (cursorState !== 'hidden') log('cursor-hide', {reason, semantic:cursorIdentity, point:last});
    cursorState = 'hidden';
    if (cursor) cursor.style.visibility = 'hidden';
    // A ripple must not land on an unrelated element after a transition either.
    if (root) root.querySelectorAll('.s11-ring').forEach(el => el.remove());
  }
  function cursorValidity() {
    if (!control?.isConnected || !control.checkVisibility()) return 'target-removed-or-hidden';
    if (control.parentElement !== cursorParent || (cursorState.startsWith('gesture')?gestureSignature(control):signature(control)) !== cursorIdentity) return 'target-identity-changed';
    if (contexts() !== cursorContext) return 'dialog-or-menu-transition';
    if (control.disabled || control.closest('[inert]')) return 'target-disabled-or-inert';
    if (cursorState === 'target') {
      const hit = document.elementFromPoint(...last);
      if (!hit || (hit !== control && !control.contains(hit))) return 'target-reflowed-or-occluded';
    }
    return null;
  }
  function followCursor() {
    if (cursorState !== 'hidden') {
      const reason = cursorValidity();
      if (reason) hideCursor(reason);
    }
  }
  function aim(el, gesture=false) {
    install(); clear('cursor-target');
    const wasHidden = cursorState === 'hidden';
    control = el; cursorIdentity = gesture?gestureSignature(el):signature(el); cursorParent = el.parentElement; cursorContext = contexts();
    cursorState = gesture ? 'gesture-approach' : 'approach';
    if (wasHidden) {
      // Re-enter near the NEW target, never resurrect coordinates from an old screen.
      const r=el.getBoundingClientRect();
      last=[Math.max(18,Math.min(innerWidth-30,r.x+r.width/2-85)),Math.max(18,Math.min(innerHeight-38,r.y+r.height/2+55))];
      sessionStorage.setItem(key+'-point',JSON.stringify(last)); install();
    }
    cursor.style.visibility = 'visible';
    log('cursor-show', {semantic:cursorIdentity, point:last, freshEntry:wasHidden, gesture});
    return {point:last, freshEntry:wasHidden};
  }
  function clear(reason = 'explicit') {
    if (section) { section.classList.remove(sectionClass); log('section-clear', {reason}); }
    section = null; identity = null; parent = null;
    document.querySelectorAll('.' + sectionClass).forEach(el => el.classList.remove(sectionClass));
  }
  function install() {
    if (!document.body) return;
    if (!root) {
      const style = document.createElement('style');
      style.textContent = `html.__s11-capture-active,html.__s11-capture-active *{cursor:none!important}
        html.__s11-capture-active :is(${controls}):focus{outline:none!important}
        .${sectionClass}{outline:3px solid rgb(25,188,230)!important;outline-offset:3px!important}
        #__s11-overlay{position:fixed;inset:0;margin:0;padding:0;border:0;width:100vw;height:100vh;background:transparent;overflow:visible;pointer-events:none;z-index:2147483647}
        #__s11-overlay::backdrop{background:transparent;pointer-events:none}
        #__s11-cursor{position:absolute;width:25px;height:34px;visibility:hidden;filter:drop-shadow(0 2px 2px #0009);transform:translate(-2px,-2px)}
        .s11-ring{position:absolute;width:20px;height:20px;border:3px solid #ffc63d;border-radius:50%;transform:translate(-50%,-50%);animation:s11-click .5s ease-out forwards}
        @keyframes s11-click{to{width:48px;height:48px;opacity:0}}`;
      document.head.append(style);
      root = document.createElement('div'); root.id = '__s11-overlay';
      // A manual popover has viewport coordinates in the top layer. Never reparent
      // this into a dialog: transformed dialogs establish a different coordinate space.
      root.setAttribute('popover', 'manual'); root.setAttribute('aria-hidden', 'true');
      root.innerHTML = '<svg id="__s11-cursor" viewBox="0 0 25 34"><path d="M3 2L3 27L9 21L14 32L19 29L14 19L23 18Z" fill="#172e40" stroke="white" stroke-width="2" stroke-linejoin="round"/></svg>';
      document.body.append(root); cursor = root.firstElementChild;
    }
    document.documentElement.classList.toggle('__s11-capture-active', active());
    if (active() && !root.matches(':popover-open')) root.showPopover();
    cursor.style.left = last[0] + 'px'; cursor.style.top = last[1] + 'px';
  }
  function validateIdentity() {
    if (!section) return;
    const modal = [...document.querySelectorAll('dialog[open]')].at(-1);
    if (!section.isConnected || !section.checkVisibility() || section.parentElement !== parent || signature(section) !== identity ||
        (modal && section !== modal && !modal.contains(section))) clear('target-hidden-replaced-or-changed');
  }
  function audit() {
    validateIdentity();
    followCursor();
    const violations = [];
    const visible = !!cursor && getComputedStyle(cursor).visibility === 'visible';
    if (visible && (cursorState === 'hidden' || cursorValidity())) violations.push('visible cursor has no current semantic target');
    if (control?.isConnected && control.checkVisibility()) {
      const s = getComputedStyle(control);
      if ((s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || control.classList.contains(sectionClass)) violations.push('cursor target displays an outline');
    }
    const highlighted = [...document.querySelectorAll('.' + sectionClass)];
    if (highlighted.some(el => el.matches(controls))) violations.push('concrete control has section highlight');
    if (highlighted.some(el => el !== section)) violations.push('stale highlight class');
    let geometry = null;
    if (section) {
      const s = getComputedStyle(section), r = section.getBoundingClientRect();
      if (s.outlineStyle !== 'solid' || parseFloat(s.outlineWidth) !== 3 || parseFloat(s.outlineOffset) !== 3 || s.outlineColor !== 'rgb(25, 188, 230)') violations.push('section outline style changed');
      geometry = {target: r.toJSON(), outlineWidth: 3, outlineOffset: 3, semantic: signature(section)};
    }
    violations.forEach(v => failures.add(v));
    return {violations: [...failures], geometry, cursorVisible:visible, cursorState, cursorTarget:cursorIdentity,
      lifecycle, point: last, viewport: [innerWidth, innerHeight]};
  }
  function refreshTopLayer() {
    validateIdentity();
    if (!root || !active()) return;
    // Re-show in front of newly opened native modal, without changing coordinates.
    root.hidePopover(); root.showPopover();
  }
  document.addEventListener('pointermove', e => {
    last = [e.clientX, e.clientY]; sessionStorage.setItem(key + '-point', JSON.stringify(last)); install();
  }, true);
  document.addEventListener('pointerdown', e => {
    clear('action'); if (!active()) return;
    actionPoint=[e.clientX,e.clientY];lastAction=performance.now();
    const ring = document.createElement('div'); ring.className = 's11-ring';
    ring.style.left = e.clientX + 'px'; ring.style.top = e.clientY + 'px'; root.append(ring);
    setTimeout(() => ring.remove(), 520); log('pointerdown', {x:e.clientX,y:e.clientY,ring:true,semantic:cursorIdentity});
  }, true);
  document.addEventListener('click',()=>queueMicrotask(followCursor),true);
  window.addEventListener('pagehide',()=>hideCursor('navigation'));
  window.addEventListener('beforeunload',()=>hideCursor('navigation'));
  document.addEventListener('scroll',followCursor,true);
  window.__s11Capture = {
    start() { failures.clear(); if (!active()) sessionStorage.setItem(key + '-events', '[]'); sessionStorage.setItem(key, 'on'); install(); hideCursor('capture-start'); },
    aim,
    arrived() { if(cursorState==='approach')cursorState='target'; followCursor(); log('cursor-arrived',{semantic:cursorIdentity,point:last,visible:cursorState!=='hidden'}); },
    gestureAt(x,y) {
      const hit=document.elementFromPoint(x,y);
      if(!hit)throw Error('Gesture has no real UI target');
      return aim(hit.closest('.speaker-track,.processor-track')||hit,true);
    },
    gestureStart() { cursorState='gesture'; log('cursor-gesture-start',{semantic:cursorIdentity}); },
    gestureEnd() { log('cursor-gesture-end',{semantic:cursorIdentity}); hideCursor('gesture-finished'); },
    afterAction() { followCursor(); log('cursor-after-action',{state:cursorState,semantic:cursorIdentity,feedback_ms:performance.now()-lastAction,point:actionPoint}); },
    hide:hideCursor,
    highlight(el, label = '') {
      install(); clear('next-section'); hideCursor('section-emphasis'); control = null;
      if (el.matches(controls)) throw Error('Cannot section-highlight a concrete control');
      const modal = [...document.querySelectorAll('dialog[open]')].at(-1);
      if (modal && el !== modal && !modal.contains(el)) throw Error('Cannot highlight behind an open dialog');
      section = el; parent = el.parentElement; identity = signature(el);
      el.classList.add(sectionClass); log('section-highlight', {label,semantic:identity});
    },
    setPoint(point) { last = point; sessionStorage.setItem(key + '-point', JSON.stringify(last)); install(); },
    clear, audit,
    evidence() { return {...audit(), events: events()}; }
  };
  function ready() {
    install();
    new MutationObserver(records => {
      validateIdentity();
      followCursor();
      if (records.some(r => r.type === 'attributes' && r.attributeName === 'open')) refreshTopLayer();
    }).observe(document.body, {subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['open','id','role','type','href','hidden','style','class','disabled','inert','aria-expanded','aria-label']});
    function frame() { if (active()) { const a=audit(); lifecycle[a.cursorVisible?'visibleFrames':'hiddenFrames']++; if(a.cursorVisible&&a.violations.length)lifecycle.invalidVisibleFrames++; } requestAnimationFrame(frame); } requestAnimationFrame(frame);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
})();
