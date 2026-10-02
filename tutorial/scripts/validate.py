#!/usr/bin/env python3
"""Fail-closed S11 audio content validation against the approved Content Pack."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from content_model import approved_structure

ROOT = Path(__file__).resolve().parents[1]
APPROVED_PACK_SHA256 = "d4be28dda0d9c021f211e25111e0873273ff8f2197052aab8275f0e8996e1ad1"


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
    types = schema.get("type")
    if types:
        types = [types] if isinstance(types, str) else types
        tests = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
                 "string": lambda v: isinstance(v, str),
                 "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
                 "null": lambda v: v is None}
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
        for i, item in enumerate(value):
            if "items" in schema:
                schema_check(item, schema["items"], root, f"{path}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            fail(f"schema {path}: empty string")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            fail(f"schema {path}: pattern mismatch")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")):
            fail(f"schema {path}: below minimum")


def validate(spec_path: Path = ROOT / "tutorial.yaml") -> dict:
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas/tutorial.schema.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        fail(f"spec/schema unreadable: {error}")
    schema_check(spec, schema, schema)
    source = spec["tutorial"]["canonical_content"]["source"]
    pack_path = (ROOT / source).resolve()
    if not pack_path.is_relative_to(ROOT) or not pack_path.is_file():
        fail("Canonical Content Pack path unresolved")
    raw = pack_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != APPROVED_PACK_SHA256 or digest != spec["tutorial"]["canonical_content"]["sha256"]:
        fail("Canonical Content Pack identity/hash changed")
    try:
        canonical, approved = approved_structure(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        fail(str(error))
    blocks = spec["narration_modules"]
    scenes = spec["scenes"]
    expected_order = [b["id"] for b in approved]
    if spec["review_policy"]["block_order"] != expected_order:
        fail("review block order changed")
    if [b["id"] for b in blocks] != expected_order:
        fail("block membership/order changed")
    expected_ids = []
    scene_index = 0
    for block, source_block in zip(blocks, approved):
        bid = block["id"]
        for key, expected in (("title", source_block["title"]),
                              ("canonical_start_offset", source_block["start"]),
                              ("canonical_end_offset", source_block["end"]),
                              ("narration", source_block["narration"])):
            if block[key] != expected:
                fail(f"{bid} {key} differs from approved source")
        if bid == "B01":
            tts = block.get("tts")
            if not tts or tts["opening_tag"] != "[slowly]":
                fail("B01 delivery settings invalid")
            pauses = tts["pauses"]
            if [p["after_offset"] for p in pauses] != [450, 795, 999, 1409, 1699, 1902] or any(
                not isinstance(p["after_offset"], int)
                or block["narration"][p["after_offset"]-2:p["after_offset"]] != "\n\n"
                or not p["reason"].strip() for p in pauses
            ):
                fail("B01 TTS pauses must match the reviewed semantic transitions")
        elif "tts" in block:
            tts = block["tts"]
            pauses = tts["pauses"]
            offsets = [p["after_offset"] for p in pauses]
            if (tts.get("semantic_reviewed") is not True or tts["opening_tag"] not in ("", "[slowly]")
                    or offsets != sorted(set(offsets))
                    or any(not isinstance(p["after_offset"], int)
                           or p["after_offset"] <= 0
                           or p["after_offset"] >= len(block["narration"])
                           or not (block["narration"][p["after_offset"]-1].isspace()
                                   or block["narration"][p["after_offset"]].isspace())
                           or len(p["reason"].strip()) < 12 for p in pauses)):
                fail(f"{bid} needs a reviewed, reasoned semantic pause map")
        expected_block_ids = [f"{bid}-{number:03d}" for number, _ in source_block["scene_units"]]
        expected_ids.extend(expected_block_ids)
        if block["scene_ids"] != expected_block_ids:
            fail(f"{bid} scene membership/order changed")
        previous_end = 0
        for (number, description), sid in zip(source_block["scene_units"], expected_block_ids):
            scene = scenes[scene_index]
            scene_index += 1
            if scene["id"] != sid or scene["block_id"] != bid or scene["number"] != number:
                fail(f"scene ID/block/number differs from approved map: {sid}")
            if scene["goal"] != description:
                fail(f"scene goal differs from approved map: {sid}")
            start, end = scene["start_offset"], scene["end_offset"]
            if not isinstance(start, int) or not isinstance(end, int) or start != previous_end or end <= start or end > len(block["narration"]):
                fail(f"missing, duplicated or reordered fragment: {sid}")
            if scene["narration"] != block["narration"][start:end] or not scene["narration"].strip():
                fail(f"scene narration differs from approved fragment: {sid}")
            if scene["captions"]:
                fail(f"unapproved caption: {sid}")
            previous_end = end
        if previous_end != len(block["narration"]):
            fail(f"incomplete block narration: {bid}")
    if [s["id"] for s in scenes] != expected_ids or scene_index != 54:
        fail("scene order or count changed")
    return {"status": "PASS", "pack_path": str(pack_path), "pack_sha256": digest,
            "block_count": 14, "scene_count": 54, "canonical_characters": len(canonical)}


if __name__ == "__main__":
    try:
        print(json.dumps(validate(), ensure_ascii=False, indent=2))
    except ContentDrift as error:
        raise SystemExit(str(error)) from None
