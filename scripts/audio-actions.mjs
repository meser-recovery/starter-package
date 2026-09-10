// Native disclosure keeps contextual actions reachable by keyboard and touch.
export function contextActions(label, ...actions) {
  const menu = document.createElement('details'); menu.className = 'audio-actions';
  const summary = document.createElement('summary'); summary.textContent = 'Действия';
  summary.setAttribute('aria-label', `Действия · ${label}`);
  const body = document.createElement('div'); body.className = 'audio-actions__items';
  body.append(...actions); menu.append(summary, body);
  menu.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.open) { event.preventDefault(); event.stopPropagation(); menu.open = false; summary.focus(); }
  });
  body.addEventListener('click', event => {
    if (event.target.closest('button, a') && !event.target.disabled) { menu.open = false; summary.focus(); }
  }, true);
  menu.addEventListener('toggle', () => {
    if (menu.open) for (const other of document.querySelectorAll('.audio-actions[open]')) if (other !== menu) other.open = false;
  });
  return menu;
}
document.addEventListener('click', event => {
  for (const menu of document.querySelectorAll('.audio-actions[open]')) if (!menu.contains(event.target)) menu.open = false;
});
