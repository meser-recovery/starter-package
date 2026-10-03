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
from audio_approval import scene_timing as approved_scene_timing, validate_approval, validate_block_approval
from b01_block import check_embedded_subtitles
from b10_block import opening_scroll_pixels_in_mp4
from b03_block import pointer_pixels_in_mp4
from b04_block import pointer_check as b04_pointer_check
from b05_block import pointer_pixels_in_mp4 as b05_pointer_check
from b06_block import pointer_pixels_in_mp4 as b06_pointer_check
from b07_block import pointer_pixels_in_mp4 as b07_pointer_check, visual_transition_anomalies
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

    def test_audio_review_gate_rejects_b11_before_provider_call(self):
        with patch("sys.argv", ["build.py", "narration", "--module", "B11"]), patch.object(build, "generate") as provider:
            with self.assertRaisesRegex(RuntimeError, "complete block approval"):
                build.main()
            provider.assert_not_called()

    def test_b09_shortened_take_and_block_approval_are_exact(self):
        audio = validate_approval(self.spec, 'B09')['record']
        block = validate_block_approval('B09')
        self.assertEqual(audio['status'], 'AUDIO_APPROVED')
        self.assertEqual(audio['approved_take']['mp3_sha256'],
                         '4ab57ad66510b260e565d8ec5187631e8e2977d82e22824f148af5af27313750')
        self.assertEqual(audio['approved_take']['alignment_sha256'],
                         'c7991291bae2f4f7b54141f9c43af8fc1e39443179f356bbdc4184cff34ee247')
        self.assertEqual(block['status'], 'BLOCK_APPROVED')
        self.assertEqual(block['video_sha256'],
                         '5776bf60053d09fad28e0879119e5a9e41bf4daf294e72f411fb465dac2e10d0')
        self.assertEqual(block['embedded_subtitle_cues'], 36)

    def test_b10_opening_scroll_rejects_prior_pre_scrolled_mp4(self):
        history = ROOT / 'generated/b10-block-review/history/rejected-69ce928b/B10.mp4'
        evidence = json.loads((ROOT / 'generated/b10-block-review/scenes/B10-035.json').read_text())
        scroll = next(e for e in evidence['choreography']['events']
                      if e['type'] == 'intentional-button-scroll')
        with self.assertRaisesRegex(RuntimeError, 'does not show smooth opening scroll'):
            opening_scroll_pixels_in_mp4(history, scroll)

    def test_b08_block_approval_pins_audio_alignment_and_subtitles(self):
        state = validate_block_approval('B08')
        self.assertEqual(state['status'], 'BLOCK_APPROVED')
        self.assertEqual(state['video_sha256'], '22ef673a36f21cf8773301fd20d9ee97e2f6e30708c84267980b8132d644e8ca')
        self.assertEqual(state['approved_mp3_sha256'], '0af16c674ec8c52f1c5bf830ad10a05b09d2ea9bdcb23f4b01ba8d93128ede4d')
        self.assertEqual(state['approved_alignment_sha256'], '070e408662743f1400b79d2fc704ef14abcbb884004e18aaeeb2af843e5fd021')
        self.assertEqual(state['embedded_subtitle_cues'], 26)

    def test_b01_revised_video_approved_and_prior_version_historical(self):
        history = ROOT / 'approvals/historical/B01-block-approved-2026-10-02.json'
        old = json.loads(history.read_text())
        self.assertEqual(old['video_sha256'], '90b1d7b28c67b623455b6d25da54184c9cf6cfa762a9935d2c091432994e3c51')
        self.assertEqual(old['embedded_subtitle_cues'], 34)
        state = validate_block_approval('B01')
        self.assertEqual(state['status'], 'BLOCK_APPROVED')
        self.assertEqual(state['video_sha256'], '8cf72d8e2b081eff6f6c4714410fa0cc901dfb09d8efa2148cb3236efa32e032')
        self.assertEqual(state['approved_mp3_sha256'], '93481d42dc3c722f2014ac01bd4369185d6d6991b6809e3ab7dd123f78e54377')
        self.assertEqual(state['subtitle_srt_sha256'], 'c0ad60bd5a1f23dea186674e6bbee913b0e3663dc75fc0fd8a4fe71df9f0b3d9')
        self.assertEqual(state['embedded_subtitle_cues'], 34)

    def test_b02_block_approval_pins_audio_alignment_and_subtitles(self):
        state = validate_block_approval('B02')
        self.assertEqual(state['status'], 'BLOCK_APPROVED')
        self.assertEqual(state['video_sha256'], '8f2f930e096dcb3a9615d047ea5901e7346b65046aee1b27b473387dc0cbd993')
        self.assertEqual(state['approved_mp3_sha256'], '19d93e92c574e7be09fd603390430e3ce7ce1e803752aec703087214c7ec98c4')
        self.assertEqual(state['approved_alignment_sha256'], 'bda48ae45818e2781b06fe3384eb69c0270623d8a2cfbf82aa99bbedd73ec817')
        self.assertEqual(state['embedded_subtitle_cues'], 40)

    def test_b03_block_approval_pins_audio_alignment_and_subtitles(self):
        state = validate_block_approval('B03')
        self.assertEqual(state['status'], 'BLOCK_APPROVED')
        self.assertEqual(state['video_sha256'], '6535356a17c3b2cb885a423a41418ac3ca6616d97b32568f1512e485966d6206')
        self.assertEqual(state['approved_mp3_sha256'], '5bf198675f2f3f9c0e24e759418034d0558020318ccde5182554da5523faec9a')
        self.assertEqual(state['approved_alignment_sha256'], '7f01cd1d688f828803314b3a21812594c8cdad6b12a0988a4f15c2df1d9584d1')
        self.assertEqual(state['subtitle_srt_sha256'], 'c8d10fdb6016abcf70559d02f21d17d22531171ad301db335f11989cd7b3d543')
        self.assertEqual(state['embedded_subtitle_cues'], 8)

    def test_b04_block_approval_pins_audio_alignment_and_subtitles(self):
        state = validate_block_approval('B04')
        self.assertEqual(state['status'], 'BLOCK_APPROVED')
        self.assertEqual(state['video_sha256'], 'f14978c373710fd5b8e5a579a4f718079ada4ea1e0ffd2dd24409d80a52b99bb')
        self.assertEqual(state['approved_mp3_sha256'], '6472a15a2ed87fbc654d265f54e34f0e6412bd8b3bba0214fe41f73f94214dfd')
        self.assertEqual(state['approved_alignment_sha256'], '3fe1b93d9085b1d60a58b5f11b35c49f55c024d180a29aa195ba5ad2a3bcd242')
        self.assertEqual(state['subtitle_srt_sha256'], '0ebb613fd7bc21a997e9bcb575d54e9fcf4a9ae39bdd33a89d042c71e8c1f623')
        self.assertEqual(state['embedded_subtitle_cues'], 2)

    def test_b05_block_approval_pins_audio_alignment_and_subtitles(self):
        state = validate_block_approval('B05')
        self.assertEqual(state['status'], 'BLOCK_APPROVED')
        self.assertEqual(state['video_sha256'], '04c281e73e288b9b8fc104b13af3c1a9dd23d64be159ac1a29dec36e4de8ff31')
        self.assertEqual(state['approved_mp3_sha256'], '261a2b47ec477aa30734cee3329d09eaea9b7ab06382f89a6053bca35a454db7')
        self.assertEqual(state['approved_alignment_sha256'], 'd7dfc506c5f2f60e416921ca546b0d2b84661ae196afe248541a22082867d9a7')
        self.assertEqual(state['subtitle_srt_sha256'], '22e7c165ed12f0f1c3d953a1a26253ce930b9e65e75988a1c808ac3cca31b9a0')
        self.assertEqual(state['embedded_subtitle_cues'], 19)

    def test_b06_block_approval_pins_audio_alignment_and_subtitles(self):
        state = validate_block_approval('B06')
        self.assertEqual(state['status'], 'BLOCK_APPROVED')
        self.assertEqual(state['video_sha256'], '452afd7e19e1ecbc1542c1e42d00f03de5366f51d5fb802f2e445df9b2970ace')
        self.assertEqual(state['approved_mp3_sha256'], 'c560975d78563940a1663ddb250a354fb0ddf825efec1c82af64fc019d5e5422')
        self.assertEqual(state['approved_alignment_sha256'], '9d29d74893b89eb2fdec0933a0390ca7f52f5afda9d2cf3531ba1df14d373acb')
        self.assertEqual(state['subtitle_srt_sha256'], '1cc04884d0dee793b3f05a777e931a115e3d51473206f8998963c2cd0d7583d8')
        self.assertEqual(state['embedded_subtitle_cues'], 16)

    def test_b07_block_approval_pins_audio_alignment_and_subtitles(self):
        state = validate_block_approval('B07')
        self.assertEqual(state['status'], 'BLOCK_APPROVED')
        self.assertEqual(state['video_sha256'], '7055e5a42dc4616ab8fd1a6d504038ef849d447218f812eaec39e2b75ae7c577')
        self.assertEqual(state['approved_mp3_sha256'], '9c6277db32d5e9cd3e9b73e542e2e57a104e0b332460dacd484865f0e493e0fd')
        self.assertEqual(state['approved_alignment_sha256'], '75f4de59bbf98be8d126161d98e43961fe7d5bb6f25ec0979ced9b9003893eb5')
        self.assertEqual(state['subtitle_srt_sha256'], '6b85456f43db2c6fd4f215ffa03c694f8887547620d20817c2d7bca03481b23b')
        self.assertEqual(state['embedded_subtitle_cues'], 34)

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

    def test_embedded_mp4_subtitles_reject_missing_final_cue(self):
        source = ('1\n00:00:01,000 --> 00:00:02,000\nПервый.\n\n'
                  '2\n00:00:02,100 --> 00:00:03,000\nи «Спикерская».\n')
        with tempfile.TemporaryDirectory() as folder:
            srt = Path(folder) / 'source.srt'
            srt.write_text(source)
            with patch('b01_block.subprocess.check_output', return_value=source.split('\n\n')[0] + '\n'):
                with self.assertRaisesRegex(RuntimeError, 'incomplete: 1/2 cues'):
                    check_embedded_subtitles(Path(folder) / 'candidate.mp4', srt, 'Первый. и «Спикерская».')
            with patch('b01_block.subprocess.check_output', return_value=source):
                result = check_embedded_subtitles(Path(folder) / 'candidate.mp4', srt, 'Первый. и «Спикерская».')
                self.assertEqual(result['embedded_subtitle_cues'], 2)
                self.assertEqual(result['last_embedded_subtitle_end_seconds'], 3.0)

    def test_b03_rendered_clicks_reject_previous_candidate(self):
        current = ROOT / 'generated/b03-block-review'
        previous = current / 'history/pre-pointer-fix'
        if not (current / 'B03.mp4').is_file() or not (previous / 'B03.mp4').is_file():
            self.skipTest('large B03 review candidates are ignored local artifacts')
        scene_start = 511 / 30
        fixed_evidence = json.loads((current / 'scenes/B03-009.json').read_text())
        checks = pointer_pixels_in_mp4(current / 'B03.mp4', fixed_evidence, scene_start)
        self.assertEqual([row['status'] for row in checks], ['PASS', 'PASS'])
        old_evidence = json.loads((previous / 'scenes/B03-009.json').read_text())
        with self.assertRaisesRegex(RuntimeError, 'outside its rendered button in MP4'):
            pointer_pixels_in_mp4(previous / 'B03.mp4', old_evidence, scene_start)

    def test_b04_click_uses_rendered_button_and_hides_cursor(self):
        folder = ROOT / 'generated/b04-block-review'
        if not (folder / 'B04.mp4').is_file():
            self.skipTest('large B04 review candidate is an ignored local artifact')
        evidence = json.loads((folder / 'scenes/B04-010.json').read_text())
        check = b04_pointer_check(folder / 'B04.mp4', evidence)
        self.assertEqual(check['status'], 'PASS')
        self.assertEqual(check['pointer_dark_pixels_after_context_change'], 0)
        broken = copy.deepcopy(evidence)
        arrival = next(e for e in broken['choreography']['events'] if e['type'] == 'cursor-arrival')
        arrival['box']['x'] += 500
        with self.assertRaisesRegex(RuntimeError, 'click misses rendered button'):
            b04_pointer_check(folder / 'B04.mp4', broken)

    def test_b05_context_clicks_use_rendered_buttons_and_hide_cursor(self):
        folder = ROOT / 'generated/b05-block-review'
        if not (folder / 'B05.mp4').is_file():
            self.skipTest('large B05 review candidate is an ignored local artifact')
        evidence = json.loads((folder / 'scenes/B05-014.json').read_text())
        checks = b05_pointer_check(folder / 'B05.mp4', evidence, 1730 / 30,
                                   'B05-014', folder / 'qa-clicks/B05-014')
        self.assertEqual([row['status'] for row in checks], ['PASS', 'PASS'])
        self.assertTrue(all(row['cursor_hidden_in_final_mp4'] for row in checks))
        broken = copy.deepcopy(evidence)
        arrival = next(e for e in broken['choreography']['events'] if e['type'] == 'cursor-arrival')
        arrival['box']['x'] -= 400
        with self.assertRaisesRegex(RuntimeError, 'misses its rendered button'):
            b05_pointer_check(folder / 'B05.mp4', broken, 1730 / 30,
                              'B05-014', folder / 'qa-clicks/B05-014')

    def test_b06_archive_clicks_use_rendered_buttons_and_clear_context(self):
        folder = ROOT / 'generated/b06-block-review'
        if not (folder / 'B06.mp4').is_file():
            self.skipTest('large B06 review candidate is an ignored local artifact')
        evidence = json.loads((folder / 'scenes/B06-018.json').read_text())
        scene_start = (608 + 333 + 447) / 30
        checks = b06_pointer_check(folder / 'B06.mp4', evidence, scene_start,
                                   'B06-018', folder / 'qa-clicks/B06-018')
        self.assertEqual([row['status'] for row in checks], ['PASS'] * 3)
        self.assertTrue(all(row['cursor_hidden_in_final_mp4'] for row in checks[1:]))
        broken = copy.deepcopy(evidence)
        arrivals = [e for e in broken['choreography']['events'] if e['type'] == 'cursor-arrival']
        arrivals[-1]['box']['x'] -= 500
        with self.assertRaisesRegex(RuntimeError, 'misses its rendered button'):
            b06_pointer_check(folder / 'B06.mp4', broken, scene_start,
                              'B06-018', folder / 'qa-clicks/B06-018')

    def test_b07_mix_clicks_hit_rendered_controls_and_hide_cursor(self):
        folder = ROOT / 'generated/b07-block-review'
        if not (folder / 'B07.mp4').is_file():
            self.skipTest('large B07 review candidate is an ignored local artifact')
        report = json.loads((folder / 'report.json').read_text())
        frames = report['scene_frame_counts']
        scene_start = sum(frames[s] for s in ('B07-019', 'B07-020', 'B07-021')) / 30
        evidence = json.loads((folder / 'scenes/B07-022.json').read_text())
        checks = b07_pointer_check(folder / 'B07.mp4', evidence, scene_start,
                                   'B07-022', folder / 'qa-clicks/B07-022')
        self.assertEqual([row['status'] for row in checks], ['PASS', 'PASS'])
        self.assertTrue(all(row['cursor_hidden_on_context_change'] for row in checks))
        broken = copy.deepcopy(evidence)
        arrival = next(e for e in broken['choreography']['events'] if e['type'] == 'cursor-arrival')
        arrival['box']['x'] += 500
        with self.assertRaisesRegex(RuntimeError, 'pointer tip is outside|misses its rendered button'):
            b07_pointer_check(folder / 'B07.mp4', broken, scene_start,
                              'B07-022', folder / 'qa-clicks/B07-022')

    def test_b07_transition_scan_catches_brief_screen_and_scroll_return(self):
        frame=lambda value:bytes([value])*(48*27)
        brief=frame(30)*12+frame(220)*24+frame(30)*12
        rebound=frame(30)*12+frame(90)*2+frame(30)*12
        loading=frame(30)*12+frame(90)*2+frame(220)*12
        self.assertIn('brief_screen_return', [a['type'] for a in visual_transition_anomalies(brief)])
        self.assertIn('brief_screen_return', [a['type'] for a in visual_transition_anomalies(rebound)])
        self.assertIn('clustered_screen_jumps', [a['type'] for a in visual_transition_anomalies(loading)])
        self.assertEqual(visual_transition_anomalies(frame(30)*12+frame(220)*80), [])
        rejected=ROOT/'generated/b07-block-review/history/rejected-058a0e14/B07.mp4'
        if rejected.is_file():
            import subprocess
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(rejected),
                                         '-vf','scale=48:27:flags=area,format=gray','-r','30',
                                         '-f','rawvideo','-'])
            anomalies=visual_transition_anomalies(raw)
            self.assertTrue(any(a['type']=='brief_screen_return' and 41<a['start_seconds']<42 for a in anomalies))
            self.assertTrue(any(a['type']=='brief_screen_return' and 62<a['start_seconds']<63 for a in anomalies))
            self.assertTrue(any(a['type']=='clustered_screen_jumps' and 4<a['start_seconds']<5 for a in anomalies))


if __name__ == "__main__":
    unittest.main()
