// One source transport for either editor. The media element remains the clock;
// its muted flag belongs to a track and is never used as a master mute control.
export function createAudioTransport({ audio, resultAudio, canPlay, seek, reportError }) {
  const doc = audio.ownerDocument;
  const workspace = audio.closest('.speaker-editor, .processor-card');
  workspace?.classList.add('daw-workspace');
  const bar = doc.createElement('div'); bar.className = 'daw-playback';
  bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', 'Прослушивание исходных дорожек');
  const button = (name, path, action) => {
    const node = doc.createElement('button'); node.type = 'button';
    node.setAttribute('aria-label', name); node.title = name;
    const svg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    const shape = doc.createElementNS('http://www.w3.org/2000/svg', 'path');
    shape.setAttribute('d', path); svg.append(shape); node.append(svg);
    node.addEventListener('click', action); bar.append(node); return node;
  };
  const play = button('Воспроизвести исходники', 'M8 5v14l11-7z', async () => {
    if (!canPlay()) return;
    if (!audio.paused) { audio.pause(); return; }
    const source = audio.getAttribute('src');
    try { await audio.play(); } catch {
      if (canPlay() && audio.getAttribute('src') === source) reportError('Не удалось начать прослушивание. Нажмите воспроизведение ещё раз.');
    }
    refresh();
  });
  play.className = 'daw-play'; play.id = `${audio.id}-play`;
  const stop = button('Остановить и вернуться к началу', 'M6 6h12v12H6z', () => {
    if (!canPlay()) return;
    audio.pause(); seek(0); refresh();
  });
  stop.id = `${audio.id}-stop`;
  const volumeLabel = doc.createElement('label'); volumeLabel.className = 'daw-monitor-volume';
  const volumeIcon = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
  volumeIcon.setAttribute('viewBox', '0 0 24 24'); volumeIcon.setAttribute('aria-hidden', 'true');
  const volumePath = doc.createElementNS('http://www.w3.org/2000/svg', 'path');
  volumePath.setAttribute('d', 'M3 9h4l5-4v14l-5-4H3zM16 8q5 4 0 8M19 5q8 7 0 14'); volumeIcon.append(volumePath);
  const text = doc.createElement('span'); text.textContent = 'Уровень прослушивания';
  const volume = doc.createElement('input'); volume.type = 'range'; volume.min = '0'; volume.max = '1'; volume.step = '.05';
  volume.value = String(audio.volume); volume.setAttribute('aria-label', 'Общий уровень прослушивания');
  volume.title = 'Уровень прослушивания всех дорожек. На финальный результат не влияет.';
  volume.addEventListener('input', () => { audio.volume = Math.max(0, Math.min(1, Number(volume.value))); });
  volumeLabel.append(volumeIcon, text, volume); bar.append(volumeLabel);
  volumeLabel.title = volume.title;
  audio.before(bar); audio.controls = false; audio.classList.add('daw-media-clock'); audio.setAttribute('aria-hidden', 'true');
  function refresh() {
    play.disabled = !canPlay(); stop.disabled = !canPlay();
    const playing = !audio.paused && !audio.ended;
    const label = playing ? 'Приостановить исходники' : 'Воспроизвести исходники';
    play.setAttribute('aria-label', label); play.title = label;
    play.dataset.playing = String(playing);
    play.querySelector('path').setAttribute('d', playing ? 'M6 5h4v14H6zM14 5h4v14h-4z' : 'M8 5v14l11-7z');
    volume.value = String(audio.volume);
  }
  for (const event of ['play', 'pause', 'ended', 'emptied', 'loadedmetadata', 'volumechange']) audio.addEventListener(event, refresh);
  if (resultAudio) {
    audio.addEventListener('play', () => resultAudio.pause());
    resultAudio.addEventListener('play', () => audio.pause());
  }
  refresh();
  if (workspace) decorateTransportButtons(workspace);
  return { refresh };
}

function decorateTransportButtons(workspace) {
  const paths = {
    undo: 'M9 5 4 10l5 5M4 10h9a6 6 0 0 1 0 12',
    redo: 'm15 5 5 5-5 5m5-5h-9a6 6 0 0 0 0 12',
    'zoom-out': 'M5 12h14', 'zoom-in': 'M5 12h14M12 5v14',
    'zoom-fit': 'M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5M8 12h8',
    follow: 'M17 3v18M3 12h10m-5-5 5 5-5 5'
  };
  for (const button of workspace.querySelectorAll('.speaker-transport .processor-zoom button, .processor-source-player .processor-zoom button')) {
    const key = Object.keys(paths).find(name => button.id.endsWith(name));
    if (!key) continue;
    const label = button.getAttribute('aria-label') || button.textContent;
    button.setAttribute('aria-label', label); button.title = label;
    const svg = button.ownerDocument.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    const path = button.ownerDocument.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', paths[key]); svg.append(path); button.replaceChildren(svg);
  }
}
