// Native disclosure keeps contextual actions reachable by keyboard and touch.
export function contextActions(label, ...actions) {
  const menu = document.createElement('details'); menu.className = 'audio-actions';
  const summary = document.createElement('summary'); summary.textContent = 'Действия';
  summary.setAttribute('aria-label', `Действия · ${label}`);
  const body = document.createElement('div'); body.className = 'audio-actions__items';
  body.append(...actions); menu.append(summary, body);
  summary.addEventListener('click', event => {
    // Position before the next Tab or a queued scroll event can observe an
    // open disclosure whose popover has not yet reached the viewport.
    event.preventDefault();
    menu.open = !menu.open;
    if (menu.open) placeActions(menu, true);
  });
  menu.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.open) { event.preventDefault(); event.stopPropagation(); menu.open = false; summary.focus(); }
  });
  body.addEventListener('click', event => {
    if (event.target.closest('button, a') && !event.target.disabled) { menu.open = false; summary.focus(); }
  }, true);
  menu.addEventListener('toggle', () => {
    if (menu.open) {
      for (const other of document.querySelectorAll('.audio-actions[open]')) if (other !== menu) other.open = false;
      placeActions(menu, true);
    } else if (body.hasAttribute('popover')) body.hidePopover();
  });
  return menu;
}
document.addEventListener('click', event => {
  for (const menu of document.querySelectorAll('.audio-actions[open]')) if (!menu.contains(event.target)) menu.open = false;
});

// Desktop menus use the browser's top layer so sticky players/track controls
// cannot cover them. Small screens retain the existing in-flow disclosure.
function placeActions(menu, revealAnchor = false) {
  if (!menu.isConnected) return;
  const body = menu.querySelector('.audio-actions__items');
  if (typeof body.showPopover !== 'function') return;
  if (window.innerWidth < 768) {
    if (body.hasAttribute('popover')) body.hidePopover();
    body.removeAttribute('popover');
    for (const property of ['position', 'inset', 'left', 'top', 'width', 'maxHeight', 'overflow', 'margin']) body.style[property] = '';
    return;
  }
  body.setAttribute('popover', 'manual');
  if (!body.matches(':popover-open')) body.showPopover();
  const summary = menu.querySelector('summary');
  let anchor = summary.getBoundingClientRect();
  // A focused summary can leave the viewport after responsive reflow. Opening
  // its menu must reveal it; only scrolling an already open menu away closes it.
  if (revealAnchor && (anchor.top < 8 || anchor.bottom > window.innerHeight - 8)) {
    summary.scrollIntoView({ block: 'center', behavior: 'instant' });
    anchor = summary.getBoundingClientRect();
  }
  if (anchor.bottom < 0 || anchor.top > window.innerHeight) { menu.open = false; body.hidePopover(); return; }
  const gap = 8, width = Math.min(300, window.innerWidth - gap * 2);
  Object.assign(body.style, { position: 'fixed', inset: 'auto', margin: '0', width: `${width}px`, maxHeight: `${window.innerHeight - gap * 2}px`, overflow: 'auto' });
  const height = body.getBoundingClientRect().height;
  const below = window.innerHeight - anchor.bottom - gap;
  const above = anchor.top - gap;
  const useAbove = height > below && above > below;
  const available = Math.max(44, useAbove ? above : below);
  body.style.maxHeight = `${Math.min(window.innerHeight - gap * 2, available)}px`;
  body.style.left = `${Math.max(gap, Math.min(window.innerWidth - width - gap, anchor.right - width))}px`;
  body.style.top = `${Math.max(gap, Math.min(window.innerHeight - Math.min(height, available) - gap, useAbove ? anchor.top - Math.min(height, available) - 4 : anchor.bottom + 4))}px`;
}
window.addEventListener('resize', () => {
  for (const menu of document.querySelectorAll('.audio-actions[open]')) placeActions(menu, true);
});
window.addEventListener('scroll', event => {
  for (const menu of document.querySelectorAll('.audio-actions[open]')) {
    if (!menu.querySelector('.audio-actions__items').contains(event.target)) placeActions(menu);
  }
}, true);
