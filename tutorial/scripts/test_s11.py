#!/usr/bin/env python3
"""Deterministic S11 content and cache safety tests; no paid or browser calls."""
from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fixtures import generate
from narration import content_hash
from validate import ContentDrift, ROOT, validate


class TutorialSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((ROOT / "tutorial.yaml").read_text())

    def altered(self, mutate):
        spec = copy.deepcopy(self.spec)
        mutate(spec)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", dir=ROOT, delete=False) as file:
            json.dump(spec, file, ensure_ascii=False)
            path = Path(file.name)
        try:
            with self.assertRaisesRegex(ContentDrift, "CONTENT_DRIFT"):
                validate(path)
        finally:
            path.unlink(missing_ok=True)

    def test_approved_pack_and_complete_mapping(self):
        result = validate()
        self.assertEqual((result["scene_count"], result["chapter_count"], result["paragraph_count"]), (60, 9, 133))

    def test_narration_rewrite_fails_closed(self):
        self.altered(lambda spec: spec["scenes"][0].__setitem__("narration", "Другой текст"))

    def test_caption_rewrite_fails_closed(self):
        self.altered(lambda spec: spec["scenes"][15]["captions"].__setitem__(0, "Другой титр"))

    def test_storyboard_goal_rewrite_fails_closed(self):
        self.altered(lambda spec: spec["scenes"][37]["visual"].__setitem__("goal", "Другая функция"))

    def test_missing_scene_or_ref_fails_closed(self):
        self.altered(lambda spec: spec["scenes"].pop())
        self.altered(lambda spec: spec["scenes"][0]["canonical_refs"]["narration"].__setitem__(0, "n999"))

    def test_narration_hash_covers_all_settings(self):
        scene = self.spec["scenes"][0]
        settings = self.spec["narration"]
        baseline = content_hash(scene, settings)
        for key, value in (("voice_id", "other"), ("model_id", "other"), ("output_format", "other"),
                           ("voice_settings", {"stability": 1}), ("pronunciation", {"dictionary": "v2"})):
            changed = {**settings, key: value}
            self.assertNotEqual(content_hash(scene, changed), baseline)
        self.assertNotEqual(content_hash({**scene, "narration": scene["narration"] + " "}, settings), baseline)

    def test_fixture_generation_is_byte_deterministic(self):
        # Tests must not rewrite the full tutorial's protected working fixtures.
        with tempfile.TemporaryDirectory() as folder, patch("fixtures.OUTPUT_DIR", Path(folder)):
            first = generate()
            second = generate()
        self.assertEqual(first, second)
        self.assertEqual(len(first["track_sha256"]), 4)

    def test_no_secret_like_values_in_tutorial_source(self):
        pattern = re.compile(rb"(?:sk[-_]|ghp_|github_pat_)[A-Za-z0-9_-]{20,}|ELEVENLABS_API_KEY\s*=\s*[^\s\"']")
        sources = [path for path in ROOT.rglob("*") if path.is_file() and
                   not {"generated", "__pycache__"}.intersection(path.parts) and path.suffix != ".pyc"]
        self.assertFalse([str(path) for path in sources if pattern.search(path.read_bytes())])


if __name__ == "__main__":
    unittest.main()
