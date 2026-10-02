# B04 · block review

Status: **READY FOR B04 BLOCK REVIEW**. Scene 010 only. B01–B03 remain `BLOCK_APPROVED`; B05–B14 remain gated.

The canonical text and punctuation are unchanged. One continuous ElevenLabs `eleven_v3` request used voice `LHi3adMlU7AICv8Yxpmm`, language `ru`, stability `0.5`, output `mp3_44100_128`, prefix `[calm] [conversational] [slowly]`. The single reviewed transition is after canonical offset 78: the first sentence names both available modes; the second moves to the Announcement mode. The source alignment shows a 0.604-second gap. The review map requests no additional silence. Original provider MP3 and alignment, reviewed MP3/WAV, PCM and mapping are retained in `generated/narration-blocks-v2/B04/`. No speed, pitch, gain or time stretching was applied.

The real Audio Editor shows both mode choices. A capture-only cursor approaches the actual `#open-local-announcement` button at the spoken decision, clicks it, and disappears as the Announcement workspace opens. There are no decorative highlights. A synthetic in-memory recording supplies four tracks; the capture sends no production mutation requests.

Review MP4: `generated/b04-block-review/B04.mp4`, 9.033333 s, SHA-256 `f14978c373710fd5b8e5a579a4f718079ada4ea1e0ffd2dd24409d80a52b99bb`.

Source/review MP3 SHA-256 `6472a15a2ed87fbc654d265f54e34f0e6412bd8b3bba0214fe41f73f94214dfd`; reviewed WAV `e1d4ff75db4ac5e82f035984decdcc36eb73c0a1246f55538d510f97e08816a1`; unchanged decoded PCM `bd15d1aca861503084da860697134e865a4656fb63be6b85e22d6a25d7ae70e6`; source/review alignment `3fe1b93d9085b1d60a58b5f11b35c49f55c024d180a29aa195ba5ad2a3bcd242`.

`build.py verify --module B04` passes: 271 frames, no blank or isolated flash frames, AAC zero-lag correlation 0.999967 with the source PCM timeline, two `mov_text` cues extracted from the final MP4 and matched to the canonical text and SRT including the final cue at 9.004 s. The click ring in the final MP4 lies inside the rendered button at 7.292 s. Before/press/after/context frames are saved under `generated/b04-block-review/qa-clicks/`; the interface changes on click, and the cursor's dark pixels at the click position fall from 198 to 0 after the context change. Capture reports no cursor lifecycle violations. The full scene was checked at its initial choice, press and opened editor states for readable controls and a stable ending. These checks do not constitute user approval.
