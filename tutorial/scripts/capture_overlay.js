/* Capture-only instrumentation. Never imported by the production frontend. */
(() => {
  const key = 's11-tutorial-capture';
  try { sessionStorage.getItem(key); } catch { return; }
  const sectionClass = '__s11-section-highlight';
  const controls = 'button,a,input,select,textarea,summary,[role="button"],[role="link"],[role="switch"],[role="checkbox"],[role="textbox"],[role="slider"]';
  let root, cursor, section = null, control = null, identity = null, parent = null;
  const failures = new Set();
  let last = JSON.parse(sessionStorage.getItem(key + '-point') || '[150,180]');
  const events = () => JSON.parse(sessionStorage.getItem(key + '-events') || '[]');
  const log = (type, extra = {}) => {
    const rows = events(); rows.push({type, t: performance.now(), ...extra});
    sessionStorage.setItem(key + '-events', JSON.stringify(rows));
  };
  const active = () => sessionStorage.getItem(key) === 'on';
  const signature = el => [el.tagName, el.id, el.getAttribute('role'), el.getAttribute('type'), el.getAttribute('href'), el.getAttribute('aria-label') || el.textContent.trim().replace(/\s+/g, ' ')].join('|');
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
        #__s11-cursor{position:absolute;width:25px;height:34px;filter:drop-shadow(0 2px 2px #0009);transform:translate(-2px,-2px)}
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
    const violations = [];
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
    return {violations: [...failures], geometry, cursorVisible: !!cursor && cursor.style.visibility !== 'hidden', point: last, viewport: [innerWidth, innerHeight]};
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
    const ring = document.createElement('div'); ring.className = 's11-ring';
    ring.style.left = e.clientX + 'px'; ring.style.top = e.clientY + 'px'; root.append(ring);
    setTimeout(() => ring.remove(), 520); log('pointerdown', {x:e.clientX,y:e.clientY,ring:true});
  }, true);
  window.__s11Capture = {
    start() { failures.clear(); if (!active()) sessionStorage.setItem(key + '-events', '[]'); sessionStorage.setItem(key, 'on'); install(); },
    aim(el) { install(); clear('cursor-target'); control = el; cursor.style.visibility = 'visible'; log('cursor-target', {semantic: signature(el)}); },
    highlight(el, label = '') {
      install(); clear('next-section'); control = null;
      if (el.matches(controls)) throw Error('Cannot section-highlight a concrete control');
      const modal = [...document.querySelectorAll('dialog[open]')].at(-1);
      if (modal && el !== modal && !modal.contains(el)) throw Error('Cannot highlight behind an open dialog');
      section = el; parent = el.parentElement; identity = signature(el);
      el.classList.add(sectionClass); cursor.style.visibility = 'hidden'; log('section-highlight', {label,semantic:identity});
    },
    setPoint(point) { last = point; sessionStorage.setItem(key + '-point', JSON.stringify(last)); install(); },
    clear, audit,
    evidence() { return {...audit(), events: events()}; }
  };
  function ready() {
    install();
    new MutationObserver(records => {
      validateIdentity();
      if (records.some(r => r.type === 'attributes' && r.attributeName === 'open')) refreshTopLayer();
    }).observe(document.body, {subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['open','id','role','type','href','hidden','style','class']});
    function frame() { if (active()) audit(); requestAnimationFrame(frame); } requestAnimationFrame(frame);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
})();
