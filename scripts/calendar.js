(() => {
  const CALENDAR_ID = "meserproject%40gmail.com";
  const MOBILE_QUERY = "(max-width: 640px)";
  const frame = document.getElementById("gc-frame");
  const mediaQuery = window.matchMedia(MOBILE_QUERY);

  function buildCalendarUrl(mode) {
    return "https://calendar.google.com/calendar/embed"
      + "?src=" + CALENDAR_ID
      + "&ctz=Asia%2FJerusalem"
      + "&hl=ru"
      + "&mode=" + mode
      + "&wkst=2"
      + "&showTitle=0"
      + "&showNav=1"
      + "&showDate=1"
      + "&showPrint=0"
      + "&showTabs=1"
      + "&showCalendars=0";
  }

  function applyCalendarMode() {
    if (!frame) return;
    const mode = mediaQuery.matches ? "AGENDA" : "WEEK";
    if (frame.dataset.mode === mode) return;
    frame.dataset.mode = mode;
    frame.src = buildCalendarUrl(mode);
  }

  applyCalendarMode();
  if (mediaQuery.addEventListener) mediaQuery.addEventListener("change", applyCalendarMode);
  else if (mediaQuery.addListener) mediaQuery.addListener(applyCalendarMode);
})();
