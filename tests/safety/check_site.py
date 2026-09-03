#!/usr/bin/env python3
"""Validate the repository's stable public-site contract and local resources."""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name("site-contract.json")
FILE_ATTRIBUTES = {
    "a": ("href",), "link": ("href",), "script": ("src",), "img": ("src",),
    "iframe": ("src",), "audio": ("src",), "video": ("src",), "source": ("src",),
}
IGNORED_SCHEMES = {"", "http", "https"}
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, str, str]] = []
        self.anchors: set[str] = set()
        self.start_tags: list[tuple[str, dict[str, str | None]]] = []
        self.h1_texts: list[str] = []
        self._h1_depth = 0
        self._current_h1: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.start_tags.append((tag, values))
        if tag == "h1":
            self._h1_depth += 1
            self._current_h1 = []
        anchor = values.get("id") or values.get("name")
        if anchor:
            self.anchors.add(anchor)
        for attribute in FILE_ATTRIBUTES.get(tag, ()):
            value = values.get(attribute)
            if value is not None:
                self.references.append((tag, attribute, value))

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._h1_depth:
            self.h1_texts.append("".join(self._current_h1).strip())
            self._h1_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._h1_depth:
            self._current_h1.append(data)


def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def normalize_local_path(reference: str, containing_file: Path) -> tuple[Path | None, str | None]:
    parsed = urlparse(reference)
    if parsed.scheme and parsed.scheme not in IGNORED_SCHEMES:
        return None, None
    if parsed.scheme in {"http", "https"} or parsed.netloc:
        return None, None
    path = parsed.path
    if not path:
        return containing_file, parsed.fragment or None
    target = (ROOT / path.lstrip("/")) if path.startswith("/") else (containing_file.parent / path)
    target = target.resolve()
    if target.is_dir():
        target = target / "index.html"
    return target, parsed.fragment or None


def is_optional(target: Path, contract: dict) -> bool:
    try:
        relative = target.relative_to(ROOT).as_posix()
    except ValueError:
        return False
    return relative in contract.get("optional_missing_assets", [])


def validate_url_syntax(value: str, source: Path, errors: list[str]) -> None:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        errors.append(f"{source.relative_to(ROOT)}: malformed external URL: {value}")


def parse_page(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    parser.close()
    return parser


def check_reference(reference: str, source: Path, contract: dict, errors: list[str], warnings: list[str], parser_cache: dict[Path, PageParser]) -> None:
    if reference == "#":
        return
    validate_url_syntax(reference, source, errors)
    target, fragment = normalize_local_path(reference, source)
    if target is None:
        return
    if not target.exists() or not target.is_file():
        message = f"{source.relative_to(ROOT)}: missing local reference {reference}"
        (warnings if is_optional(target, contract) else errors).append(message)
        return
    if fragment:
        target_parser = parser_cache.setdefault(target, parse_page(target))
        if fragment not in target_parser.anchors:
            errors.append(f"{source.relative_to(ROOT)}: missing anchor #{fragment} in {target.relative_to(ROOT)}")


def check_css_references(path: Path, contract: dict, errors: list[str], warnings: list[str]) -> None:
    for match in CSS_URL_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
        value = match.group(2).strip()
        if not value or value.startswith("data:") or value.startswith("#"):
            continue
        check_reference(value, path, contract, errors, warnings, {})


def check_literature_contract(errors: list[str]) -> None:
    literature = ROOT / "Literature.html"
    if not literature.is_file():
        return
    source = literature.read_text(encoding="utf-8", errors="replace")
    parser = parse_page(literature)
    html_attrs = next((attrs for tag, attrs in parser.start_tags if tag == "html"), {})
    if html_attrs.get("lang") != "ru":
        errors.append("Literature.html: html lang must be ru")
    if parser.h1_texts != ["Информационные проспекты"]:
        errors.append("Literature.html: expected one H1: Информационные проспекты")
    if not any(tag == "main" and attrs.get("id") == "main-content" for tag, attrs in parser.start_tags):
        errors.append("Literature.html: main#main-content is missing")
    if not any(tag == "a" and attrs.get("href") == "#main-content" for tag, attrs in parser.start_tags):
        errors.append("Literature.html: skip link is missing")
    lowered = source.lower()
    if "nicepage" in lowered or "jquery" in lowered:
        errors.append("Literature.html: Nicepage or jQuery dependency remains")
    actions = [
        attrs for tag, attrs in parser.start_tags
        if tag == "a" and "literature-action" in (attrs.get("class") or "").split()
    ]
    expected_actions = [
        "Literature-reader.html?doc=ip07", "Literature-reader.html?doc=ip16",
        "Literature-reader.html?doc=ip01", "Literature-reader.html?doc=ip22",
        "Literature-reader.html?doc=ip12", "Literature-reader.html?doc=ip13",
        "https://na-russia.org/literatures?category=recovery-literature",
    ]
    action_hrefs = [attrs.get("href") for attrs in actions]
    if action_hrefs != expected_actions:
        errors.append("Literature.html: resource action destinations changed or are out of order")
    if len(actions) != len(expected_actions):
        errors.append("Literature.html: expected seven resource actions")
    for index, attrs in enumerate(actions[:6]):
        href = attrs.get("href") or ""
        if not href.startswith("Literature-reader.html?doc=") or href.lower().endswith(".pdf"):
            errors.append(f"Literature.html: action {index + 1} must use an internal reader route")
        if attrs.get("target") is not None:
            errors.append(f"Literature.html: action {index + 1} must not open a new tab")
    if len(actions) == 7:
        last = actions[-1]
        if last.get("target") != "_blank" or not {"noopener", "noreferrer"}.issubset(set((last.get("rel") or "").split())):
            errors.append("Literature.html: external final action lacks safe new-tab semantics")


def check_literature_reader_contract(errors: list[str]) -> None:
    reader = ROOT / "Literature-reader.html"
    runtime = ROOT / "scripts" / "literature-reader.mjs"
    if not reader.is_file() or not runtime.is_file():
        errors.append("Literature reader page or runtime is missing")
        return
    parser = parse_page(reader)
    html_attrs = next((attrs for tag, attrs in parser.start_tags if tag == "html"), {})
    if html_attrs.get("lang") != "ru":
        errors.append("Literature-reader.html: html lang must be ru")
    if len(parser.h1_texts) != 1:
        errors.append("Literature-reader.html: expected exactly one H1")
    if not any(tag == "body" and "site-page" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
        errors.append("Literature-reader.html: shared page shell is missing")
    if not any(tag == "main" and attrs.get("id") == "main-content" for tag, attrs in parser.start_tags):
        errors.append("Literature-reader.html: main#main-content is missing")
    if not any(tag == "a" and attrs.get("href") == "#main-content" for tag, attrs in parser.start_tags):
        errors.append("Literature-reader.html: skip link is missing")
    if not any(tag == "a" and attrs.get("href") == "Literature.html" for tag, attrs in parser.start_tags):
        errors.append("Literature-reader.html: back-to-Literature link is missing")
    source = reader.read_text(encoding="utf-8", errors="replace").lower()
    if any(tag in source for tag in ("<iframe", "<object", "<embed")):
        errors.append("Literature-reader.html: raw PDF embed markup is not allowed")
    runtime_source = runtime.read_text(encoding="utf-8", errors="replace")
    expected_files = {
        "ip07": "documents/literature/ip-07-zavisimyi-li-ya.pdf",
        "ip16": "documents/literature/ip-16-novichku.pdf",
        "ip01": "documents/literature/ip-01-kto-chto-kak-i-pochemu.pdf",
        "ip22": "documents/literature/ip-22-dobro-pozhalovat.pdf",
        "ip12": "documents/literature/ip-12-treugolnik-oderzhimosti.pdf",
        "ip13": "documents/literature/ip-13-yunym-zavisimym.pdf",
    }
    if "pdf.legacy.mjs" not in runtime_source or "pdf.worker.legacy.mjs" not in runtime_source:
        errors.append("Literature reader: local legacy PDF.js dependency is missing")
    if any(code not in runtime_source for code in ("LIT-BOOT", "LIT-WORKER", "LIT-FETCH", "LIT-PDF", "LIT-RENDER")):
        errors.append("Literature reader: staged failure diagnostics are incomplete")
    if "getDocument" not in runtime_source or "canvas" not in runtime_source:
        errors.append("Literature reader: PDF rendering output is missing")
    for document_id, filename in expected_files.items():
        pdf = ROOT / filename
        if not pdf.is_file() or pdf.stat().st_size == 0 or not pdf.read_bytes().startswith(b"%PDF-"):
            errors.append(f"Literature reader: invalid local PDF: {filename}")
        if runtime_source.count(filename) != 1 or f"{document_id}:" not in runtime_source:
            errors.append(f"Literature reader: approved mapping is missing or ambiguous for {document_id}")
    legacy_vendor_files = (
        ROOT / "vendor/pdfjs/pdf.legacy.mjs",
        ROOT / "vendor/pdfjs/pdf.worker.legacy.mjs",
        ROOT / "vendor/pdfjs/LICENSE",
        ROOT / "vendor/pdfjs/README.md",
    )
    if not all(path.is_file() for path in legacy_vendor_files):
        errors.append("Literature reader: vendored legacy PDF.js runtime, metadata, or license is missing")
    if (ROOT / "vendor/pdfjs/pdf.mjs").exists() or (ROOT / "vendor/pdfjs/pdf.worker.mjs").exists():
        errors.append("Literature reader: obsolete modern PDF.js runtime remains vendored")


def check_homepage_order(errors: list[str]) -> None:
    index = ROOT / "index.html"
    if not index.is_file():
        return
    parser = parse_page(index)
    actions = [attrs for tag, attrs in parser.start_tags if tag == "a" and "resource-action" in (attrs.get("class") or "").split()]
    expected_hrefs = [
        "https://na-tranzit.org/gruppy/onlajn-gruppy", "Offline-meetings.html", "Literature.html", "AudioBook.html",
        "https://na-russia.org/meditation-today", "https://radio-na.ru/",
        "https://nam-poputi.ucoz.ru/load/audio_vystuplenija_anonimnykh/polnyj_spisok_perevedjonnykh_spikerskikh_s_ivrita/11-1-0-751", "Calculator.html",
    ]
    if [attrs.get("href") for attrs in actions] != expected_hrefs:
        errors.append("index.html: homepage resource actions are not in canonical DOM order")


def check_favicons(errors: list[str]) -> None:
    favicon = ROOT / "images/favicon.png"
    if not favicon.is_file() or favicon.stat().st_size == 0 or not favicon.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        errors.append("images/favicon.png: valid favicon PNG is missing")
    expected = {"rel": "icon", "type": "image/png", "sizes": "64x64", "href": "images/favicon.png?v=2"}
    migrated_pages = (
        "index.html", "Literature.html", "Literature-reader.html", "AudioBook.html", "Offline-meetings.html",
        "Admin-panel.html", "Admin-panel_5ab2b48b89f2fe30ce3272f2816f7d3f19b45752737d55f70f8c3a7f117dc527.html",
        "Calculator.html", "Calendar.html", "Google-Drive.html",
    )
    for name in migrated_pages:
        page = ROOT / name
        if not page.is_file():
            errors.append(f"{name}: migrated page is missing")
            continue
        icons = [attrs for tag, attrs in parse_page(page).start_tags if tag == "link" and attrs.get("rel") == "icon"]
        if icons != [expected]:
            errors.append(f"{name}: expected one versioned favicon declaration {expected}")


def check_audiobook_contract(errors: list[str]) -> None:
    audiobook = ROOT / "AudioBook.html"
    if not audiobook.is_file():
        return
    source = audiobook.read_text(encoding="utf-8", errors="replace")
    parser = parse_page(audiobook)
    html_attrs = next((attrs for tag, attrs in parser.start_tags if tag == "html"), {})
    if html_attrs.get("lang") != "ru":
        errors.append("AudioBook.html: html lang must be ru")
    if parser.h1_texts != ["Базовый текст (аудио)"]:
        errors.append("AudioBook.html: expected one H1: Базовый текст (аудио)")
    if not any(tag == "main" and attrs.get("id") == "main-content" for tag, attrs in parser.start_tags):
        errors.append("AudioBook.html: main#main-content is missing")
    if not any(tag == "a" and attrs.get("href") == "#main-content" for tag, attrs in parser.start_tags):
        errors.append("AudioBook.html: skip link is missing")
    if not any(tag == "a" and "site-header__logo" in (attrs.get("class") or "").split() and attrs.get("href") == "./" for tag, attrs in parser.start_tags):
        errors.append("AudioBook.html: shared home-linked logo is missing")
    if not any(tag == "a" and "site-header__identity" in (attrs.get("class") or "").split() and attrs.get("href") == "./" for tag, attrs in parser.start_tags):
        errors.append("AudioBook.html: shared home-linked identity is missing")
    if not any(tag == "a" and "service-link" in (attrs.get("class") or "").split() and attrs.get("href") == "Admin-panel.html" for tag, attrs in parser.start_tags):
        errors.append("AudioBook.html: shared service link is missing")
    frames = [attrs for tag, attrs in parser.start_tags if tag == "iframe"]
    if len(frames) != 1 or frames[0].get("src") != "bt6-player.html":
        errors.append("AudioBook.html: expected one iframe with bt6-player.html source")
    elif not (frames[0].get("title") or "").strip():
        errors.append("AudioBook.html: player iframe needs a meaningful title")
    lowered = source.lower()
    if "nicepage" in lowered or "jquery" in lowered:
        errors.append("AudioBook.html: Nicepage or jQuery dependency remains")


def check_offline_meetings_contract(errors: list[str]) -> None:
    meetings = ROOT / "Offline-meetings.html"
    if not meetings.is_file():
        return
    source = meetings.read_text(encoding="utf-8", errors="replace")
    parser = parse_page(meetings)
    html_attrs = next((attrs for tag, attrs in parser.start_tags if tag == "html"), {})
    if html_attrs.get("lang") != "ru":
        errors.append("Offline-meetings.html: html lang must be ru")
    if parser.h1_texts != ["Живые группы АН - Россия"]:
        errors.append("Offline-meetings.html: expected one H1: Живые группы АН - Россия")
    if not any(tag == "body" and "site-page" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
        errors.append("Offline-meetings.html: shared full-height page shell is missing")
    if not any(tag == "main" and attrs.get("id") == "main-content" for tag, attrs in parser.start_tags):
        errors.append("Offline-meetings.html: main#main-content is missing")
    if not any(tag == "a" and attrs.get("href") == "#main-content" for tag, attrs in parser.start_tags):
        errors.append("Offline-meetings.html: skip link is missing")
    if not any(tag == "a" and "site-header__logo" in (attrs.get("class") or "").split() and attrs.get("href") == "./" for tag, attrs in parser.start_tags):
        errors.append("Offline-meetings.html: shared home-linked logo is missing")
    if not any(tag == "a" and "site-header__identity" in (attrs.get("class") or "").split() and attrs.get("href") == "./" for tag, attrs in parser.start_tags):
        errors.append("Offline-meetings.html: shared home-linked identity is missing")
    if not any(tag == "a" and "service-link" in (attrs.get("class") or "").split() and attrs.get("href") == "Admin-panel.html" for tag, attrs in parser.start_tags):
        errors.append("Offline-meetings.html: shared service link is missing")
    if not any(tag == "select" and attrs.get("id") == "cityFilter" for tag, attrs in parser.start_tags):
        errors.append("Offline-meetings.html: native city filter is missing")
    if not any(tag == "label" and attrs.get("for") == "cityFilter" for tag, attrs in parser.start_tags):
        errors.append("Offline-meetings.html: city filter label is missing")
    scripts = [attrs.get("src") for tag, attrs in parser.start_tags if tag == "script"]
    if scripts != ["scripts/offline-meetings.js"]:
        errors.append("Offline-meetings.html: expected one dedicated meetings runtime script")
    lowered = source.lower()
    if "nicepage" in lowered or "jquery" in lowered:
        errors.append("Offline-meetings.html: Nicepage or jQuery dependency remains")
    runtime = ROOT / "scripts" / "offline-meetings.js"
    if not runtime.is_file() or 'const MEETINGS_URL = "na_meetings_live.html"' not in runtime.read_text(encoding="utf-8", errors="replace"):
        errors.append("Offline-meetings.html: generated meetings source changed or runtime is missing")


def check_calculator_contract(errors: list[str]) -> None:
    calculator = ROOT / "Calculator.html"
    runtime = ROOT / "scripts" / "calculator.js"
    if not calculator.is_file():
        return
    source = calculator.read_text(encoding="utf-8", errors="replace")
    parser = parse_page(calculator)
    html_attrs = next((attrs for tag, attrs in parser.start_tags if tag == "html"), {})
    if html_attrs.get("lang") != "ru":
        errors.append("Calculator.html: html lang must be ru")
    if not any(tag == "body" and "site-page" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
        errors.append("Calculator.html: shared full-height page shell is missing")
    if parser.h1_texts != ["Калькулятор чистого периода"]:
        errors.append("Calculator.html: expected one H1: Калькулятор чистого периода")
    if not any(tag == "main" and attrs.get("id") == "main-content" for tag, attrs in parser.start_tags):
        errors.append("Calculator.html: main#main-content is missing")
    if not any(tag == "a" and attrs.get("href") == "#main-content" for tag, attrs in parser.start_tags):
        errors.append("Calculator.html: skip link is missing")
    if not any(tag == "a" and "site-header__logo" in (attrs.get("class") or "").split() and attrs.get("href") == "./" for tag, attrs in parser.start_tags):
        errors.append("Calculator.html: shared home-linked logo is missing")
    if not any(tag == "a" and "site-header__identity" in (attrs.get("class") or "").split() and attrs.get("href") == "./" for tag, attrs in parser.start_tags):
        errors.append("Calculator.html: shared home-linked identity is missing")
    if not any(tag == "a" and "service-link" in (attrs.get("class") or "").split() and attrs.get("href") == "Admin-panel.html" for tag, attrs in parser.start_tags):
        errors.append("Calculator.html: shared service link is missing")
    if not any(tag == "footer" and "site-footer" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
        errors.append("Calculator.html: shared footer is missing")
    scripts = [attrs.get("src") for tag, attrs in parser.start_tags if tag == "script"]
    if scripts != ["scripts/calculator.js"]:
        errors.append("Calculator.html: expected one dedicated calculator runtime")
    if "nicepage" in source.lower() or "jquery" in source.lower():
        errors.append("Calculator.html: Nicepage or jQuery dependency remains")
    if (ROOT / "Calculator.css").exists():
        errors.append("Calculator.css: legacy stylesheet should have no remaining consumer")
    if not runtime.is_file() or 'const LS_KEY = "clean_period_start_date_v4"' not in runtime.read_text(encoding="utf-8", errors="replace"):
        errors.append("Calculator.html: persistent localStorage key or runtime is missing")


def check_calendar_contract(errors: list[str]) -> None:
    calendar = ROOT / "Calendar.html"
    runtime = ROOT / "scripts" / "calendar.js"
    if not calendar.is_file():
        errors.append("Calendar.html is missing")
        return
    source = calendar.read_text(encoding="utf-8", errors="replace")
    parser = parse_page(calendar)
    html_attrs = next((attrs for tag, attrs in parser.start_tags if tag == "html"), {})
    if html_attrs.get("lang") != "ru":
        errors.append("Calendar.html: html lang must be ru")
    if not any(tag == "body" and "site-page" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
        errors.append("Calendar.html: shared full-height page shell is missing")
    if parser.h1_texts != ["Календарь событий"]:
        errors.append("Calendar.html: expected one H1: Календарь событий")
    if not any(tag == "main" and attrs.get("id") == "main-content" for tag, attrs in parser.start_tags):
        errors.append("Calendar.html: main#main-content is missing")
    if not any(tag == "a" and attrs.get("href") == "#main-content" for tag, attrs in parser.start_tags):
        errors.append("Calendar.html: skip link is missing")
    if not any(tag == "a" and "site-header__logo" in (attrs.get("class") or "").split() and attrs.get("href") == "./" for tag, attrs in parser.start_tags):
        errors.append("Calendar.html: shared home-linked logo is missing")
    if not any(tag == "a" and "site-header__identity" in (attrs.get("class") or "").split() and attrs.get("href") == "./" for tag, attrs in parser.start_tags):
        errors.append("Calendar.html: shared home-linked identity is missing")
    if not any(tag == "a" and "service-link" in (attrs.get("class") or "").split() and attrs.get("href") == "Admin-panel.html" for tag, attrs in parser.start_tags):
        errors.append("Calendar.html: shared service link is missing")
    if not any(tag == "footer" and "site-footer" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
        errors.append("Calendar.html: shared footer is missing")
    styles = [attrs.get("href") for tag, attrs in parser.start_tags if tag == "link" and attrs.get("rel") == "stylesheet"]
    if styles != ["styles/foundation.css", "styles/components.css", "styles/calendar.css"]:
        errors.append("Calendar.html: expected shared and dedicated calendar stylesheets")
    scripts = [attrs.get("src") for tag, attrs in parser.start_tags if tag == "script"]
    if scripts != ["scripts/calendar.js"]:
        errors.append("Calendar.html: expected one dedicated calendar runtime")
    if "nicepage" in source.lower() or "jquery" in source.lower():
        errors.append("Calendar.html: Nicepage or jQuery dependency remains")
    if (ROOT / "Calendar.css").exists():
        errors.append("Calendar.css: legacy stylesheet should have no remaining consumer")
    frames = [attrs for tag, attrs in parser.start_tags if tag == "iframe" and attrs.get("id") == "gc-frame"]
    if len(frames) != 1 or frames[0].get("title") != "Календарь событий":
        errors.append("Calendar.html: expected one titled Google Calendar iframe")
    edit_url = "https://accounts.google.com/AccountChooser?continue=https%3A%2F%2Fcalendar.google.com%2Fcalendar%2Fr%2Fweek%3Fcid%3Dmeserproject%2540gmail.com&service=cl"
    edits = [attrs for tag, attrs in parser.start_tags if tag == "a" and "gc-btn" in (attrs.get("class") or "").split()]
    if len(edits) != 1 or edits[0].get("href") != edit_url:
        errors.append("Calendar.html: edit action destination changed")
    elif edits[0].get("target") != "_blank" or not {"noopener", "noreferrer"}.issubset(set((edits[0].get("rel") or "").split())):
        errors.append("Calendar.html: edit action lacks safe new-tab semantics")
    runtime_source = runtime.read_text(encoding="utf-8", errors="replace") if runtime.is_file() else ""
    for required in ('const CALENDAR_ID = "meserproject%40gmail.com"', 'const MOBILE_QUERY = "(max-width: 640px)"', 'ctz=Asia%2FJerusalem', '"AGENDA"', '"WEEK"', 'wkst=2'):
        if required not in runtime_source:
            errors.append(f"Calendar.html: runtime missing required Calendar contract: {required}")


def local_check(contract: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    index = ROOT / "index.html"
    if not index.is_file():
        errors.append("index.html is missing")
    if not (ROOT / ".nojekyll").is_file():
        errors.append(".nojekyll is missing")
    for stable_path in contract["stable_paths"]:
        target = index if stable_path == "/" else ROOT / stable_path.lstrip("/")
        if not target.is_file():
            errors.append(f"stable path is missing: {stable_path}")
    for family in contract.get("asset_families", []):
        directory = ROOT / family["directory"]
        for number in range(family["start"], family["end"] + 1):
            filename = f"{family['prefix']}{number:0{family['padding']}d}{family['suffix']}"
            if not (directory / filename).is_file():
                errors.append(f"required asset is missing: {family['directory']}/{filename}")
    if not index.is_file():
        return errors, warnings
    index_parser = parse_page(index)
    homepage_hrefs = [value for tag, attr, value in index_parser.references if tag == "a" and attr == "href"]
    for destination in contract["homepage_internal_destinations"]:
        if destination not in homepage_hrefs:
            errors.append(f"homepage internal destination is missing: {destination}")
    for destination in contract["homepage_external_destinations"]:
        if destination not in homepage_hrefs:
            errors.append(f"homepage external destination changed or missing: {destination}")
    check_homepage_order(errors)
    check_literature_contract(errors)
    check_literature_reader_contract(errors)
    check_favicons(errors)
    check_audiobook_contract(errors)
    check_offline_meetings_contract(errors)
    check_calculator_contract(errors)
    check_calendar_contract(errors)
    parser_cache: dict[Path, PageParser] = {index: index_parser}
    for html_path in ROOT.rglob("*.html"):
        if ".git" in html_path.parts or "venv" in html_path.parts:
            continue
        parser = parser_cache.setdefault(html_path.resolve(), parse_page(html_path.resolve()))
        for _tag, _attribute, reference in parser.references:
            check_reference(reference, html_path.resolve(), contract, errors, warnings, parser_cache)
    for css_path in ROOT.rglob("*.css"):
        if ".git" not in css_path.parts and "venv" not in css_path.parts:
            check_css_references(css_path, contract, errors, warnings)
    return errors, warnings


def remote_check(contract: dict, base_url: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    base_url = base_url.rstrip("/") + "/"
    pages: dict[str, str] = {}
    for stable_path in contract["stable_paths"]:
        url = urljoin(base_url, stable_path.lstrip("/"))
        try:
            with urlopen(Request(url, headers={"User-Agent": "site-contract-check"}), timeout=20) as response:
                if response.status < 200 or response.status >= 400:
                    errors.append(f"remote stable path returned HTTP {response.status}: {url}")
                pages[stable_path] = response.read().decode("utf-8", errors="replace")
        except URLError as exc:
            errors.append(f"remote stable path could not be fetched: {url} ({exc.reason})")
    homepage = pages.get("/", "")
    if homepage:
        parser = PageParser()
        parser.feed(homepage)
        hrefs = [value for tag, attr, value in parser.references if tag == "a" and attr == "href"]
        for destination in contract["homepage_internal_destinations"] + contract["homepage_external_destinations"]:
            if destination not in hrefs:
                errors.append(f"remote homepage contract changed or missing: {destination}")
    return errors, warnings


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--base-url", help="Validate stable URLs against a deployed site")
    args = argument_parser.parse_args()
    contract = load_contract()
    errors, warnings = remote_check(contract, args.base_url) if args.base_url else local_check(contract)
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("Site contract check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
