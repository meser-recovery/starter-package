(() => {
  const LS_KEY = "clean_period_start_date_v4"; // YYYY-MM-DD
  const DEFAULT_START_YMD = "1953-10-05";
  const monthsRu = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
  const $ = (id) => document.getElementById(id);
  const elTotalDays = $("cp-totalDays");
  const elTotalDaysLabel = $("cp-totalDaysLabel");
  const elYears = $("cp-years");
  const elMonths = $("cp-months");
  const elDays = $("cp-days");
  const elLine = $("cp-resultLine");
  const elNote = $("cp-note");
  const modal = $("cp-modal");
  const modalPanel = modal.querySelector(".cp-modal-panel");
  const openBtn = $("cp-openPicker");
  const closeBtn = $("cp-closeModal");
  const closeBackdrop = $("cp-closeBackdrop");
  const saveBtn = $("cp-save");
  const resetBtn = $("cp-reset");
  const wheelDay = $("cp-wheel-day");
  const wheelMonth = $("cp-wheel-month");
  const wheelYear = $("cp-wheel-year");

  function pad2(n) { return String(n).padStart(2, "0"); }
  function todayParts() {
    const t = new Date();
    return { y: t.getFullYear(), m: t.getMonth() + 1, d: t.getDate() };
  }
  function utcFromYMD(ymd) {
    const [y, m, d] = ymd.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d));
  }
  function diffDaysCalendar(startYMD, endYMD) {
    return Math.floor((utcFromYMD(endYMD).getTime() - utcFromYMD(startYMD).getTime()) / 86400000);
  }
  function daysInMonthUTC(year, month1to12) { return new Date(Date.UTC(year, month1to12, 0)).getUTCDate(); }
  function calendarYMDdiff(startYMD, endYMD) {
    const [sy, sm, sd] = startYMD.split("-").map(Number);
    const [ey, em, ed] = endYMD.split("-").map(Number);
    let years = ey - sy;
    let months = em - sm;
    let days = ed - sd;
    if (days < 0) {
      const prevMonth1 = em === 1 ? 12 : em - 1;
      const prevYear = em === 1 ? ey - 1 : ey;
      days += daysInMonthUTC(prevYear, prevMonth1);
      months -= 1;
    }
    if (months < 0) { months += 12; years -= 1; }
    if (years < 0) years = months = days = 0;
    return { years, months, days };
  }
  function pluralRu(n, one, few, many) {
    const mod10 = n % 10;
    const mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 14) return many;
    if (mod10 === 1) return one;
    if (mod10 >= 2 && mod10 <= 4) return few;
    return many;
  }
  function formatLine(parts) {
    const { years, months, days } = parts;
    if (years <= 0 && months <= 0) return `${days} ${pluralRu(days, "день", "дня", "дней")}`;
    if (years <= 0) return `${months} ${pluralRu(months, "месяц", "месяца", "месяцев")} ${days} ${pluralRu(days, "день", "дня", "дней")}`;
    return `${years} ${pluralRu(years, "год", "года", "лет")} ${months} ${pluralRu(months, "месяц", "месяца", "месяцев")} ${days} ${pluralRu(days, "день", "дня", "дней")}`;
  }
  function ymdFromParts(y, m, d) { return `${y}-${pad2(m)}-${pad2(d)}`; }
  function clampToToday(y, m, d) {
    const t = todayParts();
    if (y > t.y) { y = t.y; m = t.m; d = t.d; }
    if (y === t.y && m > t.m) { m = t.m; d = Math.min(d, t.d); }
    if (y === t.y && m === t.m && d > t.d) d = t.d;
    return { y, m, d };
  }
  function normalizeDate(y, m, d) {
    d = Math.min(d, daysInMonthUTC(y, m));
    ({ y, m, d } = clampToToday(y, m, d));
    d = Math.min(d, daysInMonthUTC(y, m));
    return { y, m, d };
  }
  function todayYMD() { const t = todayParts(); return ymdFromParts(t.y, t.m, t.d); }
  function renderFromStart(startYMD) {
    const endYMD = todayYMD();
    const totalDays = diffDaysCalendar(startYMD, endYMD);
    if (totalDays < 0) {
      elTotalDays.textContent = "0";
      elTotalDaysLabel.textContent = "дней";
      elYears.textContent = "0";
      elMonths.textContent = "0";
      elDays.textContent = "0";
      elLine.textContent = "Дата не может быть в будущем";
      elNote.textContent = "";
      return;
    }
    const parts = calendarYMDdiff(startYMD, endYMD);
    elTotalDays.textContent = String(totalDays);
    elTotalDaysLabel.textContent = pluralRu(totalDays, "день", "дня", "дней");
    elYears.textContent = String(parts.years);
    elMonths.textContent = String(parts.months);
    elDays.textContent = String(parts.days);
    elLine.textContent = formatLine(parts);
    elNote.textContent = `До ${endYMD}`;
  }
  function setStartDate(startYMD) { localStorage.setItem(LS_KEY, startYMD); renderFromStart(startYMD); }
  function getItemHeightPx() {
    const item = wheelDay.querySelector(".cp-wheel-item");
    return item ? Math.round(item.getBoundingClientRect().height) || 44 : 44;
  }
  function buildWheel(el, values, renderFn) {
    el.innerHTML = values.map((value) => `<div class="cp-wheel-item" data-value="${value}">${renderFn(value)}</div>`).join("");
    el.querySelectorAll(".cp-wheel-item").forEach((item, index) => item.addEventListener("click", () => {
      snapTo(el, index, true);
      triggerWheelChange(el);
    }));
  }
  function setActiveByIndex(el, idx) { el.querySelectorAll(".cp-wheel-item").forEach((item, index) => item.classList.toggle("is-active", index === idx)); }
  function nearestIndex(el) {
    const max = el.querySelectorAll(".cp-wheel-item").length - 1;
    return Math.max(0, Math.min(max, Math.round(el.scrollTop / getItemHeightPx())));
  }
  function snapTo(el, idx, smooth) {
    const top = idx * getItemHeightPx();
    if (smooth && el.scrollTo) el.scrollTo({ top, behavior: "smooth" });
    else el.scrollTop = top;
    setActiveByIndex(el, idx);
  }
  function setWheelValue(el, value) {
    const items = Array.from(el.querySelectorAll(".cp-wheel-item"));
    const idx = items.findIndex((item) => String(item.dataset.value) === String(value));
    if (idx >= 0) snapTo(el, idx, false);
  }

  let picker = { y: 2000, m: 1, d: 1 };
  function rebuildDays() {
    const days = Array.from({ length: daysInMonthUTC(picker.y, picker.m) }, (_, index) => index + 1);
    buildWheel(wheelDay, days, pad2);
    if (picker.d > days.length) picker.d = days.length;
    requestAnimationFrame(() => setWheelValue(wheelDay, picker.d));
  }
  function triggerWheelChange(el) {
    const idx = nearestIndex(el);
    setActiveByIndex(el, idx);
    const value = el.querySelectorAll(".cp-wheel-item")[idx]?.dataset.value;
    if (value == null) return;
    if (el === wheelYear) {
      picker.y = parseInt(value, 10);
      picker = normalizeDate(picker.y, picker.m, picker.d);
      rebuildDays();
      requestAnimationFrame(() => { setWheelValue(wheelMonth, picker.m); setWheelValue(wheelYear, picker.y); });
    } else if (el === wheelMonth) {
      picker.m = parseInt(value, 10);
      picker = normalizeDate(picker.y, picker.m, picker.d);
      rebuildDays();
      requestAnimationFrame(() => { setWheelValue(wheelMonth, picker.m); setWheelValue(wheelYear, picker.y); });
    } else {
      picker.d = parseInt(value, 10);
      picker = normalizeDate(picker.y, picker.m, picker.d);
      requestAnimationFrame(() => setWheelValue(wheelDay, picker.d));
    }
  }
  function attachWheel(el) {
    let timer = null;
    el.addEventListener("scroll", () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => triggerWheelChange(el), 80);
    }, { passive: true });
  }
  function initWheelsFromYMD(ymd) {
    const [y, m, d] = ymd.split("-").map(Number);
    picker = normalizeDate(y, m, d);
    const years = [];
    for (let year = 1950; year <= todayParts().y; year += 1) years.push(year);
    buildWheel(wheelYear, years, String);
    buildWheel(wheelMonth, Array.from({ length: 12 }, (_, index) => index + 1), (value) => monthsRu[value - 1]);
    rebuildDays();
    requestAnimationFrame(() => { setWheelValue(wheelYear, picker.y); setWheelValue(wheelMonth, picker.m); setWheelValue(wheelDay, picker.d); });
  }
  function openModal() {
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => {
      setWheelValue(wheelYear, picker.y);
      setWheelValue(wheelMonth, picker.m);
      setWheelValue(wheelDay, picker.d);
      closeBtn.focus();
    });
  }
  function closeModal() {
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    openBtn.focus();
  }
  function trapModalFocus(event) {
    if (event.key !== "Tab" || !modal.classList.contains("is-open")) return;
    const focusable = Array.from(modalPanel.querySelectorAll("button, [tabindex]:not([tabindex='-1'])"));
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  openBtn.addEventListener("click", openModal);
  closeBtn.addEventListener("click", closeModal);
  closeBackdrop.addEventListener("click", closeModal);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.classList.contains("is-open")) closeModal();
    trapModalFocus(event);
  });
  resetBtn.addEventListener("click", () => {
    initWheelsFromYMD(DEFAULT_START_YMD);
  });
  saveBtn.addEventListener("click", () => {
    picker = normalizeDate(picker.y, picker.m, picker.d);
    const ymd = ymdFromParts(picker.y, picker.m, picker.d);
    if (diffDaysCalendar(ymd, todayYMD()) < 0) { elLine.textContent = "Дата не может быть в будущем"; return; }
    setStartDate(ymd);
    closeModal();
  });
  [wheelDay, wheelMonth, wheelYear].forEach(attachWheel);
  const saved = localStorage.getItem(LS_KEY);
  const hasSavedDate = Boolean(saved && /^\d{4}-\d{2}-\d{2}$/.test(saved));
  const initial = hasSavedDate ? saved : DEFAULT_START_YMD;
  initWheelsFromYMD(initial);
  if (hasSavedDate) renderFromStart(saved);
})();
