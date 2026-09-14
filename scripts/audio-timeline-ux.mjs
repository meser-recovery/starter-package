export const TRACK_COLORS = ["#2388bd", "#1c9b7b", "#a56a16", "#8a62b8", "#c24f6e", "#4f7d2d"];

export function defaultTrackColor(index) {
  return TRACK_COLORS[Math.max(0, index) % TRACK_COLORS.length];
}

export function normalizedWheelDelta(event) {
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 800 : 1;
  return Math.max(-240, Math.min(240, event.deltaY * unit));
}

export function zoomFromGesture(pixelsPerSecond, delta) {
  return pixelsPerSecond * Math.exp(-delta * .0045);
}

export function installTimelineZoomGestures(surface, { getZoom, setZoomAt }) {
  let gestureBase = null;
  const anchor = event => {
    const box = surface.getBoundingClientRect();
    const offset = Math.max(0, Math.min(box.width, event.clientX - box.left));
    return { time: (surface.scrollLeft + offset) / getZoom(), offset };
  };
  surface.addEventListener("wheel", event => {
    if (!event.ctrlKey || !event.cancelable) return;
    event.preventDefault();
    const point = anchor(event);
    setZoomAt(zoomFromGesture(getZoom(), normalizedWheelDelta(event)), point.time, point.offset);
  }, { passive: false });
  surface.addEventListener("gesturestart", event => {
    if (!event.cancelable) return;
    event.preventDefault();
    gestureBase = { ...anchor(event), zoom: getZoom() };
  }, { passive: false });
  surface.addEventListener("gesturechange", event => {
    if (!gestureBase || !event.cancelable || !Number.isFinite(event.scale) || event.scale <= 0) return;
    event.preventDefault();
    setZoomAt(gestureBase.zoom * event.scale, gestureBase.time, gestureBase.offset);
  }, { passive: false });
  const clearGesture = () => { gestureBase = null; };
  surface.addEventListener("gestureend", clearGesture);
  surface.addEventListener("gesturecancel", clearGesture);
}

function isNativeControl(target) {
  return target instanceof Element && Boolean(target.closest(
    "input, textarea, select, button, summary, audio, [contenteditable]:not([contenteditable=false]), dialog[open], [role=dialog], [aria-expanded=true]"
  ));
}

export function installSpaceTransport({ workspace, sourceAudio, resultAudio, sourceButton, canHandle }) {
  let context = "source";
  // A pointer click on a studio command should not make Space repeat that
  // command. Tab navigation still gives native buttons their usual Space key.
  let pointerButton = null;
  document.addEventListener("pointerdown", event => {
    pointerButton = event.target instanceof Element ? event.target.closest("button") : null;
    if (pointerButton?.getAttribute("aria-controls") === workspace.id) context = "source";
  }, { capture: true });
  document.addEventListener("focusin", event => {
    if (event.target !== pointerButton) pointerButton = null;
  });
  for (const eventName of ["pointerdown", "focusin"]) workspace.addEventListener(eventName, event => {
    context = resultAudio?.closest("section")?.contains(event.target) ? "result" : "source";
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Tab") pointerButton = null;
    if (event.code !== "Space" || event.repeat || event.isComposing || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const pointerCommand = pointerButton && event.target === pointerButton &&
      (workspace.contains(pointerButton) || pointerButton.getAttribute("aria-controls") === workspace.id) &&
      !pointerButton.disabled && !pointerButton.closest('[aria-expanded="true"], [role="menu"], [role="dialog"], dialog');
    if (workspace.hidden || !workspace.isConnected || !workspace.getClientRects().length ||
        document.querySelector('dialog[open], [role="menu"]:not([hidden])') ||
        (isNativeControl(event.target) && !pointerCommand) || !canHandle()) return;
    event.preventDefault();
    if (context === "result" && resultAudio && resultAudio.getAttribute("src")) {
      if (resultAudio.paused) {
        sourceAudio.pause();
        void resultAudio.play().catch(() => {});
      } else resultAudio.pause();
      return;
    }
    sourceButton?.click();
  }, { capture: true });
}

let expandedWorkspace = null;

function installNativeFullscreen({ workspace, button, captureAnchor, onGeometryChange }) {
  const enterPath = "M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5";
  const exitPath = "M9 3v6H3M15 3v6h6M9 21v-6H3M15 21v-6h6";
  const supported = typeof workspace.requestFullscreen === "function" && typeof document.exitFullscreen === "function";
  let pageScroll = 0, geometryAnchor = NaN;
  const label = expanded => expanded ? "Выйти из полноэкранного режима" : "На весь экран";
  const updateButton = expanded => {
    button.setAttribute("aria-pressed", String(expanded));
    button.setAttribute("aria-label", label(expanded));
    button.title = label(expanded);
    button.querySelector("span").textContent = label(expanded);
    button.querySelector("path")?.setAttribute("d", expanded ? exitPath : enterPath);
  };
  const unavailable = () => {
    button.disabled = true;
    button.setAttribute("aria-disabled", "true");
    button.setAttribute("aria-label", "Полноэкранный режим недоступен");
    button.title = "Полноэкранный режим недоступен";
    button.querySelector("span").textContent = "Полноэкранный режим недоступен";
  };
  if (!supported) {
    unavailable();
    return { setExpanded: () => {}, isExpanded: () => false };
  }
  updateButton(false);
  const refreshGeometry = () => {
    const anchor = geometryAnchor;
    geometryAnchor = NaN;
    requestAnimationFrame(() => requestAnimationFrame(() => onGeometryChange?.(anchor)));
  };
  const sync = () => {
    const expanded = document.fullscreenElement === workspace;
    workspace.classList.toggle("is-expanded", expanded);
    document.body.classList.toggle("has-expanded-editor", expanded);
    updateButton(expanded);
    if (!expanded) window.scrollTo({ top: pageScroll, behavior: "instant" });
    refreshGeometry();
  };
  const setExpanded = async expanded => {
    if (expanded === (document.fullscreenElement === workspace)) return;
    geometryAnchor = captureAnchor?.();
    try {
      if (expanded) { pageScroll = window.scrollY; await workspace.requestFullscreen(); }
      else if (document.fullscreenElement) await document.exitFullscreen();
    } catch {
      workspace.classList.remove("is-expanded");
      document.body.classList.remove("has-expanded-editor");
      unavailable();
      refreshGeometry();
    }
  };
  button.addEventListener("click", () => void setExpanded(document.fullscreenElement !== workspace));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && document.fullscreenElement === workspace) {
      geometryAnchor = captureAnchor?.();
      void document.exitFullscreen();
    }
  }, { capture: true });
  document.addEventListener("fullscreenchange", sync);
  document.addEventListener("fullscreenerror", unavailable);
  new MutationObserver(() => {
    if (workspace.hidden && document.fullscreenElement === workspace) void document.exitFullscreen();
  }).observe(workspace, { attributes: true, attributeFilter: ["hidden"] });
  return { setExpanded, isExpanded: () => document.fullscreenElement === workspace };
}

export function installEditorExpansion({ workspace, button, captureAnchor, onGeometryChange, isGestureActive = () => false, nativeFullscreen = false }) {
  if (nativeFullscreen) return installNativeFullscreen({ workspace, button, captureAnchor, onGeometryChange });
  let pageScroll = 0;
  const setExpanded = expanded => {
    if (expanded === workspace.classList.contains("is-expanded")) return;
    const geometryAnchor = captureAnchor?.();
    if (expandedWorkspace && expandedWorkspace !== workspace) {
      expandedWorkspace.classList.remove("is-expanded");
      expandedWorkspace.querySelector(".editor-expand")?.setAttribute("aria-pressed", "false");
    }
    if (expanded) {
      pageScroll = window.scrollY;
      expandedWorkspace = workspace;
      workspace.classList.add("is-expanded");
      document.body.classList.add("has-expanded-editor");
    } else {
      workspace.classList.remove("is-expanded");
      if (expandedWorkspace === workspace) expandedWorkspace = null;
      if (!expandedWorkspace) document.body.classList.remove("has-expanded-editor");
      window.scrollTo({ top: pageScroll, behavior: "instant" });
    }
    button.setAttribute("aria-pressed", String(expanded));
    button.setAttribute("aria-label", expanded ? "Вернуть обычный вид редактора" : "Развернуть редактор");
    button.title = button.getAttribute("aria-label");
    button.querySelector("span").textContent = expanded ? "Обычный вид" : "Развернуть";
    requestAnimationFrame(() => requestAnimationFrame(() => onGeometryChange?.(geometryAnchor)));
  };
  button.addEventListener("click", () => setExpanded(!workspace.classList.contains("is-expanded")));
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape" || event.defaultPrevented || !workspace.classList.contains("is-expanded")) return;
    if (isGestureActive() || document.querySelector("dialog[open]") || event.target?.matches?.('input[type="color"]') || document.querySelector('[role="menu"]:not([hidden])')) return;
    event.preventDefault();
    setExpanded(false);
    button.focus({ preventScroll: true });
  }, { capture: true });
  new MutationObserver(() => { if (workspace.hidden) setExpanded(false); }).observe(workspace, { attributes: true, attributeFilter: ["hidden"] });
  return { setExpanded, isExpanded: () => workspace.classList.contains("is-expanded") };
}
