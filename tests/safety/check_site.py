#!/usr/bin/env python3
"""Validate the repository's stable public-site contract and local resources."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name("site-contract.json")
FILE_ATTRIBUTES = {
    "a": ("href",), "link": ("href",), "script": ("src",), "img": ("src",),
    "iframe": ("src",), "audio": ("src",), "video": ("src",), "source": ("src",),
}
IGNORED_SCHEMES = {"", "http", "https"}
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:?\d{2})$")
LEGACY_RUNTIME_FILES = (
    "nicepage.css",
    "nicepage.js",
    "jquery.js",
)
LEGACY_RUNTIME_DIRECTORY = "intlTelInput"
LEGACY_RUNTIME_RESOURCE_NAMES = frozenset(
    (*LEGACY_RUNTIME_FILES, "intlTelInput.css", "intlTelInput.min.js", "utils.js")
)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, str, str]] = []
        self.anchors: set[str] = set()
        self.start_tags: list[tuple[str, dict[str, str | None]]] = []
        self.h1_texts: list[str] = []
        self._h1_depth = 0
        self._current_h1: list[str] = []
        self.h2_texts: list[str] = []
        self._h2_depth = 0
        self._current_h2: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        self.start_tags.append((tag, values))
        if tag == "h1":
            self._h1_depth += 1
            self._current_h1 = []
        if tag == "h2":
            self._h2_depth += 1
            self._current_h2 = []
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
        if tag == "h2" and self._h2_depth:
            self.h2_texts.append("".join(self._current_h2).strip())
            self._h2_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._h1_depth:
            self._current_h1.append(data)
        if self._h2_depth:
            self._current_h2.append(data)


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


def check_legacy_runtime_contract(errors: list[str]) -> None:
    for filename in LEGACY_RUNTIME_FILES:
        if (ROOT / filename).exists():
            errors.append(f"{filename}: prohibited legacy runtime file remains")
    if (ROOT / LEGACY_RUNTIME_DIRECTORY).exists():
        errors.append(f"{LEGACY_RUNTIME_DIRECTORY}/: prohibited legacy runtime directory remains")

    for html_path in ROOT.glob("*.html"):
        parser = parse_page(html_path)
        for _tag, _attribute, reference in parser.references:
            resource_name = Path(urlparse(reference).path).name.lower()
            if resource_name in LEGACY_RUNTIME_RESOURCE_NAMES:
                errors.append(f"{html_path.name}: prohibited legacy runtime reference remains: {reference}")
        for tag, attrs in parser.start_tags:
            if (tag == "meta" and (attrs.get("name") or "").lower() == "generator" and
                    "nicepage" in (attrs.get("content") or "").lower()):
                errors.append(f"{html_path.name}: Nicepage generator metadata remains")


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
        "Calculator.html", "Calendar.html", "Google-Drive.html", "Audio-Editor.html",
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
    runtime_source = runtime.read_text(encoding="utf-8", errors="replace") if runtime.is_file() else ""
    if not runtime_source or 'const LS_KEY = "clean_period_start_date_v4"' not in runtime_source:
        errors.append("Calculator.html: persistent localStorage key or runtime is missing")
    if 'const DEFAULT_START_YMD = "1953-10-05";' not in runtime_source:
        errors.append("Calculator.html: canonical default start date is missing")
    reset_buttons = [attrs for tag, attrs in parser.start_tags if tag == "button" and attrs.get("id") == "cp-reset"]
    if len(reset_buttons) != 1 or reset_buttons[0].get("type") != "button":
        errors.append("Calculator.html: expected one typed #cp-reset button")
    if ">Сброс</button>" not in source:
        errors.append("Calculator.html: #cp-reset must be labelled Сброс")
    if "cp-today" in source or ">Сегодня</button>" in source:
        errors.append("Calculator.html: obsolete Сегодня action remains")


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
    edits = [attrs for tag, attrs in parser.start_tags if tag == "a" and "gc-btn" in (attrs.get("class") or "").split()]
    if len(edits) != 1:
        errors.append("Calendar.html: expected one edit action")
    elif edits[0].get("target") != "_blank" or not {"noopener", "noreferrer"}.issubset(set((edits[0].get("rel") or "").split())):
        errors.append("Calendar.html: edit action lacks safe new-tab semantics")
    else:
        parsed = urlparse(edits[0].get("href") or "")
        values = parse_qs(parsed.query)
        if (parsed.scheme != "https" or parsed.netloc != "calendar.google.com" or
                parsed.path != "/calendar/r/week" or values != {"cid": ["meserproject@gmail.com"]}):
            errors.append("Calendar.html: edit action direct Calendar destination changed")
    if "accounts.google.com/AccountChooser" in source or "continue=" in source or "service=cl" in source:
        errors.append("Calendar.html: obsolete AccountChooser action remains")
    if "Открыть календарь в Google Calendar" not in source:
        errors.append("Calendar.html: direct Calendar action label is missing")
    if "Календарь доступен для просмотра здесь. Пользователи с соответствующими правами могут редактировать его в Google Calendar." not in source:
        errors.append("Calendar.html: direct Calendar permission note is missing")
    runtime_source = runtime.read_text(encoding="utf-8", errors="replace") if runtime.is_file() else ""
    for required in ('const CALENDAR_ID = "meserproject%40gmail.com"', 'const MOBILE_QUERY = "(max-width: 640px)"', 'ctz=Asia%2FJerusalem', '"AGENDA"', '"WEEK"', 'wkst=2'):
        if required not in runtime_source:
            errors.append(f"Calendar.html: runtime missing required Calendar contract: {required}")


def check_google_drive_contract(errors: list[str]) -> None:
    drive = ROOT / "Google-Drive.html"
    if not drive.is_file():
        errors.append("Google-Drive.html is missing")
        return
    source = drive.read_text(encoding="utf-8", errors="replace")
    parser = parse_page(drive)
    html_attrs = next((attrs for tag, attrs in parser.start_tags if tag == "html"), {})
    if html_attrs.get("lang") != "ru":
        errors.append("Google-Drive.html: html lang must be ru")
    if not any(tag == "body" and "site-page" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
        errors.append("Google-Drive.html: shared full-height page shell is missing")
    if parser.h1_texts != ["Материалы"]:
        errors.append("Google-Drive.html: expected one H1: Материалы")
    if not any(tag == "main" and attrs.get("id") == "main-content" for tag, attrs in parser.start_tags):
        errors.append("Google-Drive.html: main#main-content is missing")
    if not any(tag == "a" and attrs.get("href") == "#main-content" for tag, attrs in parser.start_tags):
        errors.append("Google-Drive.html: skip link is missing")
    for class_name, href in (("site-header__logo", "./"), ("site-header__identity", "./"), ("service-link", "Admin-panel.html")):
        if not any(tag == "a" and class_name in (attrs.get("class") or "").split() and attrs.get("href") == href for tag, attrs in parser.start_tags):
            errors.append(f"Google-Drive.html: shared {class_name} link is missing")
    if not any(tag == "footer" and "site-footer" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
        errors.append("Google-Drive.html: shared footer is missing")
    styles = [attrs.get("href") for tag, attrs in parser.start_tags if tag == "link" and attrs.get("rel") == "stylesheet"]
    if styles != ["styles/foundation.css", "styles/components.css", "styles/google-drive.css"]:
        errors.append("Google-Drive.html: expected shared and dedicated Drive stylesheets")
    scripts = [attrs.get("src") for tag, attrs in parser.start_tags if tag == "script"]
    if scripts:
        errors.append("Google-Drive.html: native catalog must not load a dedicated runtime")
    if "nicepage" in source.lower() or "jquery" in source.lower():
        errors.append("Google-Drive.html: Nicepage or jQuery dependency remains")
    if (ROOT / "Google-Drive.css").exists():
        errors.append("Google-Drive.css: legacy stylesheet should have no remaining consumer")
    if any(tag == "iframe" for tag, _attrs in parser.start_tags) or "embeddedfolderview" in source:
        errors.append("Google-Drive.html: obsolete Drive iframe integration remains")
    if "accounts.google.com/AccountChooser" in source or "service=writely" in source or "continue=" in source:
        errors.append("Google-Drive.html: obsolete AccountChooser integration remains")
    if (ROOT / "scripts" / "google-drive.js").exists():
        errors.append("scripts/google-drive.js: obsolete iframe runtime should be removed")
    expected_folders = (
        ("Аварийная коммуникация", "1DxqR91OJeER4nsPxPqncvBNH0379wOxX"),
        ("Архив спикерских", "1MuiNuW6oBzgDls1y_MeGXgOu0qrZhjdr"),
        ("Карточки", "1aZTL1CoTwpVrdKlE8O7KOtQjlmj_0s9g"),
        ("Концепции служения", "1qI_HNm2Ifay0jiLZmcsI1Qy1f6Z1Y0iU"),
        ("Отчёты", "1-X980mz_eSJ0IVh8sr3uWmdbG_SM3Xvt"),
        ("Преамбулы", "1U86CV0y4ziA9ex-WjHcfbdbxVD3aQi0q"),
        ("Устав", "1dZ1Z3I_I79-mWCsaxTi5Jg11SAiEzPjq"),
    )
    labels = re.findall(r'<span class="drive-folder__label">([^<]+)</span>', source)
    if labels != [label for label, _folder_id in expected_folders]:
        errors.append("Google-Drive.html: folder labels or their order changed")
    folders = [attrs for tag, attrs in parser.start_tags if tag == "a" and "drive-folder" in (attrs.get("class") or "").split()]
    if len(folders) != len(expected_folders):
        errors.append("Google-Drive.html: expected exactly seven folder-card links")
    for index, (_label, folder_id) in enumerate(expected_folders):
        if index >= len(folders):
            break
        folder = folders[index]
        parsed = urlparse(folder.get("href") or "")
        if (parsed.scheme != "https" or parsed.netloc != "drive.google.com" or
                parsed.path != f"/drive/folders/{folder_id}" or parsed.query or parsed.fragment):
            errors.append(f"Google-Drive.html: folder card {index + 1} direct Drive destination changed")
        if folder.get("target") != "_blank" or not {"noopener", "noreferrer"}.issubset(set((folder.get("rel") or "").split())):
            errors.append(f"Google-Drive.html: folder card {index + 1} lacks safe new-tab semantics")
    parent_actions = [attrs for tag, attrs in parser.start_tags if tag == "a" and attrs.get("id") == "drive-open-all"]
    parent_id = "1XjxskHzqZeVhhCx4HTe00mWWRuH2Sdnc"
    if len(parent_actions) != 1:
        errors.append("Google-Drive.html: expected one parent-folder action")
    else:
        parent = parent_actions[0]
        parsed = urlparse(parent.get("href") or "")
        if (parsed.scheme != "https" or parsed.netloc != "drive.google.com" or
                parsed.path != f"/drive/folders/{parent_id}" or parsed.query or parsed.fragment):
            errors.append("Google-Drive.html: parent-folder direct Drive destination changed")
        if parent.get("target") != "_blank" or not {"noopener", "noreferrer"}.issubset(set((parent.get("rel") or "").split())):
            errors.append("Google-Drive.html: parent-folder action lacks safe new-tab semantics")
    if "Материалы доступны для просмотра всем по ссылке. Редактирование доступно только пользователям с соответствующими правами." not in source:
        errors.append("Google-Drive.html: permission note is missing")


def check_admin_access_contract(errors: list[str]) -> None:
    login = ROOT / "Admin-panel.html"
    landing_name = "Admin-panel_5ab2b48b89f2fe30ce3272f2816f7d3f19b45752737d55f70f8c3a7f117dc527.html"
    landing = ROOT / landing_name
    login_runtime = ROOT / "scripts" / "admin-access.js"
    landing_runtime = ROOT / "scripts" / "service-landing.js"
    for page, expected_h1 in ((login, "Для служащих"), (landing, "Служебная страница")):
        if not page.is_file():
            errors.append(f"{page.name} is missing")
            continue
        source = page.read_text(encoding="utf-8", errors="replace")
        parser = parse_page(page)
        html_attrs = next((attrs for tag, attrs in parser.start_tags if tag == "html"), {})
        if html_attrs.get("lang") != "ru":
            errors.append(f"{page.name}: html lang must be ru")
        if parser.h1_texts != [expected_h1]:
            errors.append(f"{page.name}: expected one H1: {expected_h1}")
        if not any(tag == "body" and "site-page" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
            errors.append(f"{page.name}: shared full-height page shell is missing")
        if not any(tag == "main" and attrs.get("id") == "main-content" for tag, attrs in parser.start_tags):
            errors.append(f"{page.name}: main#main-content is missing")
        if not any(tag == "a" and attrs.get("href") == "#main-content" for tag, attrs in parser.start_tags):
            errors.append(f"{page.name}: skip link is missing")
        for class_name, href in (("site-header__logo", "./"), ("site-header__identity", "./"), ("service-link", "Admin-panel.html")):
            if not any(tag == "a" and class_name in (attrs.get("class") or "").split() and attrs.get("href") == href for tag, attrs in parser.start_tags):
                errors.append(f"{page.name}: shared {class_name} link is missing")
        if not any(tag == "footer" and "site-footer" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
            errors.append(f"{page.name}: shared footer is missing")
        favicon = [attrs for tag, attrs in parser.start_tags if tag == "link" and attrs.get("rel") == "icon"]
        if len(favicon) != 1 or favicon[0].get("href") != "images/favicon.png?v=2":
            errors.append(f"{page.name}: versioned favicon is missing")
        if "nicepage" in source.lower() or "jquery" in source.lower():
            errors.append(f"{page.name}: Nicepage or jQuery dependency remains")

    if login.is_file():
        source = login.read_text(encoding="utf-8", errors="replace")
        parser = parse_page(login)
        styles = [attrs.get("href") for tag, attrs in parser.start_tags if tag == "link" and attrs.get("rel") == "stylesheet"]
        if styles != ["styles/foundation.css", "styles/components.css", "styles/admin-access.css"]:
            errors.append("Admin-panel.html: expected shared and dedicated admin stylesheets")
        scripts = [attrs.get("src") for tag, attrs in parser.start_tags if tag == "script"]
        if scripts != ["scripts/admin-access.js"]:
            errors.append("Admin-panel.html: expected one dedicated admin runtime")
        forms = [attrs for tag, attrs in parser.start_tags if tag == "form"]
        if len(forms) != 1 or forms[0].get("id") != "admin-access-form":
            errors.append("Admin-panel.html: expected one semantic password form")
        inputs = [attrs for tag, attrs in parser.start_tags if tag == "input" and attrs.get("id") == "admin-password"]
        if (len(inputs) != 1 or inputs[0].get("type") != "password" or inputs[0].get("autocomplete") != "current-password" or
                "required" not in inputs[0] or inputs[0].get("value") is not None):
            errors.append("Admin-panel.html: password input contract changed")
        labels = [attrs for tag, attrs in parser.start_tags if tag == "label" and attrs.get("for") == "admin-password"]
        if len(labels) != 1 or "sr-only" in (labels[0].get("class") or "").split():
            errors.append("Admin-panel.html: visible associated password label is missing")
        toggles = [attrs for tag, attrs in parser.start_tags if tag == "button" and attrs.get("id") == "admin-password-toggle"]
        if (len(toggles) != 1 or toggles[0].get("type") != "button" or
                toggles[0].get("aria-label") != "Показать пароль" or
                toggles[0].get("aria-controls") != "admin-password"):
            errors.append("Admin-panel.html: accessible show-password button contract changed")
        if "<svg" not in source or "admin-password-toggle" not in source:
            errors.append("Admin-panel.html: local inline eye icon is missing")
        buttons = [attrs for tag, attrs in parser.start_tags if tag == "button" and attrs.get("type") == "submit"]
        if len(buttons) != 1 or ">Войти</button>" not in source:
            errors.append("Admin-panel.html: real Войти submit button is missing")
        if not any(attrs.get("aria-live") == "polite" for tag, attrs in parser.start_tags if tag in {"p", "div"}):
            errors.append("Admin-panel.html: polite live error region is missing")
        if "Введите пароль для доступа к служебным инструментам." not in source:
            errors.append("Admin-panel.html: intro text changed")

    runtime_source = login_runtime.read_text(encoding="utf-8", errors="replace") if login_runtime.is_file() else ""
    required_login_runtime = (
        'const SALT = "2969"',
        'const SALTED_PASSWORD_VERIFIER = "598ebb5954daa98ece99310008316b259607777f0772006fb675ca92962cc216"',
        'const SESSION_KEY = "meser_service_access_v1"',
        f'const LANDING_URL = "{landing_name}"',
        'value.charCodeAt(index) & 0xff',
        'function sha256Fallback(bytes)',
        'window.crypto?.subtle?.digest',
        'window.crypto.subtle.digest("SHA-256", bytes)',
        'return sha256Fallback(bytes);',
        'window.AdminAccessHash = AdminAccessHash',
        'legacySha256(passwordInput.value + SALT)',
        'sessionStorage.setItem(SESSION_KEY, "granted")',
        'location.replace(LANDING_URL)',
        'error.textContent = "Неверный пароль."',
        'error.textContent = "Не удалось проверить пароль. Попробуйте ещё раз."',
        'passwordToggle.setAttribute("aria-label", showPassword ? "Скрыть пароль" : "Показать пароль")',
    )
    for required in required_login_runtime:
        if required not in runtime_source:
            errors.append(f"Admin-panel.html: runtime missing required access contract: {required}")
    if "localStorage" in runtime_source or '"auth_key"' in runtime_source:
        errors.append("Admin-panel.html: legacy persistent password storage remains")
    if 'catch {\n        // A present but unusable Web Crypto API must not block LAN HTTP access.\n      }\n    }\n    return sha256Fallback(bytes);' not in runtime_source:
        errors.append("Admin-panel.html: missing Web Crypto fallback path")
    if 'catch {\n      error.textContent = "Неверный пароль."' in runtime_source:
        errors.append("Admin-panel.html: technical hashing failures must not be reported as invalid passwords")

    if landing.is_file():
        source = landing.read_text(encoding="utf-8", errors="replace")
        parser = parse_page(landing)
        styles = [attrs.get("href") for tag, attrs in parser.start_tags if tag == "link" and attrs.get("rel") == "stylesheet"]
        if styles != ["styles/foundation.css", "styles/components.css", "styles/service-landing.css"]:
            errors.append(f"{landing_name}: expected shared and dedicated landing stylesheets")
        scripts = [attrs for tag, attrs in parser.start_tags if tag == "script"]
        if len(scripts) != 1 or scripts[0].get("src") != "scripts/service-landing.js" or scripts[0].get("defer") is not None:
            errors.append(f"{landing_name}: expected one early blocking guard runtime")
        actions = [attrs for tag, attrs in parser.start_tags if tag == "a" and "service-action" in (attrs.get("class") or "").split()]
        if [attrs.get("href") for attrs in actions] != ["Calendar.html", "Google-Drive.html", "Audio-Editor.html"]:
            errors.append(f"{landing_name}: service actions changed or are out of order")
        if any(attrs.get("target") is not None for attrs in actions):
            errors.append(f"{landing_name}: service actions must use same-tab navigation")
        labels = re.findall(r'<a class="service-action"[^>]*>([^<]+)</a>', source)
        if labels != ["Календарь", "Материалы", "Редактирование аудио"]:
            errors.append(f"{landing_name}: service action labels changed")
        logout = [attrs for tag, attrs in parser.start_tags if tag == "button" and attrs.get("id") == "service-logout"]
        if len(logout) != 1 or ">Выйти</button>" not in source:
            errors.append(f"{landing_name}: logout control is missing")

    landing_runtime_source = landing_runtime.read_text(encoding="utf-8", errors="replace") if landing_runtime.is_file() else ""
    for required in ('const SESSION_KEY = "meser_service_access_v1"', 'sessionStorage.getItem(SESSION_KEY) !== "granted"', 'location.replace(LOGIN_URL)', 'sessionStorage.removeItem(SESSION_KEY)'):
        if required not in landing_runtime_source:
            errors.append(f"{landing_name}: guard runtime missing required contract: {required}")
    if 'const LOGIN_URL = "Admin-panel.html"' not in landing_runtime_source:
        errors.append(f"{landing_name}: unauthorized redirect target changed")
    for legacy_css in ("Page-Password-Template.css", "Admin-panel.css"):
        if (ROOT / legacy_css).exists():
            errors.append(f"{legacy_css}: legacy admin stylesheet should be removed")


def is_iso_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not ISO_TIMESTAMP_RE.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def is_release_asset_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    prefix = "/meser-recovery/starter-package/releases/download/"
    remaining = [part for part in parsed.path.removeprefix(prefix).split("/") if part]
    return (
        parsed.scheme == "https" and parsed.netloc == "github.com" and not parsed.username and not parsed.password and
        parsed.path.startswith(prefix) and len(remaining) >= 2
    )


def check_audio_editor_contract(errors: list[str]) -> None:
    page = ROOT / "Audio-Editor.html"
    manifest_path = ROOT / "data" / "edited-audio.json"
    if not page.is_file():
        errors.append("Audio-Editor.html is missing")
    else:
        source = page.read_text(encoding="utf-8", errors="replace")
        parser = parse_page(page)
        html_attrs = next((attrs for tag, attrs in parser.start_tags if tag == "html"), {})
        if html_attrs.get("lang") != "ru":
            errors.append("Audio-Editor.html: html lang must be ru")
        if parser.h1_texts != ["Редактирование аудио"]:
            errors.append("Audio-Editor.html: expected one H1: Редактирование аудио")
        if not any(tag == "h2" for tag, attrs in parser.start_tags) or "Архив отредактированных аудио" not in source:
            errors.append("Audio-Editor.html: archive H2 is missing")
        if not any(tag == "body" and "site-page" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
            errors.append("Audio-Editor.html: shared page shell is missing")
        if not any(tag == "main" and attrs.get("id") == "main-content" for tag, attrs in parser.start_tags):
            errors.append("Audio-Editor.html: main#main-content is missing")
        if not any(tag == "a" and attrs.get("href") == "#main-content" for tag, attrs in parser.start_tags):
            errors.append("Audio-Editor.html: skip link is missing")
        for class_name, href in (("site-header__logo", "./"), ("site-header__identity", "./")):
            if not any(tag == "a" and class_name in (attrs.get("class") or "").split() and attrs.get("href") == href for tag, attrs in parser.start_tags):
                errors.append(f"Audio-Editor.html: shared {class_name} link is missing")
        if not any(tag == "a" and attrs.get("href") == "Admin-panel_5ab2b48b89f2fe30ce3272f2816f7d3f19b45752737d55f70f8c3a7f117dc527.html" for tag, attrs in parser.start_tags):
            errors.append("Audio-Editor.html: exact service landing back link is missing")
        if not any(tag == "button" and attrs.get("id") == "service-logout" for tag, attrs in parser.start_tags):
            errors.append("Audio-Editor.html: service logout is missing")
        if not any(tag == "footer" and "site-footer" in (attrs.get("class") or "").split() for tag, attrs in parser.start_tags):
            errors.append("Audio-Editor.html: shared footer is missing")
        styles = [attrs.get("href") for tag, attrs in parser.start_tags if tag == "link" and attrs.get("rel") == "stylesheet"]
        if styles != ["styles/foundation.css", "styles/components.css", "styles/audio-editor.css"]:
            errors.append("Audio-Editor.html: expected shared and dedicated stylesheets")
        scripts = [(attrs.get("src"), "defer" in attrs) for tag, attrs in parser.start_tags if tag == "script"]
        if scripts != [("scripts/service-landing.js", False), ("scripts/audio-editor.js", True), ("scripts/audio-processor.mjs", False)]:
            errors.append("Audio-Editor.html: expected guard before dedicated archive runtime")
        if any(tag == "script" and not attrs.get("src") for tag, attrs in parser.start_tags):
            errors.append("Audio-Editor.html: inline scripts are not allowed")
        if "nicepage" in source.lower() or "jquery" in source.lower():
            errors.append("Audio-Editor.html: Nicepage or jQuery dependency remains")

    if not manifest_path.is_file():
        errors.append("data/edited-audio.json is missing")
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        errors.append("data/edited-audio.json: invalid JSON")
        return
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        errors.append("data/edited-audio.json: schemaVersion must be 1")
        return
    if manifest.get("updatedAt") is not None and not is_iso_timestamp(manifest.get("updatedAt")):
        errors.append("data/edited-audio.json: updatedAt must be null or a valid ISO timestamp")
    items = manifest.get("items")
    if not isinstance(items, list):
        errors.append("data/edited-audio.json: items must be an array")
        return
    seen_ids: set[str] = set()
    for index, item in enumerate(items):
        prefix = f"data/edited-audio.json: item {index + 1}"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            errors.append(f"{prefix} id must be a non-empty string")
        elif item_id in seen_ids:
            errors.append(f"{prefix} id must be unique")
        else:
            seen_ids.add(item_id)
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            errors.append(f"{prefix} name must be a non-empty string")
        if not is_iso_timestamp(item.get("processedAt")):
            errors.append(f"{prefix} processedAt must be a valid ISO timestamp")
        duration = item.get("durationSeconds")
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            errors.append(f"{prefix} durationSeconds must be a positive finite number")
        if not is_release_asset_url(item.get("audioUrl")):
            errors.append(f"{prefix} audioUrl must be a canonical GitHub Release asset URL")


FFMPEG_WASM_SHA256 = "9f57947a5bd530d8f00c5b3f2cb2a3492faa7e5d823315342d6a8656d0a6b7b7"
FFMPEG_WASM_BYTES = 32232419
FFMPEG_HASHES = {
    "ffmpeg/index.js": "cad19572420f7ead17272082d9582ebaed7f2856e19875542f83daf8d25d3b5d",
    "ffmpeg/classes.js": "7a829c898bdbc3a8806652a5502d9101178ce4e988a2c50b3abc1306ce4fc919",
    "ffmpeg/const.js": "9e3bc9dd84781c81daf459e2c46eeec815edac35089832681d9a9a0f383060d0",
    "ffmpeg/errors.js": "619310d7ef5fe5fefa0a31927db862b7c291713cfef4d71753fa8aafd18f4db6",
    "ffmpeg/types.js": "72f80e6fd44fcd18b55c9a0deb3bc70b9bb37480cf969045ca4521f5a11300f5",
    "ffmpeg/utils.js": "8c2e0e16445f8d3a0acbb812f2c60541a92c88ed0bf9ffe96c52e7fb6c8b1d72",
    "ffmpeg/worker.js": "feff0ac937ea225e997e1fae997a74f8b8d572423a526da59eb56624b1f3cde7",
    "core/ffmpeg-core.js": "67a48f11645f85439f3fde4f2119042c16b374b910206b7a7a24f342e28dcae3",
    "core/ffmpeg-core.wasm": FFMPEG_WASM_SHA256,
    "licenses/ffmpeg-wasm-MIT.txt": "3e123e29517d76504ffce77b3f8e2ccffd4712493f27694b0aba3e376676459f",
    "licenses/FFmpeg-GPLv2.txt": "8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643",
    "licenses/FFmpeg-LGPLv2.1.txt": "b634ab5640e258563c536e658cad87080553df6f34f62269a21d554844e58bfe",
}
PROCESSOR_ACCEPT = {".mp3", ".m4a", ".wav", "audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/wav", "audio/x-wav"}


def check_processor_markup(source: str, errors: list[str]) -> None:
    parser = PageParser()
    parser.feed(source)
    if parser.h2_texts != ["Обработка аудио", "Архив отредактированных аудио"]:
        errors.append("Audio-Editor.html: expected exactly processor then archive H2")
    tags = parser.start_tags
    ids = [attrs.get("id") for _, attrs in tags if attrs.get("id")]
    expected = {
        "processor-heading": "h2", "processor-file": "input", "processor-run": "button",
        "processor-cancel": "button", "processor-status": "p", "processor-progress": "progress",
        "processor-source-audio": "audio", "processor-result": "div", "processor-result-audio": "audio",
        "processor-download": "a", "processor-file-info": "ul", "processor-original-duration": "dd",
        "processor-processed-duration": "dd", "processor-removed-duration": "dd", "processor-pause-count": "dd",
        "processor-selection-summary": "p", "processor-mixed-count": "p", "processor-pause-label": "dt",
        "processor-source-label": "h3", "processor-source-time": "p",
        "processor-source-zoom-out": "button", "processor-source-zoom-range": "input",
        "processor-source-zoom-in": "button", "processor-source-zoom-fit": "button",
        "processor-source-navigation": "div", "processor-source-scrollbar": "div",
        "processor-source-scrollbar-spacer": "div", "processor-source-follow": "button",
        "processor-result-waveform-scroll": "div", "processor-result-waveform-control": "button",
        "processor-result-waveform-status": "p", "processor-result-time": "p",
    }
    for element_id, element_tag in expected.items():
        if ids.count(element_id) != 1 or not any(tag == element_tag and attrs.get("id") == element_id for tag, attrs in tags):
            errors.append(f"Audio-Editor.html: missing/duplicate/invalid {element_id}")
    elements = {attrs.get("id"): attrs for _, attrs in tags if attrs.get("id")}
    if elements.get("processor-file", {}).get("type") != "file" or set((elements.get("processor-file", {}).get("accept") or "").split(",")) != PROCESSOR_ACCEPT:
        errors.append("Audio-Editor.html: processor extension/MIME accept list changed")
    if "multiple" not in elements.get("processor-file", {}):
        errors.append("Audio-Editor.html: processor must accept one or multiple tracks")
    if not any(tag == "label" and attrs.get("for") == "processor-file" for tag, attrs in tags):
        errors.append("Audio-Editor.html: file label missing")
    for element_id in ("processor-run", "processor-cancel"):
        if elements.get(element_id, {}).get("type") != "button":
            errors.append(f"Audio-Editor.html: {element_id} must not submit a form")
    for element_id, label in (("processor-run", "Обработать"), ("processor-cancel", "Отменить"), ("processor-download", "Скачать обработанный MP3")):
        if not re.search(rf'<[^>]+id="{element_id}"[^>]*>{re.escape(label)}</', source):
            errors.append(f"Audio-Editor.html: incorrect label for {element_id}")
    if "disabled" not in elements.get("processor-run", {}):
        errors.append("Audio-Editor.html: processor Run must start disabled")
    for element_id in ("processor-cancel", "processor-progress", "processor-result", "processor-source-navigation"):
        if "hidden" not in elements.get(element_id, {}):
            errors.append(f"Audio-Editor.html: {element_id} must start hidden")
    if elements.get("processor-status", {}).get("role") != "status" or "value" in elements.get("processor-progress", {}):
        errors.append("Audio-Editor.html: live status/indeterminate progress contract changed")
    follow = elements.get("processor-source-follow", {})
    if (follow.get("aria-pressed") != "false" or not re.search(
            r'<button[^>]+id="processor-source-follow"[^>]*>Следовать за воспроизведением</button>', source)):
        errors.append("Audio-Editor.html: source follow toggle contract changed")
    scrollbar = elements.get("processor-source-scrollbar", {})
    if scrollbar.get("tabindex") != "0" or scrollbar.get("aria-labelledby") != "processor-source-navigation-label":
        errors.append("Audio-Editor.html: shared source scrollbar is not keyboard accessible")
    if "processor-result-follow" in ids or source.count('id="processor-source-scrollbar"') != 1:
        errors.append("Audio-Editor.html: source/result follow or shared scrollbar count contract changed")
    for tag, attrs in tags:
        if tag == "audio" and ("autoplay" in attrs or "controls" not in attrs):
            errors.append("Audio-Editor.html: audio must have native controls and no autoplay")
        if tag == "script" and attrs.get("src") == "scripts/audio-processor.mjs" and attrs.get("type") != "module":
            errors.append("Audio-Editor.html: processor runtime must be a module")
        if tag in {"script", "link"} and "ffmpeg" in (attrs.get("src") or attrs.get("href") or "").lower():
            errors.append("Audio-Editor.html: FFmpeg must not load/preload on page open")
    scripts = [attrs for tag, attrs in tags if tag == "script"]
    if ([attrs.get("src") for attrs in scripts] != ["scripts/service-landing.js", "scripts/audio-editor.js", "scripts/audio-processor.mjs"] or
            not scripts or any(key in scripts[0] for key in ("async", "defer", "type"))):
        errors.append("Audio-Editor.html: early blocking guard/archive/module order changed")
    for text in ("Длинные участки тишины продолжительностью 2 секунды и больше сокращаются примерно до 0,35 секунды.",
                 "Исходные файлы обрабатываются локально в браузере и не отправляются на сервер.",
                 "Общий размер всех файлов — не более 500 МБ.", "все выбранные дорожки одновременно молчат"):
        if text not in source:
            errors.append(f"Audio-Editor.html: processor explanation missing: {text}")


def check_audio_processor_contract(errors: list[str]) -> None:
    page = ROOT / "Audio-Editor.html"
    if page.is_file():
        check_processor_markup(page.read_text(encoding="utf-8"), errors)
    runtime = ROOT / "scripts/audio-processor.mjs"
    if not runtime.is_file():
        errors.append("scripts/audio-processor.mjs is missing")
        return
    source = runtime.read_text(encoding="utf-8")
    required = (
        "const MIN_SILENCE_SECONDS = 2.0;", "const TARGET_SILENCE_SECONDS = 0.35;",
        "const SILENCE_THRESHOLD_DB = -45;", 'const OUTPUT_BITRATE = "128k";',
        "const MAX_INPUT_BYTES = 500 * 1024 * 1024;", 'import("../vendor/ffmpeg/ffmpeg/index.js")',
        'coreURL: new URL("../vendor/ffmpeg/core/ffmpeg-core.js", import.meta.url).href',
        'wasmURL: new URL("../vendor/ffmpeg/core/ffmpeg-core.wasm", import.meta.url).href',
        '"0:a:0"', '"libmp3lame"', "silencedetect=noise=", "aselect=", "asetpts=N/SR/TB",
        "engine.terminate()", "URL.revokeObjectURL", "currentEngine.deleteFile(path)",
        "Поддерживаются файлы MP3, M4A и WAV.",
        "Общий размер файлов слишком большой для обработки в браузере. Максимальный размер — 500 МБ.",
        "const MAX_DURATION_DIFFERENCE_SECONDS = 0.5;",
        "Дорожки имеют разную длительность. Проверьте, что они относятся к одной записи Zoom.",
        "Длинные общие паузы не найдены. Дорожки сведены без сокращения пауз.",
        "commonSilences(analyses, duration)", "commonTimeline(analyses)",
        "const cuts = makeFilter(ranges)", "normalize=0", "alimiter=limit=0.95:level=0:latency=1",
        '"-filter_complex_script"', '"-map", "[mixed]"', "`processor-input-${index}`",
        "files.reduce((sum, file) => sum + file.size, 0)", "[...inputPaths, ...TEMP_PATHS]",
        "Выбрано дорожек:", "Дорожек сведено:", "Сокращено общих длинных пауз",
        "const WAVEFORM_PIXELS_PER_SECOND = 4;", "const WAVEFORM_MAX_WIDTH = 16384;",
        "showwavespic=s=", "aformat=channel_layouts=mono", 'new Blob([image], { type: "image/png" })',
        "processor-waveform-input-${track.id}", "processor-waveform-${track.id}.png",
        "Не удалось построить форму сигнала.", "Подготовка формы сигнала…",
        "requestAnimationFrame", "ArrowLeft", "ArrowRight", 'event.key === "Home"', 'event.key === "End"',
        "URL.revokeObjectURL(track.waveformURL)", "Соло", "Заглушить", "Удалить",
        "processor-result-waveform.png", "resultWaveformURL", "processor-preview-audio",
        "let sourceLeftVisibleTime = 0;", "let sourceViewportDuration = 0;",
        "sourceFollowEnabled", "source-scrollbar-spacer",
        "Обработка аудио не поддерживается в этом браузере.", "Обработка отменена.",
        "Длинные паузы не найдены. Файл не изменён.", "Подготовка обработчика…",
        "Поиск длинных пауз…", "Сокращение пауз и создание MP3…", "Готово.",
    )
    for token in required:
        if token not in source:
            errors.append(f"Processor runtime contract missing: {token}")
    if re.search(r'^import\s', source, re.M):
        errors.append("Processor must import FFmpeg lazily after valid source selection")
    if "Прослушать" in source or "processor-track-switcher" in source or "<details" in page.read_text(encoding="utf-8"):
        errors.append("Processor retains the obsolete track switcher/detail waveform UI")
    forbidden = r"https?://|\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|silenceremove|SharedArrayBuffer|core-mt|wavesurfer|peaks\.js|\b(?:atempo|loudnorm|dynaudnorm)\b|[\"']-(?:ar|ac|itsoffset)[\"']|\b(?:adelay|pan)="
    if re.search(forbidden, source):
        errors.append("Processor has a forbidden external/write API, DSP, or threading dependency")
    own_source = source + (page.read_text(encoding="utf-8") if page.is_file() else "")
    if re.search(r"gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]+|Bearer\s+[A-Za-z0-9]|api[_-]?key\s*[:=]|<form\b|\bupload\b", own_source, re.I):
        errors.append("Processor contains a credential/upload/form contract violation")
    for relative, expected_hash in {
        "data/edited-audio.json": "196cb8d26daf8251485383d37df0c270e11f5d1b8a455fccc25903ddfe9c9364",
        "scripts/audio-editor.js": "51448c682e5b21149191016b74d9374ce499b19c75df64bcf1b15cde657898ee",
        "scripts/service-landing.js": "78387a46da7668981bfb7b5b6742838118a2dc26c00b81f07254faec90c01836",
    }.items():
        path = ROOT / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            errors.append(f"Stage 7 must preserve Stage 6 bytes: {relative}")
    vendor = ROOT / "vendor/ffmpeg"
    actual = {path.relative_to(vendor).as_posix() for path in vendor.rglob("*") if path.is_file()}
    if actual != set(FFMPEG_HASHES) | {"README.md"}:
        errors.append("FFmpeg vendor file set differs from the pinned minimal ESM closure/licenses")
    for relative, expected_hash in FFMPEG_HASHES.items():
        path = vendor / relative
        if not path.is_file() or not path.stat().st_size:
            errors.append(f"FFmpeg vendor asset missing/empty: {relative}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            errors.append(f"FFmpeg vendor upstream SHA-256 mismatch: {relative}")
    wasm = vendor / "core/ffmpeg-core.wasm"
    if wasm.is_file():
        with wasm.open("rb") as handle:
            if handle.read(4) != b"\x00asm" or wasm.stat().st_size != FFMPEG_WASM_BYTES:
                errors.append("FFmpeg WASM magic bytes/byte size mismatch")
    readme = vendor / "README.md"
    provenance = readme.read_text(encoding="utf-8") if readme.is_file() else ""
    for token in ("@ffmpeg/ffmpeg", "0.12.15", "@ffmpeg/core", "0.12.10", "single-thread",
                  "https://github.com/ffmpegwasm/ffmpeg.wasm", "https://registry.npmjs.org/", FFMPEG_WASM_SHA256):
        if token not in provenance:
            errors.append(f"FFmpeg provenance missing: {token}")
    for path in ROOT.rglob("*"):
        if any(part in {".git", "venv", ".venv"} for part in path.relative_to(ROOT).parts):
            continue
        if path.name in {"package.json", "package-lock.json", "node_modules", "yarn.lock", "pnpm-lock.yaml", "webpack.config.js", "vite.config.js"}:
            errors.append(f"Prohibited npm/build artifact: {path.relative_to(ROOT)}")


def local_check(contract: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    check_legacy_runtime_contract(errors)
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
    check_google_drive_contract(errors)
    check_admin_access_contract(errors)
    check_audio_editor_contract(errors)
    check_audio_processor_contract(errors)
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
    if pages.get("/Audio-Editor.html"):
        check_processor_markup(pages["/Audio-Editor.html"], errors)
    # HEAD only: production checks must not download the 31 MiB WASM on each run.
    for relative in ["scripts/audio-processor.mjs", *[f"vendor/ffmpeg/{path}" for path in FFMPEG_HASHES]]:
        asset_url = urljoin(base_url, relative)
        try:
            with urlopen(Request(asset_url, method="HEAD", headers={"User-Agent": "site-contract-check"}), timeout=30) as response:
                if response.status != 200:
                    errors.append(f"processor deployed asset returned HTTP {response.status}: {relative}")
                if relative.endswith(".wasm"):
                    mime = response.headers.get_content_type()
                    if mime != "application/wasm":
                        errors.append(f"deployed WASM has incorrect MIME type: {mime}")
                    length = response.headers.get("Content-Length")
                    if length and not response.headers.get("Content-Encoding") and length != str(FFMPEG_WASM_BYTES):
                        errors.append(f"deployed WASM has unexpected byte size: {length}")
        except URLError as exc:
            errors.append(f"processor deployed asset unavailable: {relative} ({exc.reason})")
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
