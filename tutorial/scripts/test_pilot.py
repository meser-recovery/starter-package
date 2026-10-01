"""Pilot boundary and paid-request cache tests; offline, no media mutations."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pilot
from narration import cached, content_hash, request_body
from serve_pilot import byte_range
from validate import ROOT


class PilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((ROOT / "content/historical/tutorial-N01-N08.yaml").read_text())

    def test_only_six_approved_scenes_and_three_variants(self):
        self.assertEqual(len(pilot.selection(self.spec)), 6)
        changed = copy.deepcopy(self.spec)
        changed["pilot"]["scene_ids"].append(changed["scenes"][6]["id"])
        with self.assertRaisesRegex(RuntimeError, "001–006"):
            pilot.selection(changed)

    def test_media_ranges_are_bounded_and_seekable(self):
        self.assertEqual(byte_range("bytes=2-5", 10), (2, 5))
        self.assertEqual(byte_range("bytes=5-", 10), (5, 9))
        self.assertEqual(byte_range("bytes=-3", 10), (7, 9))
        self.assertEqual(byte_range("bytes=0-99", 10), (0, 9))
        for value in ("bytes=10-", "bytes=4-2", "bytes=-0", "bytes=-", "bytes=0-1,4-5"):
            with self.assertRaises(ValueError):
                byte_range(value, 10)

    def test_neighbors_are_context_never_spoken_text(self):
        for variant in pilot.VARIANTS:
            for index, scene in enumerate(self.spec["scenes"][:6]):
                settings, context = pilot.parameters(self.spec, variant, scene)
                body = request_body(scene, settings, context)
                self.assertEqual(body["text"], scene["narration"])
                self.assertEqual(settings["voice_id"], self.spec["narration"]["voice_id"])
                self.assertEqual(settings["model_id"], self.spec["pilot"]["narration_profile"]["model_id"])
                if variant == "a-current":
                    self.assertEqual(context, {})
                else:
                    self.assertEqual(context["next_text"], self.spec["scenes"][index + 1]["narration"])
                    self.assertEqual(context.get("previous_text"), self.spec["scenes"][index - 1]["narration"] if index else None)

    def test_legacy_hash_unchanged_and_neighbors_invalidate(self):
        scene = self.spec["scenes"][1]
        settings = self.spec["narration"]
        legacy = {"text": scene["narration"], **{key: settings[key] for key in
                  ("voice_id", "model_id", "output_format", "voice_settings", "pronunciation")}}
        expected = hashlib.sha256(json.dumps(legacy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(content_hash(scene, settings), expected)
        context = {"previous_text": "Первый.", "next_text": "Третий."}
        hashes = {content_hash(scene, settings), content_hash(scene, settings, context),
                  content_hash(scene, settings, {**context, "previous_text": "Другой."}),
                  content_hash(scene, settings, {**context, "next_text": "Другой."})}
        self.assertEqual(len(hashes), 4)

    def test_context_cache_fails_closed(self):
        scene = self.spec["scenes"][1]
        settings = self.spec["narration"]
        context = {"previous_text": "До.", "next_text": "После."}
        with tempfile.TemporaryDirectory() as folder:
            cache_dir = Path(folder)
            data = b"test audio bytes"
            (cache_dir / f"{scene['id']}.mp3").write_bytes(data)
            chars = list(scene["narration"])
            record = {"narration_hash": content_hash(scene, settings, context),
                      "mp3_sha256": hashlib.sha256(data).hexdigest(), "duration_seconds": 30,
                      "alignment": {"characters": chars, "character_start_times_seconds": [0] * len(chars),
                                    "character_end_times_seconds": [1] * len(chars)}}
            (cache_dir / f"{scene['id']}.timing.json").write_text(json.dumps(record))
            with patch("narration.probe_duration", return_value=30):
                self.assertIsNotNone(cached(scene, settings, context=context, cache_dir=cache_dir))
                self.assertIsNone(cached(scene, settings, context={**context, "next_text": "Изменён."}, cache_dir=cache_dir))
                self.assertIsNone(cached(scene, settings, cache_dir=cache_dir))

    def test_unsupported_context_not_sent(self):
        with self.assertRaises(ValueError):
            request_body(self.spec["scenes"][0], self.spec["narration"], {"text": "Unapproved"})

    def test_changed_timing_moves_visual_cue(self):
        scene = self.spec["scenes"][1]
        n = len(scene["narration"])
        timing = {"duration_seconds": n * .01 + 1,
                  "alignment": {"character_start_times_seconds": [i * .01 for i in range(n)]}}
        cues = pilot.cue_times(self.spec, scene, timing)
        for second, phase in cues:
            self.assertAlmostEqual(pilot.phase_at(second, cues), phase)

    def test_protected_artifact_mutation_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "generated").mkdir()
            media = root / "generated/007.mp4"
            media.write_bytes(b"old")
            with patch.object(pilot, "ROOT", root), patch.object(pilot, "OUT", root / "generated/pilot"), patch.object(pilot, "head", return_value="baseline"):
                with self.assertRaisesRegex(RuntimeError, "baseline missing"):
                    pilot.preserve(self.spec)
                self.assertEqual(pilot.preserve(self.spec, initialize=True)["protected_files"], 1)
                media.write_bytes(b"new")
                with self.assertRaisesRegex(RuntimeError, "modified protected artifact"):
                    pilot.preserve(self.spec)


if __name__ == "__main__":
    unittest.main()
