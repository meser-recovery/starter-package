(() => {
  "use strict";

  const MEETINGS_URL = "na_meetings_live.html";

  document.addEventListener("DOMContentLoaded", async () => {
    const content = document.getElementById("meetings-content");
    const loading = document.getElementById("na-loading");
    const date = document.getElementById("meetings-date");
    const cityFilter = document.getElementById("cityFilter");

    try {
      const response = await fetch(MEETINGS_URL);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const source = await response.text();
      const sourceDocument = new DOMParser().parseFromString(source, "text/html");
      const generatedMeetings = sourceDocument.querySelector(".na-meetings");
      if (!generatedMeetings) throw new Error("Generated meetings root is missing");

      const generatedHeading = generatedMeetings.querySelector("h1");
      const formattedDate = getFormattedDate(generatedHeading?.textContent || "");
      generatedHeading?.remove();
      content.replaceChildren(...Array.from(generatedMeetings.children));

      if (formattedDate) {
        date.textContent = `Расписание собраний на ${formattedDate}`;
        date.hidden = false;
      }

      loading.hidden = true;
      initCityFilter(cityFilter, content);
    } catch (error) {
      console.error("Ошибка загрузки na_meetings_live.html:", error);
      loading.textContent = "Ошибка загрузки данных. Попробуйте позже.";
      loading.classList.add("meetings-error");
      loading.setAttribute("role", "alert");
    }
  });

  function getFormattedDate(text) {
    const match = text.match(/(\d{4})-(\d{2})-(\d{2})/);
    if (!match) return "";

    const [, year, month, day] = match;
    const parsed = new Date(`${year}-${month}-${day}T00:00:00Z`);
    if (Number.isNaN(parsed.getTime()) ||
        parsed.getUTCFullYear() !== Number(year) ||
        parsed.getUTCMonth() + 1 !== Number(month) ||
        parsed.getUTCDate() !== Number(day)) return "";

    return `${day}-${month}-${year}`;
  }

  function initCityFilter(cityFilter, content) {
    const cityBlocks = Array.from(content.querySelectorAll(":scope > h2")).map((heading) => {
      const nodes = [heading];
      let node = heading.nextElementSibling;
      while (node && node.tagName !== "H2") {
        nodes.push(node);
        node = node.nextElementSibling;
      }
      return { name: heading.textContent.trim(), nodes };
    });

    const cityNames = [...new Set(cityBlocks.map(({ name }) => name))]
      .sort((first, second) => first.localeCompare(second, "ru"));
    cityNames.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      cityFilter.appendChild(option);
    });

    const applyFilter = () => {
      const showAll = cityFilter.value === "" || cityFilter.value === "all";
      cityBlocks.forEach(({ name, nodes }) => {
        const visible = showAll || cityFilter.value === name;
        nodes.forEach((node) => { node.hidden = !visible; });
      });
    };

    cityFilter.addEventListener("change", applyFilter);
    applyFilter();
  }
})();
