import * as pdfjsLib from "../vendor/pdfjs/pdf.mjs";

const BROCHURES = Object.freeze({
  ip07: { title: "Зависимый ли я?", file: "documents/literature/ip-07-zavisimyi-li-ya.pdf" },
  ip16: { title: "Новичку", file: "documents/literature/ip-16-novichku.pdf" },
  ip01: { title: "Кто, что, как и почему?", file: "documents/literature/ip-01-kto-chto-kak-i-pochemu.pdf" },
  ip22: { title: "Добро пожаловать в Сообщество Анонимные Наркоманы", file: "documents/literature/ip-22-dobro-pozhalovat.pdf" },
  ip12: { title: "Треугольник одержимости своими желаниями", file: "documents/literature/ip-12-treugolnik-oderzhimosti.pdf" },
  ip13: { title: "Юным зависимым от юных зависимых", file: "documents/literature/ip-13-yunym-zavisimym.pdf" },
});

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL("../vendor/pdfjs/pdf.worker.mjs", import.meta.url).href;

const title = document.getElementById("brochure-title");
const status = document.getElementById("reader-status");
const error = document.getElementById("reader-error");
const pages = document.getElementById("brochure-pages");
const documentId = new URLSearchParams(window.location.search).get("doc");
const brochure = BROCHURES[documentId];
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
      console.error("Literature reader failed to rerender brochure", renderError);
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

async function loadBrochure() {
  if (!brochure) {
    title.textContent = "Информационный проспект";
    document.title = "Проспект не найден — Проект Мэсэр";
    showError("Этот проспект не найден. Вернитесь к списку и выберите нужный материал.");
    return;
  }

  title.textContent = brochure.title;
  document.title = `${brochure.title} — Проект Мэсэр`;

  try {
    const response = await fetch(brochure.file);
    if (!response.ok) {
      throw new Error(`PDF request failed with status ${response.status}`);
    }
    const data = await response.arrayBuffer();
    pdfDocument = await pdfjsLib.getDocument({ data }).promise;
    await requestRender(pageWidth());
  } catch (loadError) {
    console.error("Literature reader failed to load brochure", loadError);
    showError("Не удалось открыть проспект. Попробуйте ещё раз позже или вернитесь к списку проспектов.");
  }
}

window.addEventListener("resize", () => {
  if (!pdfDocument) return;
  const availableWidth = pageWidth();
  if (!widthChanged(availableWidth, lastSuccessfulRenderWidth)) return;
  window.clearTimeout(rerenderTimer);
  rerenderTimer = window.setTimeout(() => {
    requestRender(pageWidth()).catch((renderError) => {
      console.error("Literature reader failed during resize", renderError);
    });
  }, 150);
});

loadBrochure();
