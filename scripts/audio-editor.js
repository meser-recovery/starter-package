(() => {
  "use strict";

  const MANIFEST_URL = "data/edited-audio.json";
  const RELEASE_PREFIX = "/meser-recovery/starter-package/releases/download/";
  const state = { items: [], selectedId: null };

  const isNonEmptyString = (value) => typeof value === "string" && value.trim().length > 0;
  const isIsoTimestamp = (value) => isNonEmptyString(value) &&
    /^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:?\d{2})$/.test(value) && !Number.isNaN(Date.parse(value));
  const isReleaseAssetUrl = (value) => {
    if (!isNonEmptyString(value)) return false;
    try {
      const parsed = new URL(value);
      const remainder = parsed.pathname.slice(RELEASE_PREFIX.length).split("/").filter(Boolean);
      return parsed.protocol === "https:" && parsed.host === "github.com" && !parsed.username && !parsed.password &&
        parsed.pathname.startsWith(RELEASE_PREFIX) && remainder.length >= 2;
    } catch {
      return false;
    }
  };

  const isValidItem = (item) => item && typeof item === "object" && !Array.isArray(item) &&
    isNonEmptyString(item.id) && isNonEmptyString(item.name) && isIsoTimestamp(item.processedAt) &&
    typeof item.durationSeconds === "number" && Number.isFinite(item.durationSeconds) && item.durationSeconds > 0 &&
    isReleaseAssetUrl(item.audioUrl);

  const isValidManifest = (manifest) => {
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest) || manifest.schemaVersion !== 1 ||
        !(manifest.updatedAt === null || isIsoTimestamp(manifest.updatedAt)) || !Array.isArray(manifest.items) ||
        !manifest.items.every(isValidItem)) return false;
    const ids = manifest.items.map((item) => item.id);
    return new Set(ids).size === ids.length;
  };

  const formatDuration = (seconds) => {
    const total = Math.round(seconds);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remaining = total % 60;
    return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}` :
      `${minutes}:${String(remaining).padStart(2, "0")}`;
  };

  const formatDate = (timestamp) => new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit", month: "long", year: "numeric"
  }).format(new Date(timestamp));

  document.addEventListener("DOMContentLoaded", async () => {
    const status = document.getElementById("archive-status");
    const controls = document.getElementById("archive-controls");
    const count = document.getElementById("archive-count");
    const list = document.getElementById("archive-list");
    const search = document.getElementById("archive-search");
    const sort = document.getElementById("archive-sort");
    const audio = document.getElementById("archive-audio");
    const selectedName = document.getElementById("archive-selected-name");

    const setNeutralPlayer = () => {
      state.selectedId = null;
      audio.removeAttribute("src");
      audio.load();
      selectedName.textContent = "Выберите аудио из архива.";
    };

    const visibleItems = () => {
      const query = search.value.trim().toLocaleLowerCase("ru-RU");
      const items = state.items.filter((item) => item.name.toLocaleLowerCase("ru-RU").includes(query));
      return items.sort((left, right) => {
        if (sort.value === "oldest") return Date.parse(left.processedAt) - Date.parse(right.processedAt) || left.name.localeCompare(right.name, "ru");
        if (sort.value === "name") return left.name.localeCompare(right.name, "ru", { sensitivity: "base" });
        return Date.parse(right.processedAt) - Date.parse(left.processedAt) || left.name.localeCompare(right.name, "ru");
      });
    };

    const selectItem = (item, updateUrl) => {
      state.selectedId = item.id;
      audio.src = item.audioUrl;
      audio.load();
      selectedName.textContent = item.name;
      if (updateUrl) {
        const nextUrl = new URL(window.location.href);
        nextUrl.searchParams.set("id", item.id);
        history.replaceState(null, "", nextUrl);
      }
      render();
    };

    const render = () => {
      const items = visibleItems();
      list.replaceChildren();
      count.hidden = false;
      count.textContent = `Найдено: ${items.length}.`;
      if (!items.length) {
        const empty = document.createElement("p");
        empty.className = "archive-empty";
        empty.textContent = search.value.trim() ? "По вашему запросу ничего не найдено." : "Архив пока пуст.";
        list.append(empty);
        return;
      }
      for (const item of items) {
        const card = document.createElement("article");
        card.className = "archive-item";
        const details = document.createElement("div");
        details.className = "archive-item__details";
        const heading = document.createElement("h3");
        heading.textContent = item.name;
        const metadata = document.createElement("p");
        metadata.textContent = `${formatDate(item.processedAt)} · ${formatDuration(item.durationSeconds)}`;
        details.append(heading, metadata);
        const actions = document.createElement("div");
        actions.className = "archive-item__actions";
        const listen = document.createElement("button");
        listen.type = "button";
        listen.textContent = "Слушать";
        listen.setAttribute("aria-pressed", String(state.selectedId === item.id));
        listen.addEventListener("click", () => selectItem(item, true));
        const download = document.createElement("a");
        download.className = "archive-download";
        download.href = item.audioUrl;
        download.textContent = "Скачать";
        actions.append(listen, download);
        card.append(details, actions);
        list.append(card);
      }
    };

    try {
      const response = await fetch(MANIFEST_URL, { cache: "no-store" });
      if (!response.ok) throw new Error("Manifest request failed");
      const manifest = await response.json();
      if (!isValidManifest(manifest)) throw new Error("Manifest schema failed");
      state.items = manifest.items;
      status.textContent = "";
      controls.hidden = !state.items.length;
      const requestedId = new URLSearchParams(window.location.search).get("id");
      const requestedItem = state.items.find((item) => item.id === requestedId);
      if (requestedItem) selectItem(requestedItem, false);
      else setNeutralPlayer();
      render();
      if (!state.items.length) count.hidden = true;
    } catch {
      setNeutralPlayer();
      controls.hidden = true;
      count.hidden = true;
      list.replaceChildren();
      status.textContent = "Не удалось загрузить архив.";
    }

    search.addEventListener("input", render);
    sort.addEventListener("change", render);
  });
})();
