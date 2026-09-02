const PDFJS_MODULE_URL = new URL("../vendor/pdfjs/pdf.legacy.mjs", import.meta.url).href;
const PDFJS_WORKER_URL = new URL("../vendor/pdfjs/pdf.worker.legacy.mjs", import.meta.url).href;

const BROCHURES = Object.freeze({
  ip07: { title: "Зависимый ли я?", file: "documents/literature/ip-07-zavisimyi-li-ya.pdf" },
  ip16: { title: "Новичку", file: "documents/literature/ip-16-novichku.pdf" },
  ip01: { title: "Кто, что, как и почему?", file: "documents/literature/ip-01-kto-chto-kak-i-pochemu.pdf" },
  ip22: { title: "Добро пожаловать в Сообщество Анонимные Наркоманы", file: "documents/literature/ip-22-dobro-pozhalovat.pdf" },
  ip12: { title: "Треугольник одержимости своими желаниями", file: "documents/literature/ip-12-treugolnik-oderzhimosti.pdf" },
  ip13: { title: "Юным зависимым от юных зависимых", file: "documents/literature/ip-13-yunym-zavisimym.pdf" },
});

const ERROR_MESSAGES = Object.freeze({
  "LIT-BOOT": "Не удалось запустить просмотр проспекта.",
  "LIT-WORKER": "Не удалось запустить обработку проспекта.",
  "LIT-FETCH": "Не удалось загрузить проспект.",
  "LIT-PDF": "Не удалось прочитать проспект.",
  "LIT-RENDER": "Не удалось показать страницы проспекта.",
});

const title = document.getElementById("brochure-title");
const status = document.getElementById("reader-status");
const error = document.getElementById("reader-error");
const pages = document.getElementById("brochure-pages");
const documentId = new URLSearchParams(window.location.search).get("doc");
const brochure = BROCHURES[documentId];
let pdfjsLib;
let pdfWorker;
let pdfDocument;
let rerenderTimer;
let renderInProgress = false;
let renderPromise;
let pendingRenderWidth;
let lastSuccessfulRenderWidth;

const WIDTH_CHANGE_TOLERANCE = 1;

function showError(message) {
  status.hidden = true;
  error.textContent = message;
  error.hidden = false;
}

function errorDetails(cause) {
  if (cause instanceof Error) {
    return { name: cause.name || "Error", message: cause.message || "Unknown error" };
  }
  return { name: "Error", message: String(cause) };
}

function logReaderError(stage, cause) {
  const details = errorDetails(cause);
  console.error(`[Literature reader] stage=${stage}; name=${details.name}; message=${details.message}`);
}

function showReaderFailure(stage, code, cause) {
  logReaderError(stage, cause);
  showError(`${ERROR_MESSAGES[code]} Код: ${code}. Вернитесь к списку проспектов и попробуйте ещё раз.`);
}

function pageWidth() {
  return Math.max(1, pages.clientWidth - 16);
}

function widthChanged(nextWidth, previousWidth) {
  return previousWidth === undefined || Math.abs(nextWidth - previousWidth) > WIDTH_CHANGE_TOLERANCE;
}

async function buildRenderedPages(targetWidth) {
  const replacement = document.createDocumentFragment();
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);

  for (let number = 1; number <= pdfDocument.numPages; number += 1) {
    const pdfPage = await pdfDocument.getPage(number);
    const originalViewport = pdfPage.getViewport({ scale: 1 });
    const cssScale = targetWidth / originalViewport.width;
    const cssViewport = pdfPage.getViewport({ scale: cssScale });
    const renderViewport = pdfPage.getViewport({ scale: cssScale * pixelRatio });
    const surface = document.createElement("article");
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d", { alpha: false });

    if (!context) throw new Error("Canvas 2D context is unavailable");
    surface.className = "brochure-page";
    surface.setAttribute("aria-label", `Страница ${number}`);
    canvas.width = Math.ceil(renderViewport.width);
    canvas.height = Math.ceil(renderViewport.height);
    canvas.style.width = `${Math.ceil(cssViewport.width)}px`;
    canvas.style.height = `${Math.ceil(cssViewport.height)}px`;
    surface.append(canvas);
    replacement.append(surface);
    await pdfPage.render({ canvasContext: context, viewport: renderViewport }).promise;
  }

  return replacement;
}

async function processRenderQueue() {
  while (pendingRenderWidth !== undefined) {
    const targetWidth = pendingRenderWidth;
    pendingRenderWidth = undefined;

    if (!widthChanged(targetWidth, lastSuccessfulRenderWidth)) continue;

    try {
      const replacement = await buildRenderedPages(targetWidth);
      if (pendingRenderWidth !== undefined && widthChanged(pendingRenderWidth, targetWidth)) continue;
      pages.replaceChildren(replacement);
      lastSuccessfulRenderWidth = targetWidth;
      status.textContent = `Показано страниц: ${pdfDocument.numPages}`;
    } catch (renderError) {
      if (lastSuccessfulRenderWidth === undefined) throw renderError;
      logReaderError("canvas/render-responsive", renderError);
    }
  }
}

function requestRender(targetWidth) {
  pendingRenderWidth = targetWidth;
  if (!renderInProgress) {
    renderInProgress = true;
    renderPromise = processRenderQueue().finally(() => {
      renderInProgress = false;
      renderPromise = undefined;
    });
  }
  return renderPromise;
}

async function loadPdfRuntime() {
  try {
    pdfjsLib = await import(PDFJS_MODULE_URL);
    pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;
  } catch (bootstrapError) {
    showReaderFailure("bootstrap", "LIT-BOOT", bootstrapError);
    return false;
  }

  try {
    pdfWorker = pdfjsLib.PDFWorker.create({ name: "literature-reader" });
    await pdfWorker.promise;
  } catch (workerError) {
    showReaderFailure("worker-initialization", "LIT-WORKER", workerError);
    return false;
  }

  return true;
}

async function fetchBrochure() {
  try {
    const response = await fetch(brochure.file);
    if (!response.ok) throw new Error(`PDF request failed with status ${response.status}`);
    return await response.arrayBuffer();
  } catch (fetchError) {
    showReaderFailure("pdf-fetch", "LIT-FETCH", fetchError);
    return undefined;
  }
}

async function parseBrochure(data) {
  try {
    pdfDocument = await pdfjsLib.getDocument({ data, worker: pdfWorker }).promise;
    return true;
  } catch (pdfError) {
    showReaderFailure("pdf-parse", "LIT-PDF", pdfError);
    return false;
  }
}

async function loadBrochure() {
  if (!brochure) {
    title.textContent = "Информационный проспект";
    document.title = "Проспект не найден — Проект Мэсэр";
    showError("Этот проспект не найден. Вернитесь к списку и выберите нужный материал.");
    return;
  }

  title.textContent = brochure.title;
  document.title = `${brochure.title} — Проект Мэсэр`;

  if (!await loadPdfRuntime()) return;
  const data = await fetchBrochure();
  if (!data) return;
  if (!await parseBrochure(data)) return;

  try {
    await requestRender(pageWidth());
  } catch (renderError) {
    showReaderFailure("canvas/render", "LIT-RENDER", renderError);
  }
}

window.addEventListener("resize", () => {
  if (!pdfDocument) return;
  const availableWidth = pageWidth();
  if (!widthChanged(availableWidth, lastSuccessfulRenderWidth)) return;
  window.clearTimeout(rerenderTimer);
  rerenderTimer = window.setTimeout(() => {
    requestRender(pageWidth()).catch((renderError) => {
      logReaderError("canvas/render-responsive", renderError);
    });
  }, 150);
});

loadBrochure();
