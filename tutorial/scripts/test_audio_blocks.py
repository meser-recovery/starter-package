"""Offline S11 audio-first mapping, alignment and review-gate regressions."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import modules
import build
from audio_approval import scene_timing as approved_scene_timing, validate_approval
from content_model import approved_structure
from validate import ContentDrift, ROOT, validate


class AudioBlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((ROOT / "tutorial.yaml").read_text())

    def changed(self, mutate):
        spec = copy.deepcopy(self.spec)
        mutate(spec)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=ROOT, delete=False) as file:
            json.dump(spec, file, ensure_ascii=False)
            path = Path(file.name)
        try:
            with self.assertRaisesRegex(ContentDrift, "CONTENT_DRIFT"):
                validate(path)
        finally:
            path.unlink(missing_ok=True)

    def test_exact_approved_mapping(self):
        result = validate()
        self.assertEqual((result["block_count"], result["scene_count"]), (14, 54))
        canonical, approved = approved_structure((ROOT / "content/meser-audio-tutorial-canonical-content-pack.md").read_text())
        self.assertEqual(self.spec["narration_modules"][0]["narration"], approved[0]["narration"])
        self.assertEqual(self.spec["narration_modules"][-1]["narration"][-20:], "Спасибо за внимание.")
        self.assertEqual([s["id"] for s in self.spec["scenes"][:3]], ["B01-001", "B01-002", "B01-003"])
        self.assertEqual(len(canonical), result["canonical_characters"])

    def test_content_drift_rejects_phrase_gap_duplicate_order_title_scene_caption_hash(self):
        self.changed(lambda s: s["scenes"][0].__setitem__("narration", "Привет."))
        self.changed(lambda s: s["scenes"][1].__setitem__("start_offset", s["scenes"][1]["start_offset"] + 1))
        self.changed(lambda s: s["scenes"][1].__setitem__("start_offset", s["scenes"][1]["start_offset"] - 1))
        self.changed(lambda s: s["scenes"].__setitem__(slice(0, 2), list(reversed(s["scenes"][:2]))))
        self.changed(lambda s: s["narration_modules"][0].__setitem__("title", "Другой заголовок"))
        self.changed(lambda s: s["scenes"][0].__setitem__("block_id", "B02"))
        self.changed(lambda s: s["scenes"][0].__setitem__("goal", "Другая сцена"))
        self.changed(lambda s: s["scenes"][0]["captions"].append("Новый титр"))
        self.changed(lambda s: s["tutorial"]["canonical_content"].__setitem__("sha256", "0" * 64))

    def test_one_continuous_request_and_scene_alignment(self):
        block = self.spec["narration_modules"][0]
        body = modules.request_body(self.spec, block)
        self.assertTrue(body["text"].startswith("[calm] [conversational] [slowly]\n"))
        self.assertEqual(body["voice_settings"], {"stability": 0.5})
        text, indices = modules.request_text_and_indices(self.spec, block)
        self.assertEqual(text, body["text"])
        self.assertEqual("".join(text[i] for i in indices), block["narration"])
        self.assertEqual(text.count("[pause]"), 6)
        self.assertEqual(text.count("[slowly]"), 1)
        self.assertIn("Привет. Позвольте", text)
        self.assertNotIn(block["title"], body["text"])
        text = body["text"]
        length = len(text)
        alignment = {"characters": list(text),
                     "character_start_times_seconds": [i * .05 for i in range(length)],
                     "character_end_times_seconds": [(i + 1) * .05 for i in range(length)]}
        timing = modules.map_timing(self.spec, block, alignment, length * .05)
        self.assertEqual(len(timing["scenes"]), 3)
        self.assertEqual(timing["scenes"][0]["range_start_seconds"], 0)
        self.assertEqual(timing["scenes"][-1]["range_end_seconds"], length * .05)
        self.assertEqual("".join(s["narration"] for s in modules.members(self.spec, block)), block["narration"])
        with patch.object(modules, "cached", return_value={"timing": timing, "metadata": {"audio_sha256": "fixture"}}):
            for scene in modules.members(self.spec, block):
                local = modules.scene_timing(self.spec, scene)["alignment"]
                self.assertEqual("".join(local["characters"]), scene["narration"])
                self.assertNotIn("[pause]", "".join(local["characters"]))
        broken = copy.deepcopy(alignment)
        broken["characters"][0] = "X"
        with self.assertRaises(RuntimeError):
            modules.map_timing(self.spec, block, broken, length * .05)

    def test_b01_tts_markup_stays_outside_canonical_source(self):
        self.changed(lambda s: s["narration_modules"][0]["tts"]["pauses"].pop())
        self.changed(lambda s: s["narration_modules"][0]["tts"]["pauses"][0].__setitem__("reason", ""))
        self.changed(lambda s: s["narration_modules"][0]["tts"]["pauses"][0].__setitem__("after_offset", 7))
        self.changed(lambda s: s["narration_modules"][1].__setitem__("tts", copy.deepcopy(s["narration_modules"][0]["tts"])))

    def test_hash_scope_and_selection(self):
        blocks = self.spec["narration_modules"]
        before = [modules.narration_hash(self.spec, b) for b in blocks]
        self.assertEqual([b["id"] for b in modules.selection(self.spec, module_id="B01")], ["B01"])
        changed = copy.deepcopy(self.spec)
        changed["scenes"][0]["end_offset"] += 1
        self.assertEqual([i for i, b in enumerate(changed["narration_modules"])
                          if modules.narration_hash(changed, b) != before[i]], [0])
        changed = copy.deepcopy(self.spec)
        changed["narration_modules"][1]["pronunciation_dictionary_locators"] = [
            {"pronunciation_dictionary_id": "example", "version_id": "v2"}]
        self.assertEqual([i for i, b in enumerate(changed["narration_modules"])
                          if modules.narration_hash(changed, b) != before[i]], [1])

    def test_approved_b01_never_spends_even_with_force(self):
        with tempfile.TemporaryDirectory() as folder:
            rows = modules.plan(self.spec, [self.spec["narration_modules"][0]], force=True, root=Path(folder))
        self.assertEqual(rows["tts_requests"], 0)
        self.assertEqual(rows["modules"][0]["cache"], "APPROVED")
        with self.assertRaisesRegex(RuntimeError, "approved and immutable"):
            modules.generate(self.spec, self.spec["narration_modules"][0], force=True)
        self.assertEqual(len([r for r in rows["modules"] if not r["selected"]]), 13)

    def test_audio_review_gate_rejects_other_blocks_before_provider_call(self):
        with patch("sys.argv", ["build.py", "narration", "--module", "B02"]), patch.object(build, "generate") as provider:
            with self.assertRaisesRegex(RuntimeError, "complete block approval"):
                build.main()
            provider.assert_not_called()

    def test_b01_approval_preserves_pcm_and_shifted_scene_alignment(self):
        if not (ROOT / "generated/narration-blocks-v2/B01/B01-six-pauses.mp3").is_file():
            self.skipTest("approved large audio is an ignored local review artifact")
        approval = validate_approval(self.spec, "B01")
        self.assertEqual(approval["record"]["status"], "AUDIO_APPROVED")
        self.assertEqual(len(approval["record"]["insertions"]), 6)
        for scene in self.spec["scenes"][:3]:
            timing = approved_scene_timing(self.spec, scene, approval)
            self.assertEqual("".join(timing["alignment"]["characters"]), scene["narration"])
            self.assertGreater(timing["duration_seconds"], 0)

    def test_later_block_requires_manual_semantic_map_without_copying_b01_tags(self):
        spec = copy.deepcopy(self.spec)
        block = spec["narration_modules"][1]
        offset = block["narration"].index("Запись в режиме")
        block["tts"] = {"opening_tag": "", "semantic_reviewed": True,
                        "pauses": [{"after_offset": offset,
                                    "reason": "Объяснение двух режимов записи закончено; далее показаны преимущества раздельных дорожек."}]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=ROOT, delete=False) as file:
            json.dump(spec, file, ensure_ascii=False)
            path = Path(file.name)
        try:
            self.assertEqual(validate(path)["status"], "PASS")
        finally:
            path.unlink(missing_ok=True)
        request, indices = modules.request_text_and_indices(spec, block)
        self.assertEqual(request.count("[pause]"), 1)
        self.assertNotIn("[slowly]", request)
        self.assertEqual("".join(request[i] for i in indices), block["narration"])


if __name__ == "__main__":
    unittest.main()
