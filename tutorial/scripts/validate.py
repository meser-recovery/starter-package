#!/usr/bin/env python3
"""Mechanical schema and approved-content checks. No semantic rewrite judge."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPROVED_PACK_SHA256 = "523c29b093a40ac3b1f3c6fc07d4058a9275ed3e0c3883efd0876af033e59c03"
REQUIRED_ANIMATIONS = {
    "zoom-multitrack", "archive-hierarchy", "one-translator",
    "multiple-translators", "project-vs-final", "summary",
}


class ContentDrift(ValueError):
    pass


def fail(message: str) -> None:
    raise ContentDrift(f"CONTENT_DRIFT: {message}")


def schema_check(value, schema, root, path="$" ):
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            fail(f"unsupported schema reference at {path}")
        return schema_check(value, root["$defs"][ref.split("/")[-1]], root, path)
    if "const" in schema and value != schema["const"]:
        fail(f"schema {path}: expected {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        fail(f"schema {path}: value outside enum")
    types = schema.get("type")
    if types:
        types = [types] if isinstance(types, str) else types
        tests = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "null": lambda v: v is None,
        }
        if not any(tests[t](value) for t in types):
            fail(f"schema {path}: expected {types}")
    if isinstance(value, dict):
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            fail(f"schema {path}: missing {sorted(missing)}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - props.keys():
            fail(f"schema {path}: unknown keys {sorted(set(value) - props.keys())}")
        for key, child in props.items():
            if key in value:
                schema_check(value[key], child, root, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            fail(f"schema {path}: item count")
        for i, child in enumerate(schema.get("prefixItems", [])):
            if i < len(value):
                schema_check(value[i], child, root, f"{path}[{i}]")
        if "items" in schema:
            for i, item in enumerate(value):
                schema_check(item, schema["items"], root, f"{path}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            fail(f"schema {path}: empty string")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            fail(f"schema {path}: pattern mismatch")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")):
            fail(f"schema {path}: below minimum")


def canonical_items(pack: str):
    try:
        narration = pack.split("# PART A · Canonical Russian Narration", 1)[1].split("# PART B", 1)[0]
        storyboard = pack.split("# PART B · Approved Storyboard / Visual Coverage", 1)[1].split("# PART C", 1)[0]
        captions = pack.split("# PART D · On-screen captions", 1)[1].split("# PART E", 1)[0]
    except IndexError:
        fail("Canonical Content Pack sections missing")
    paragraphs = [p.strip() for p in narration.split("\n\n")
                  if p.strip() and p.strip() != "---" and not p.strip().startswith("## ")]
    rows = {}
    for line in storyboard.splitlines():
        match = re.match(r"^\| (\d+) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$", line)
        if match:
            number, meaning, goal, visual_type, target = match.groups()
            rows[f"b{int(number):03d}"] = {"meaning": meaning, "goal": goal, "type": visual_type, "target": target}
    blocks = {match.group(1): match.group(2).strip() for match in
              re.finditer(r"## (.*?)\n\n```text\n(.*?)\n```", captions, re.S)}
    return {f"n{i:03d}": text for i, text in enumerate(paragraphs, 1)}, rows, blocks


def validate(spec_path: Path = ROOT / "tutorial.yaml") -> dict:
    # JSON is a strict YAML 1.2 subset; this avoids an extra parser dependency.
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/tutorial.schema.json").read_text(encoding="utf-8"))
    schema_check(spec, schema, schema)
    source = spec["tutorial"]["canonical_content"]["source"]
    pack_path = (ROOT / source).resolve()
    if not pack_path.is_relative_to(ROOT) or not pack_path.is_file():
        fail("Canonical Content Pack path unresolved")
    raw = pack_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != APPROVED_PACK_SHA256 or digest != spec["tutorial"]["canonical_content"]["sha256"]:
        fail("Canonical Content Pack identity/hash changed")
    paragraphs, rows, blocks = canonical_items(raw.decode("utf-8"))
    if len(paragraphs) != 132 or len(rows) != 60:
        fail("approved narration/storyboard count changed")
    ids, used_narration, used_storyboard, seen_animations = set(), [], [], set()
    chapters = spec["tutorial"]["chapters"]
    if len(chapters) != len(set(chapters)) or len(chapters) != 9:
        fail("chapter coverage changed")
    if len(spec["scenes"]) != 60:
        fail("required storyboard scenes missing")
    for scene in spec["scenes"]:
        sid = scene["id"]
        if sid in ids:
            fail(f"duplicate scene ID: {sid}")
        ids.add(sid)
        if scene["chapter"] not in chapters:
            fail(f"unknown chapter: {sid}")
        refs = scene["canonical_refs"]
        nrefs, brefs, crefs = refs["narration"], refs["storyboard"], refs["captions"]
        if any(ref not in paragraphs for ref in nrefs) or any(ref not in rows for ref in brefs):
            fail(f"unresolved canonical refs: {sid}")
        if any(ref not in blocks for ref in crefs):
            fail(f"unresolved caption refs: {sid}")
        if scene["narration"] != "\n\n".join(paragraphs[ref] for ref in nrefs):
            fail(f"narration differs from approved text: {sid}")
        if scene["captions"] != [blocks[ref] for ref in crefs]:
            fail(f"caption differs from approved text: {sid}")
        if len(brefs) != 1 or scene["visual"]["goal"] != rows[brefs[0]]["goal"]:
            fail(f"visual goal differs from storyboard: {sid}")
        if scene["expected_state"] != rows[brefs[0]]["meaning"]:
            fail(f"scene meaning differs from storyboard: {sid}")
        if scene["target_seconds"] != rows[brefs[0]]["target"]:
            fail(f"scene timing reference differs from storyboard: {sid}")
        if scene["transforms"]:
            fail(f"transform requires explicit fragment mapping: {sid}")
        if scene["fixture_set"] not in (None, "synthetic-zoom-v1"):
            fail(f"unresolved fixture set: {sid}")
        used_narration.extend(nrefs)
        used_storyboard.extend(brefs)
        if scene["visual"]["animation"]:
            seen_animations.add(scene["visual"]["animation"])
    if sorted(used_narration) != sorted(paragraphs):
        fail("unmapped or duplicated narration")
    if sorted(used_storyboard) != sorted(rows):
        fail("missing or duplicated storyboard scene")
    if not REQUIRED_ANIMATIONS.issubset(seen_animations):
        fail("required explanatory animation missing")
    for scene in spec["scenes"]:
        if any(dep not in ids for dep in scene["dependencies"]):
            fail(f"unresolved scene dependency: {scene['id']}")
    return {"status": "PASS", "pack_path": str(pack_path), "pack_sha256": digest,
            "scene_count": len(ids), "chapter_count": len(chapters), "paragraph_count": len(paragraphs)}


if __name__ == "__main__":
    try:
        print(json.dumps(validate(), ensure_ascii=False, indent=2))
    except ContentDrift as error:
        raise SystemExit(str(error)) from None
