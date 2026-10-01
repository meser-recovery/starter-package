# S11 · Narration Module Map

## Status

**APPROVED DRAFT FOR CODEX IMPLEMENTATION**

Purpose: define the stable long-form narration units for the S11 Meser Audio tutorial.

This document does **not** replace the Canonical Content Pack.

- **Canonical Content Pack** remains the source of truth for tutorial content.
- **`tutorial.yaml`** remains the executable source of truth for the build.
- **Narration modules** define how approved scene narration is grouped into continuous ElevenLabs requests.
- A narration module must not change, paraphrase, omit, or add canonical content unless the user has explicitly approved that content change.

---

# 1. Approved narration profile

Use the following profile for the clean full rollout:

```text
provider: ElevenLabs
voice_id: LHi3adMlU7AICv8Yxpmm
model_id: eleven_v3
language_code: ru
output_format: mp3_44100_128
voice_settings:
  stability: 0.5
delivery_prefix:
  [calm] [conversational]
```

The delivery prefix is a TTS instruction only. It is **not** canonical narration, must not appear in subtitles, and must not be treated as spoken tutorial content.

The profile is based on the successful long-form test of scenes 019–022, generated as one continuous request.

---

# 2. Canonical opening and ending

The approved opening is already part of the current canonical content:

> Привет. Позвольте представить вам несколько новых возможностей, доступных на сайте Мэсэр в разделе для служащих.

The user has also explicitly approved the closing:

> Спасибо за внимание, всего доброго.

Before the final full build, this closing must be added **canonically** to the end of the tutorial:

1. first/atomically update the Canonical Content Pack;
2. update scene `060-summary` in `tutorial.yaml`;
3. update canonical hash/mapping;
4. CONTENT_DRIFT must remain PASS.

The closing must not exist only as a TTS-only extra.

---

# 3. Module map

Durations below are planning estimates derived from the validated long-form v3 test:

- 1,923 canonical characters
- 116.506 seconds

Actual module duration is determined only by the returned ElevenLabs audio/timestamps.

| Module | Meaning | Scenes | Canonical refs | Approx. chars | Est. duration |
|---|---|---|---|---:|---:|
| **N01** | Introduction and why multitrack matters | `001–005` | `n001–n014` | 2,541 | ~2:34 |
| **N02** | Audio Archive and getting sources into the Editor | `006–018` | `n015–n037` | 2,321 | ~2:21 |
| **N03** | Announcement workflow concept: bilingual audio, one/multiple translators, common silence | `019–022` | `n038–n054` | 1,917 | ~1:56 |
| **N04** | Announcement workflow in the real Editor | `023–029` | `n055–n066` | 1,162 | ~1:10 |
| **N05** | Speaker mode: independent processing, monitoring, workspace and navigation | `030–036` | `n067–n083` | 1,628 | ~1:39 |
| **N06** | Speaker mode: trim, cut, silence and edit operations | `037–043` | `n084–n094` | 1,244 | ~1:15 |
| **N07** | Project vs final version and returning to saved work | `044–055` | `n095–n118` | 2,450 | ~2:28 |
| **N08** | Archive management, summary and closing | `056–060` | `n119–n132` + approved closing | ~1,455 | ~1:28 |

No module exceeds approximately 2.6k canonical characters.

These boundaries are semantic, not arbitrary equal-size chunks.

---

# 4. Exact scene membership

## N01 · Introduction and why multitrack matters

```text
001-purpose
002-zoom-multitrack
003-announcement-benefit
004-speaker-benefit
005-two-tools
```

Start:
`Привет. Позвольте представить вам несколько новых возможностей...`

End:
the explanation of Audio Archive and Audio Editor as the two main tools.

Reason for boundary:
this is the complete conceptual introduction before entering the actual Archive workflow.

---

## N02 · Audio Archive and getting sources

```text
006-archive-open
007-archive-create
008-archive-files
009-archive-add-replace
010-archive-save
011-archive-hierarchy
012-archive-search
013-editor-open
014-editor-from-archive
015-editor-device-import
016-local-not-saved
017-editor-save-sources
018-two-modes
```

Start:
`Начнём с Аудиоархива.`

End:
the choice between `Анонс-мейкер` and `Спикерская`.

Reason for boundary:
one continuous user journey from receiving/saving a recording through opening its sources in the Editor and reaching the workflow choice.

---

## N03 · Announcement concept

```text
019-bilingual-problem
020-one-translator
021-two-translators
022-common-silence
```

Start:
`Как упоминалось ранее, анонс-мейкеру нужно внимательно прослушать спикерскую...`

End:
`Если переводчик один, алгоритм просто анализирует одну дорожку.`

Reason for boundary:
this is one self-contained explanation of the pause-reduction algorithm.

**This exact semantic block has already passed the long-form v3 Directed test as one continuous TTS request.**

---

## N04 · Announcement workflow in the Editor

```text
023-announcement-open
024-announcement-solo-mute
025-announcement-navigation
026-announcement-workspace
027-announcement-process
028-announcement-result
029-announcement-save
```

Start:
opening the `Анонс-мейкер` mode.

End:
saving a new announcement version without deleting the previous one.

Reason for boundary:
this is one complete practical workflow inside the announcement mode.

---

## N05 · Speaker processing and navigation

```text
030-speaker-open
031-speaker-processing
032-speaker-levels
033-speaker-monitor-exclude
034-speaker-workspace
035-speaker-navigation
036-speaker-loop
```

Start:
`Режим «Спикерская» предназначен для более точной обработки и монтажа.`

End:
Loop usage.

Reason for boundary:
this module establishes Speaker mode and covers per-track processing, monitoring and navigation before destructive/non-destructive edit operations begin.

---

## N06 · Speaker editing operations

```text
037-speaker-trim
038-speaker-global-cut
039-speaker-remove-cut
040-speaker-silence
041-speaker-remove-silence
042-speaker-region-edit
043-speaker-undo-redo
```

Start:
setting the recording start/end.

End:
Undo/Redo, Space playback, and the summary of what Speaker editing enables.

Reason for boundary:
this is the complete manual editing toolset: trim, global cut, per-track silence, direct reversal and edit manipulation.

---

## N07 · Project, final and history

```text
044-project-meaning
045-project-save
046-local-project-save
047-final-create
048-final-check
049-final-download-save
050-project-final-link
051-history-reopen
052-history-states
053-history-old-state
054-history-finals
055-history-final-state
```

Start:
the distinction between a saved project and a ready audio file.

End:
returning to the exact project state that produced a final version.

Reason for boundary:
saving, final rendering and project history are one connected mental model. Keeping them in one narration take avoids an artificial break between “what is a project?” and “how do I return to it later?”.

---

## N08 · Archive management, summary and closing

```text
056-archive-edit-details
057-archive-worklist
058-archive-delete-results
059-archive-danger
060-summary
```

Start:
management of already saved Archive materials.

End:

`Спасибо за внимание, всего доброго.`

Reason for boundary:
the final operational housekeeping naturally leads into the tutorial summary and sign-off.

---

# 5. Module request construction

For each module, build the spoken canonical text by concatenating the exact `scene.narration` values in module order.

Use natural paragraph separation between scene narrations.

Conceptually:

```text
request text =
[calm] [conversational]
<newline>
<exact canonical narration for first scene>

<exact canonical narration for second scene>

...
```

Requirements:

- one ElevenLabs request per module;
- do not generate one request per scene;
- do not silently edit punctuation or wording;
- do not insert explanatory text between scenes;
- TTS delivery tags are not canonical content;
- request text and canonical spoken text must be stored separately in evidence;
- module character count must be measured on canonical spoken text, excluding delivery tags.

---

# 6. Timestamp / scene boundary model

A module remains one continuous audio file.

Scenes inside it are **logical timing ranges**, not separate audio files.

The returned alignment must be mapped back to the exact canonical narration.

For every scene inside a module, persist at minimum:

```text
module_id
scene_id
scene_start_seconds
scene_end_seconds
canonical_start_offset
canonical_end_offset
```

These scene boundaries drive:

- subtitles;
- explanatory animation cue timing;
- browser action timing where narration synchronization is required;
- review-page seeking.

Do not physically split the module MP3 merely to obtain scene artifacts.

Review tooling may seek into the module or create disposable previews, but those previews are not narration sources for the final assembly.

---

# 7. Selective regeneration contract

The module is the minimum normal regeneration unit for narration.

Example:

```text
User requests correction inside scene 020
→ identify module N03
→ regenerate N03 only
→ keep N01, N02, N04–N08 from valid cache
→ replace N03 timestamps
→ update timing-dependent artifacts for scenes 019–022
→ rebuild subtitles
→ rebuild final timeline
```

Do **not** regenerate a single sentence and splice it into the middle of an otherwise continuous module as the normal correction path.

If one phrase has:

- wrong stress;
- wrong pronunciation;
- poor intonation;
- an unwanted pause;
- an unacceptable delivery;

regenerate the **entire affected module**.

This deliberately trades a small amount of TTS cost for consistent prosody.

---

# 8. Pronunciation overrides

A pronunciation correction does not automatically change the Canonical Content Pack.

Keep semantic text and TTS pronunciation control separate.

The pipeline should support module-scoped pronunciation metadata, for example conceptually:

```yaml
pronunciation_overrides:
  - canonical: "..."
    tts_instruction: "..."
```

Exact implementation depends on supported ElevenLabs v3 mechanisms and must not cause the visible/subtitle text to diverge from canonical content.

Rules:

1. canonical spelling stays unchanged unless the user explicitly approves a textual correction;
2. TTS-only pronunciation instructions must never appear in subtitles;
3. every override participates in the module narration hash;
4. changing an override invalidates only the affected module;
5. actual spoken output remains subject to human review.

Do not invent pronunciation overrides proactively.

---

# 9. Cache identity

A module narration hash must include at least:

```text
module ID
ordered scene IDs
exact canonical spoken text
voice ID
model ID
language code
output format
voice settings
delivery prefix/tags
pronunciation configuration
```

Changing any of these must invalidate that module narration cache.

Changing N03 must not invalidate N01/N02/N04–N08.

---

# 10. Visual invalidation after narration regeneration

When a module is regenerated:

- keep visual assets whose content itself is unchanged;
- recompute scene timing from the new alignment;
- recapture/rerender only visual scene artifacts whose timing is coupled to narration;
- do not regenerate unrelated modules or unrelated scenes.

For procedural explanatory visuals, phrase-level cue timing should follow the new alignment.

For browser demonstrations, preserve semantic actions; only timing/capture for affected scenes should change when required.

---

# 11. Final audio assembly

Do not build the final soundtrack by concatenating already AAC-encoded scene clips.

Required model:

```text
N01 decoded audio
N02 decoded audio
N03 decoded audio
...
N08 decoded audio
        ↓
continuous PCM master timeline
        ↓
module-boundary pauses / approved spacing
        ↓
one final AAC encode
```

Requirements:

- decode module source audio to a common PCM format;
- concatenate on one continuous PCM timeline;
- perform only one final AAC encode for the final MP4 soundtrack;
- no `AAC scene → AAC scene → concat -c copy` master assembly;
- avoid audible codec seams at module boundaries;
- do not crossfade actual spoken words;
- any micro-fade used to suppress discontinuities must be restricted to non-speech boundary silence.

---

# 12. Module boundary quality check

Before accepting the full narration:

For every N01→N02 ... N07→N08 boundary verify:

- no click/pop;
- no duplicated word;
- no truncated phoneme;
- no accidental extra phrase;
- no delivery tag spoken;
- no obviously abnormal pause;
- no abrupt loudness discontinuity;
- no subtitle overlap/out-of-range timing.

Full decode PASS alone is not sufficient evidence of perceptual cleanliness.

A review page must allow playback beginning shortly before each module boundary.

---

# 13. Build/rebuild commands — required behavior

Exact CLI syntax may follow the existing S11 build style, but equivalent functionality must exist:

```text
build narration --module N03
build visual --module N03
build all --module N03
build narration --all-modules
assemble
dry-run --module N03
```

A dry run must say exactly which module TTS requests would be spent and which cached modules remain reusable.

---

# 14. Generated artifact model

Preferred conceptual layout:

```text
tutorial/generated/narration-modules/
├── N01/
│   ├── narration.mp3
│   ├── timing.json
│   └── metadata.json
├── N02/
│   └── ...
...
└── N08/
    └── ...
```

`timing.json` / metadata must preserve enough evidence to recover scene timing without re-calling ElevenLabs.

Generated narration media remains ignored by Git.

The module map/source configuration itself must be versioned.

---

# 15. Source-of-truth hierarchy

The final hierarchy is:

```text
Canonical Content Pack
        ↓ defines approved meaning/text
tutorial.yaml
        ↓ defines executable scenes + module grouping/build behavior
Narration module cache
        ↓ generated evidence/output
Scene timing / visuals / subtitles
        ↓
PCM master timeline
        ↓
Final MP4
```

If `tutorial.yaml` semantically disagrees with the Canonical Content Pack:

```text
FAIL: CONTENT_DRIFT
```

The module system must never be used as a second content-authoring layer.

---

# 16. Full-rollout gate

Do not start final full narration generation until:

1. this module map is implemented in the executable spec;
2. the approved closing is added canonically;
3. `eleven_v3` Directed profile is configured;
4. module-level cache/selective regeneration exists;
5. module-to-scene timing mapping exists;
6. final PCM-first audio assembly exists;
7. boundary review tooling exists;
8. CONTENT_DRIFT passes.

The already validated N03 long-form test is evidence for the chosen approach, but generated test media is not automatically promoted into the final module cache unless its exact hash/configuration matches the final implementation.

---

# 17. Final decision summary

**8 narration modules.**

**One continuous Eleven v3 request per module.**

**Current approved voice: `LHi3adMlU7AICv8Yxpmm`.**

**Delivery: `[calm] [conversational]`, stability `0.5`, Russian.**

**Scene boundaries come from timestamps; scenes are not separate narration files.**

**Corrections regenerate the affected module, not the entire tutorial and not a single sentence splice.**

**Final soundtrack is assembled in PCM and encoded to AAC once.**

**Canonical Content Pack remains the authority for what is said.**
