#!/usr/bin/env python3
"""Small browser smoke suite for the public static site."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error, sync_playwright


def url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def click_viewport_link(page, href: str, expected_path: str) -> None:
    """Click a visible, interactable link without relying on DOM position/classes."""
    links = page.locator(f'a[href="{href}"]')
    viewport_height = (page.viewport_size or {}).get("height", 900)
    for index in range(links.count()):
        candidate = links.nth(index)
        try:
            candidate.wait_for(state="visible", timeout=1000)
        except Error:
            continue
        box = candidate.bounding_box()
        if box and box["y"] < viewport_height and box["y"] + box["height"] > 0:
            try:
                candidate.click(timeout=750)
                page.wait_for_url(f"**{expected_path}", timeout=1500)
                return
            except Error:
                continue
    raise AssertionError(f"no visible in-viewport link found for {href}")


LITERATURE_ACTIONS = (
    ("Зависимый ли я?", "Literature-reader.html?doc=ip07", "Зависимый ли я?"),
    ("Новичку", "Literature-reader.html?doc=ip16", "Новичку"),
    ("Кто, что, как и почему", "Literature-reader.html?doc=ip01", "Кто, что, как и почему?"),
    ("Добро пожаловать в Сообщество АН", "Literature-reader.html?doc=ip22", "Добро пожаловать в Сообщество Анонимные Наркоманы"),
    ("Треугольник одержимости", "Literature-reader.html?doc=ip12", "Треугольник одержимости своими желаниями"),
    ("Юным зависимым от юных зависимых", "Literature-reader.html?doc=ip13", "Юным зависимым от юных зависимых"),
    ("Дополнительная литература", "https://na-russia.org/literatures?category=recovery-literature", None),
)

HOMEPAGE_ACTION_ORDER = (
    "Онлайн собрания", "Живые собрания", "Информационные проспекты", "Базовый текст (аудио)",
    "Ежедневные размышления", "Радио NA", "Слушать спикерские NA", "Калькулятор чистого периода",
)


def visible_text(locator) -> str:
    return locator.evaluate("""element => Array.from(element.childNodes)
        .filter(node => node.nodeType === Node.TEXT_NODE)
        .map(node => node.textContent)
        .join(\"\").trim()""")


def check_literature(page, base_url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(url(base_url, "/Literature.html"), wait_until="domcontentloaded")
    page.wait_for_function("getComputedStyle(document.body).display === 'flex'")
    if not page.evaluate("document.body.scrollHeight >= window.innerHeight"):
        raise AssertionError(f"Literature does not fill the viewport at {width}px")
    if page.locator("html").get_attribute("lang") != "ru":
        raise AssertionError("Literature must use Russian document language")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Информационные проспекты":
        raise AssertionError("Literature must retain one correct H1")
    if page.locator("main#main-content").count() != 1:
        raise AssertionError("Literature main landmark is missing")
    if page.locator('a[href="#main-content"]').count() != 1:
        raise AssertionError("Literature skip link is missing")
    if page.locator(".site-header__identity").count() != 1 or page.locator(".site-header__logo").count() != 1:
        raise AssertionError("Literature shared home navigation is missing")
    if page.locator('a.service-link[href="Admin-panel.html"]').count() != 1:
        raise AssertionError("Literature service control is missing")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Literature has horizontal overflow at {width}px")
    actions = page.locator("a.literature-action")
    if actions.count() != len(LITERATURE_ACTIONS):
        raise AssertionError("Literature must retain seven resource actions")
    for index, (label, href, _title) in enumerate(LITERATURE_ACTIONS):
        action = actions.nth(index)
        if visible_text(action) != label or action.get_attribute("href") != href:
            raise AssertionError(f"Literature action {index + 1} label or href changed")
        if index < 6 and action.get_attribute("target") is not None:
            raise AssertionError(f"Literature action {index + 1} must stay in the same tab")
        if index == 6 and (action.get_attribute("target") != "_blank" or not {"noopener", "noreferrer"}.issubset(set((action.get_attribute("rel") or "").split()))):
            raise AssertionError("Literature final action lacks safe external-link semantics")
        if not action.evaluate("element => element.tagName === 'A' && element.tabIndex >= 0"):
            raise AssertionError(f"Literature action {index + 1} is not keyboard accessible")
        action.focus()
        if not action.evaluate("element => document.activeElement === element"):
            raise AssertionError(f"Literature action {index + 1} cannot receive keyboard focus")
        if action.evaluate("element => element.scrollWidth > element.clientWidth"):
            raise AssertionError(f"Literature action {index + 1} label is clipped at {width}px")
    if width >= 768:
        grid_box = page.locator(".literature-grid").bounding_box()
        first_box = actions.nth(0).bounding_box()
        last_box = actions.nth(-1).bounding_box()
        if not grid_box or not first_box or not last_box:
            raise AssertionError(f"Literature action layout boxes missing at {width}px")
        if abs(last_box["width"] - first_box["width"]) > 1 or abs((last_box["x"] + last_box["width"] / 2) - (grid_box["x"] + grid_box["width"] / 2)) > 1 or last_box["y"] <= first_box["y"]:
            raise AssertionError(f"Literature final action is not centered at normal width at {width}px")


def check_literature_reader(page, base_url: str, document_id: str, expected_title: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(url(base_url, f"/Literature-reader.html?doc={document_id}"), wait_until="domcontentloaded")
    page.locator(".brochure-page canvas").nth(0).wait_for(state="visible", timeout=20000)
    page.wait_for_function("document.getElementById('reader-status').textContent.includes('Показано страниц:')", timeout=30000)
    if ".pdf" in urlparse(page.url).path or not urlparse(page.url).path.endswith("/Literature-reader.html"):
        raise AssertionError(f"Literature reader navigated to a PDF for {document_id}")
    if page.locator("html").get_attribute("lang") != "ru" or page.locator("h1").count() != 1:
        raise AssertionError(f"Literature reader shell is invalid for {document_id}")
    if page.locator("h1").inner_text() != expected_title:
        raise AssertionError(f"Literature reader title is wrong for {document_id}")
    if page.locator('a[href="Literature.html"]').count() != 1:
        raise AssertionError(f"Literature reader back link is missing for {document_id}")
    if page.locator(".reader-error").is_visible():
        raise AssertionError(f"Literature reader showed an error for {document_id}")
    if page.locator(".brochure-page canvas").count() < 1:
        raise AssertionError(f"Literature reader did not render a page for {document_id}")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Literature reader has horizontal overflow for {document_id} at {width}px")
    if not page.evaluate("performance.getEntriesByType('resource').some(entry => new URL(entry.name).pathname.includes('/documents/literature/'))"):
        raise AssertionError(f"Literature reader did not request a local PDF for {document_id}")


def check_literature_reader_error(page, base_url: str) -> None:
    page.set_viewport_size({"width": 390, "height": 900})
    page.goto(url(base_url, "/Literature-reader.html?doc=unknown"), wait_until="domcontentloaded")
    page.locator(".reader-error").wait_for(state="visible")
    if page.locator(".brochure-page canvas").count() != 0 or ".pdf" in urlparse(page.url).path:
        raise AssertionError("Unknown literature route is not handled safely")


def capture_screenshots(page, base_url: str, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    captures = (
        ("homepage-390.png", "/", 390),
        ("homepage-1280.png", "/", 1280),
        ("literature-390.png", "/Literature.html", 390),
        ("literature-1280.png", "/Literature.html", 1280),
        ("literature-reader-ip07-390.png", "/Literature-reader.html?doc=ip07", 390),
        ("literature-reader-ip07-1280.png", "/Literature-reader.html?doc=ip07", 1280),
        ("literature-reader-ip16-390.png", "/Literature-reader.html?doc=ip16", 390),
    )
    for filename, path, width in captures:
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(url(base_url, path), wait_until="domcontentloaded")
        if "Literature-reader" in path:
            page.locator(".brochure-page canvas").nth(0).wait_for(state="visible", timeout=20000)
            page.wait_for_function("document.getElementById('reader-status').textContent.includes('Показано страниц:')", timeout=30000)
        page.screenshot(path=str(directory / filename), full_page=False)


def check_audiobook(page, base_url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(url(base_url, "/AudioBook.html"), wait_until="domcontentloaded")
    page.wait_for_function("getComputedStyle(document.body).display === 'flex'")
    if not page.evaluate("document.body.scrollHeight >= window.innerHeight"):
        raise AssertionError(f"AudioBook does not fill the viewport at {width}px")
    if page.locator("html").get_attribute("lang") != "ru":
        raise AssertionError("AudioBook must use Russian document language")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Базовый текст (аудио)":
        raise AssertionError("AudioBook must retain one correct outer H1")
    if page.locator("main#main-content").count() != 1:
        raise AssertionError("AudioBook main landmark is missing")
    if page.locator('a[href="#main-content"]').count() != 1:
        raise AssertionError("AudioBook skip link is missing")
    if page.locator(".site-header__identity").count() != 1 or page.locator(".site-header__logo").count() != 1:
        raise AssertionError("AudioBook shared home navigation is missing")
    service = page.locator('a.service-link[href="Admin-panel.html"]')
    if service.count() != 1:
        raise AssertionError("AudioBook service control is missing")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"AudioBook has horizontal overflow at {width}px")
    frame_element = page.locator('iframe[src="bt6-player.html"]')
    if frame_element.count() != 1 or not (frame_element.get_attribute("title") or "").strip():
        raise AssertionError("AudioBook must retain one titled local player iframe")
    frame_box = frame_element.bounding_box()
    embed_box = page.locator(".audiobook-embed").bounding_box()
    identity_box = page.locator(".site-header__identity").bounding_box()
    service_box = service.bounding_box()
    if not frame_box or not embed_box or not identity_box or not service_box:
        raise AssertionError(f"AudioBook layout controls missing at {width}px")
    if abs((frame_box["x"] + frame_box["width"] / 2) - (embed_box["x"] + embed_box["width"] / 2)) > 1:
        raise AssertionError(f"AudioBook player is not centered at {width}px")
    if (identity_box["x"] < service_box["x"] + service_box["width"] and
            service_box["x"] < identity_box["x"] + identity_box["width"] and
            identity_box["y"] < service_box["y"] + service_box["height"] and
            service_box["y"] < identity_box["y"] + identity_box["height"]):
        raise AssertionError(f"AudioBook header identity overlaps service control at {width}px")
    frame = page.frame_locator('iframe[src="bt6-player.html"]')
    frame.locator("#playlist li").nth(0).wait_for(timeout=10000)
    frame.locator("#audio").wait_for(state="visible")
    frame.locator(".player-wrap").wait_for(state="visible")
    if not frame.locator("#playlist").is_visible():
        raise AssertionError(f"AudioBook playlist is not visible at {width}px")
    if not frame.locator("html").evaluate("document.documentElement.scrollWidth <= window.innerWidth"):
        raise AssertionError(f"AudioBook iframe content has horizontal clipping at {width}px")
    if not frame.locator("html").evaluate("document.documentElement.scrollHeight <= window.innerHeight"):
        raise AssertionError(f"AudioBook iframe is too short for its player content at {width}px")
    content_height = frame.locator("body").evaluate("""() => {
        const player = document.querySelector('.player-wrap');
        if (!player) return 0;
        const styles = getComputedStyle(player);
        return player.getBoundingClientRect().bottom + parseFloat(styles.marginBottom);
    }""")
    frame_height = frame.locator("html").evaluate("window.innerHeight")
    if not content_height or frame_height < content_height or frame_height - content_height > 48:
        raise AssertionError(f"AudioBook iframe has excessive unused height at {width}px")


def check_offline_meetings(page, base_url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(url(base_url, "/Offline-meetings.html"), wait_until="domcontentloaded")
    page.wait_for_function("""() => {
        const loading = document.getElementById('na-loading');
        const select = document.getElementById('cityFilter');
        return loading && loading.hidden && select && select.options.length > 2;
    }""", timeout=15000)
    if page.locator("html").get_attribute("lang") != "ru":
        raise AssertionError("Offline Meetings must use Russian document language")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Живые группы АН - Россия":
        raise AssertionError("Offline Meetings must retain exactly one outer H1")
    if page.locator("main#main-content").count() != 1 or page.locator('a[href="#main-content"]').count() != 1:
        raise AssertionError("Offline Meetings main landmark or skip link is missing")
    if page.locator(".site-header__identity").count() != 1 or page.locator(".site-header__logo").count() != 1:
        raise AssertionError("Offline Meetings shared home navigation is missing")
    if page.locator('a.service-link[href="Admin-panel.html"]').count() != 1:
        raise AssertionError("Offline Meetings service control is missing")
    if not page.locator("body").evaluate("element => getComputedStyle(element).display === 'flex' && element.scrollHeight >= window.innerHeight"):
        raise AssertionError(f"Offline Meetings shared full-height shell is missing at {width}px")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Offline Meetings has horizontal overflow at {width}px")
    if page.locator('script[src="scripts/offline-meetings.js"]').count() != 1:
        raise AssertionError("Offline Meetings dedicated runtime is missing")
    if page.evaluate("document.documentElement.innerHTML.toLowerCase().includes('nicepage') || document.documentElement.innerHTML.toLowerCase().includes('jquery')"):
        raise AssertionError("Offline Meetings retains a Nicepage or jQuery dependency")
    if not page.evaluate("performance.getEntriesByType('resource').some(entry => new URL(entry.name).pathname.endsWith('/na_meetings_live.html'))"):
        raise AssertionError("Offline Meetings did not fetch its generated source")
    source_date = page.evaluate("""async () => {
        const source = await fetch('na_meetings_live.html').then(response => response.text());
        const heading = new DOMParser().parseFromString(source, 'text/html').querySelector('.na-meetings h1');
        const match = (heading?.textContent || '').match(/(\\d{4})-(\\d{2})-(\\d{2})/);
        return match ? `${match[3]}-${match[2]}-${match[1]}` : '';
    }""")
    subtitle = page.locator("#meetings-date")
    if source_date and (subtitle.is_hidden() or subtitle.inner_text() != f"Расписание собраний на {source_date}"):
        raise AssertionError("Offline Meetings date subtitle does not match the generated source")
    city_filter = page.locator("#cityFilter")
    city_blocks = page.locator("#meetings-content > h2")
    if city_blocks.count() < 2:
        raise AssertionError("Offline Meetings did not render generated city headings")
    if city_blocks.evaluate_all("headings => headings.filter(heading => !heading.hidden).length") < 2:
        raise AssertionError("Offline Meetings does not initially show all city blocks")
    selected_city = city_filter.locator("option").nth(2).get_attribute("value")
    if not selected_city:
        raise AssertionError("Offline Meetings city names were not dynamically populated")
    city_filter.select_option(selected_city)
    if city_blocks.filter(has_text=selected_city).count() != 1 or not city_blocks.filter(has_text=selected_city).is_visible():
        raise AssertionError("Offline Meetings selected city is not visible")
    if city_blocks.evaluate_all("headings => headings.filter(heading => !heading.hidden).length") != 1:
        raise AssertionError("Offline Meetings city filter did not hide other city blocks")
    city_filter.select_option("all")
    if city_blocks.evaluate_all("headings => headings.filter(heading => !heading.hidden).length") < 2:
        raise AssertionError("Offline Meetings all-cities option did not restore city blocks")
    if page.locator("footer.site-footer").count() != 1:
        raise AssertionError("Offline Meetings shared footer is missing")


def check_offline_meetings_failure(browser, base_url: str) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 900})
    context.route("**/na_meetings_live.html", lambda route: route.abort())
    page = context.new_page()
    page.goto(url(base_url, "/Offline-meetings.html"), wait_until="domcontentloaded")
    error = page.locator("#na-loading")
    error.wait_for(state="visible")
    page.wait_for_function("document.getElementById('na-loading').textContent.includes('Ошибка загрузки данных')")
    if error.inner_text() != "Ошибка загрузки данных. Попробуйте позже.":
        raise AssertionError("Offline Meetings fetch failure does not show the expected Russian error")
    context.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--screenshot-dir", type=Path)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    site_host = urlparse(base_url).netloc
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})

        def block_external(route):
            if urlparse(route.request.url).netloc not in {"", site_host}:
                route.abort()
            else:
                route.continue_()

        context.route("**/*", block_external)
        page = context.new_page()
        page.goto(url(base_url, "/"), wait_until="domcontentloaded")
        homepage_destinations = (
            "Offline-meetings.html", "Literature.html", "AudioBook.html",
            "Calculator.html", "Admin-panel.html",
            "https://na-tranzit.org/gruppy/onlajn-gruppy",
            "https://na-russia.org/meditation-today", "https://radio-na.ru/",
            "https://nam-poputi.ucoz.ru/load/audio_vystuplenija_anonimnykh/polnyj_spisok_perevedjonnykh_spikerskikh_s_ivrita/11-1-0-751",
        )
        for href in homepage_destinations:
            if page.locator(f'a[href="{href}"]').count() != 1:
                raise AssertionError(f"homepage destination must appear exactly once: {href}")
        if page.locator("h1").count() != 1:
            raise AssertionError("homepage must contain exactly one H1")
        page.get_by_role("heading", name="Проект Мэсэр", level=1).wait_for()
        if page.locator('a[href="#main-content"]').count() != 1:
            raise AssertionError("homepage skip link is missing")
        if page.locator('a[href="Admin-panel.html"]').count() != 1:
            raise AssertionError("desktop service navigation link is missing or duplicated")
        desktop_service = page.get_by_role("link", name="Для служащих")
        desktop_heading_box = page.get_by_role("heading", name="Проект Мэсэр", level=1).bounding_box()
        desktop_header_box = page.locator(".site-header__content").bounding_box()
        if (not desktop_heading_box or not desktop_header_box or
                abs((desktop_heading_box["x"] + desktop_heading_box["width"] / 2) -
                    (desktop_header_box["x"] + desktop_header_box["width"] / 2)) > 1):
            raise AssertionError("desktop H1 is no longer centered in the header")
        if not desktop_service.evaluate("""el => {
            const style = getComputedStyle(el);
            return style.flexDirection === 'row' && style.whiteSpace === 'nowrap' &&
                style.textDecorationLine === 'none' && style.backgroundColor !== 'rgba(0, 0, 0, 0)';
        }"""):
            raise AssertionError("desktop service control lacks its compact control treatment")
        desktop_actions = page.locator(".resource-action")
        if desktop_actions.count() != 8:
            raise AssertionError("desktop homepage must retain eight resource actions")
        if [visible_text(desktop_actions.nth(index)) for index in range(desktop_actions.count())] != list(HOMEPAGE_ACTION_ORDER):
            raise AssertionError("homepage resource actions are not in canonical DOM order")
        if not desktop_actions.nth(0).evaluate("""el => {
            const style = getComputedStyle(el);
            return style.minHeight === '92px' && style.borderRadius === '17px' &&
                style.transitionDuration.split(', ').every(duration => duration === '0.18s');
        }"""):
            raise AssertionError("desktop resource action treatment is not the compact refined style")
        newcomer_heading = page.get_by_role("heading", name="Кто такой зависимый?", level=2)
        heading_box = newcomer_heading.bounding_box()
        if not heading_box or heading_box["y"] >= 900:
            raise AssertionError("newcomer content begins below the initial desktop viewport")
        click_viewport_link(page, "Offline-meetings.html", "/Offline-meetings.html")

        mobile = context.new_page()
        for width in (320, 390):
            mobile.set_viewport_size({"width": width, "height": 844})
            mobile.goto(url(base_url, "/"), wait_until="domcontentloaded")
            if mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                raise AssertionError(f"homepage has horizontal overflow at {width}px")
            mobile.get_by_role("heading", name="Проект Мэсэр", level=1).wait_for(state="visible")
            service = mobile.locator('a[href="Admin-panel.html"]')
            service.wait_for(state="visible")
            heading_box = mobile.get_by_role("heading", name="Проект Мэсэр", level=1).bounding_box()
            service_box = service.bounding_box()
            if not heading_box or not service_box:
                raise AssertionError(f"header controls missing at {width}px")
            if (heading_box["x"] < service_box["x"] + service_box["width"] and
                    service_box["x"] < heading_box["x"] + heading_box["width"] and
                    heading_box["y"] < service_box["y"] + service_box["height"] and
                    service_box["y"] < heading_box["y"] + heading_box["height"]):
                raise AssertionError(f"header H1 and service link overlap at {width}px")
            horizontal_gap = service_box["x"] - (heading_box["x"] + heading_box["width"])
            if horizontal_gap < 4:
                raise AssertionError(f"header H1 and service link gap is too small at {width}px: {horizontal_gap}px")
            if service.locator("span").count() != 2 or [service.locator("span").nth(i).inner_text() for i in range(2)] != ["Для", "служащих"]:
                raise AssertionError(f"service link does not have the required two lines at {width}px")
            line_boxes = [service.locator("span").nth(i).bounding_box() for i in range(2)]
            if not line_boxes[0] or not line_boxes[1] or line_boxes[1]["y"] <= line_boxes[0]["y"]:
                raise AssertionError(f"service link lines are not stacked at {width}px")
            control_center = service_box["x"] + service_box["width"] / 2
            if any(abs((line["x"] + line["width"] / 2) - control_center) > 2 for line in line_boxes):
                raise AssertionError(f"service link lines are not centered in the control at {width}px")
            if not service.evaluate("el => getComputedStyle(el).whiteSpace === 'nowrap' && el.scrollWidth <= el.clientWidth"):
                raise AssertionError(f"header service link wraps unexpectedly at {width}px")
            if abs(heading_box["y"] - service_box["y"]) > max(heading_box["height"], service_box["height"]):
                raise AssertionError(f"header controls are not in the same row at {width}px")
            header_box = mobile.locator(".site-header__content").bounding_box()
            if not header_box or abs((heading_box["x"] + heading_box["width"] / 2) - (header_box["x"] + header_box["width"] / 2)) > 20:
                raise AssertionError(f"H1 is not centered in the mobile header at {width}px")
            if not mobile.evaluate("""() => {
                const columns = getComputedStyle(document.querySelector('.site-header__content')).gridTemplateColumns.split(' ');
                return columns.length === 3 && Math.abs(parseFloat(columns[0]) - parseFloat(columns[2])) <= 1;
            }"""):
                raise AssertionError(f"mobile header side tracks are not symmetric at {width}px")
            if not header_box or header_box["height"] > 96:
                raise AssertionError(f"mobile header is too tall at {width}px")
        if mobile.locator('a[href="Literature.html"]').count() != 1:
            raise AssertionError("homepage Literature destination must appear exactly once")
        mobile.locator('a[href="Literature.html"]').click()
        mobile.wait_for_url("**/Literature.html", timeout=1500)
        mobile.close()

        for width in (320, 390, 768, 1280):
            check_literature(page, base_url, width)
        for label, href, reader_title in LITERATURE_ACTIONS[:6]:
            document_id = href.split("doc=", 1)[1]
            check_literature_reader(page, base_url, document_id, reader_title, 390)
        for document_id, reader_title in (("ip07", "Зависимый ли я?"),):
            for width in (320, 768, 1280):
                check_literature_reader(page, base_url, document_id, reader_title, width)
        check_literature_reader_error(page, base_url)
        for width in (320, 390, 768, 1280):
            check_audiobook(page, base_url, width)
        click_viewport_link(page, "./", "/")
        page.goto(url(base_url, "/Literature.html"), wait_until="domcontentloaded")
        click_viewport_link(page, "Admin-panel.html", "/Admin-panel.html")

        page.goto(url(base_url, "/About.html"), wait_until="domcontentloaded")
        page.wait_for_url(base_url + "/", timeout=10000)

        for width in (320, 390, 768, 1280):
            check_offline_meetings(page, base_url, width)
        check_offline_meetings_failure(browser, base_url)

        page.goto(url(base_url, "/Calculator.html"), wait_until="domcontentloaded")
        page.locator("#cp-openPicker").click()
        page.locator("#cp-today").click()
        page.locator("#cp-save").click()
        if page.locator("#cp-totalDays").inner_text() != "0":
            raise AssertionError("today must produce zero elapsed days")
        saved_date = page.evaluate("localStorage.getItem('clean_period_start_date_v4')")
        page.reload(wait_until="domcontentloaded")
        if page.evaluate("localStorage.getItem('clean_period_start_date_v4')") != saved_date:
            raise AssertionError("calculator date did not persist in localStorage")

        page.goto(url(base_url, "/AudioBook.html"), wait_until="domcontentloaded")
        frame = page.frame_locator('iframe[src="bt6-player.html"]')
        frame.locator("#playlist li").nth(1).wait_for(timeout=10000)
        frame.locator("#playlist li").nth(1).click()
        source = frame.locator("#audio").get_attribute("src")
        if not source or not source.endswith("audio/bt6/bt6_002.mp3"):
            raise AssertionError(f"second audio track did not set expected source: {source}")

        page.goto(url(base_url, "/Admin-panel.html"), wait_until="domcontentloaded")
        password = page.locator('input[type="password"]')
        password.fill("stage-1-invalid-password")
        page.locator('form a[href="#"]:visible').click()
        page.wait_for_timeout(250)
        if "Admin-panel.html" not in urlparse(page.url).path or "5ab2b48b" in page.url:
            raise AssertionError("invalid admin password granted access")

        page.goto(url(base_url, "/Calendar.html"), wait_until="domcontentloaded")
        calendar = page.locator("#gc-frame")
        calendar.wait_for()
        if "mode=WEEK" not in (calendar.get_attribute("src") or ""):
            raise AssertionError("desktop calendar URL did not initialize WEEK mode")
        calendar_page = context.new_page()
        calendar_page.set_viewport_size({"width": 390, "height": 844})
        calendar_page.goto(url(base_url, "/Calendar.html"), wait_until="domcontentloaded")
        if "mode=AGENDA" not in (calendar_page.locator("#gc-frame").get_attribute("src") or ""):
            raise AssertionError("mobile calendar URL did not initialize AGENDA mode")
        calendar_page.close()

        page.goto(url(base_url, "/Google-Drive.html"), wait_until="domcontentloaded")
        drive_src = page.locator("#gd-frame").get_attribute("src") or ""
        drive_open = page.locator("#gd-open-btn").get_attribute("href") or ""
        if "drive.google.com/embeddedfolderview?id=" not in drive_src:
            raise AssertionError("Drive embed URL did not initialize")
        if not drive_open.startswith("https://accounts.google.com/AccountChooser?continue="):
            raise AssertionError("Drive account chooser URL did not initialize")
        if args.screenshot_dir:
            capture_screenshots(page, base_url, args.screenshot_dir)
        context.close()
        browser.close()
    print("Browser smoke suite passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, Error) as exc:
        print(f"BROWSER SMOKE FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
