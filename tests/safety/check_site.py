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
        ("Зависимый ли я?", "https://na.org/wp-content/uploads/2024/05/RU3107-IP-7-Russian.pdf"),
        ("Новичку", "https://na.org/wp-content/uploads/2024/05/RU3116-IP-16-Russian.pdf"),
        ("Кто, что, как и почему", "https://na.org/wp-content/uploads/2024/05/RU3107-IP-7-Russian.pdf"),
        ("Добро пожаловать в Сообщество АН", "https://na.org/wp-content/uploads/2024/05/RU3122-IP-22-Russian.pdf"),
        ("Треугольник одержимости", "https://na.org/wp-content/uploads/2024/05/RU3112-IP-12-Russian.pdf"),
        ("Юным зависимым от юных зависимых", "https://na.org/wp-content/uploads/2024/05/RU3113_final_Apr2017-IP-13-Russian.pdf"),
        ("Дополнительная литература", "https://na-russia.org/literatures?category=recovery-literature"),
    ]
    action_hrefs = [attrs.get("href") for attrs in actions]
    if action_hrefs != [href for _label, href in expected_actions]:
        errors.append("Literature.html: resource action destinations changed or are out of order")
    if len(actions) != len(expected_actions):
        errors.append("Literature.html: expected seven resource actions")
    for attrs in actions:
        if attrs.get("target") == "_blank" and not {"noopener", "noreferrer"}.issubset(set((attrs.get("rel") or "").split())):
            errors.append("Literature.html: target blank resource action lacks safe rel semantics")


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
    check_literature_contract(errors)
    check_audiobook_contract(errors)
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
