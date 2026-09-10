# PR #36 shared workspace validation

This is implementation evidence. User visual/listening Acceptance remains open.
No merge, production mutation or Closure Record is authorized or performed.

## Patch reconciliation

The local checkout and draft PR both had clean HEAD
`756e3cd11b2307467ba1935c7ff87e4d1f55e5c2` on
`codex/s09a-editor-corrective-ux`. Both package SHA-256 checks passed. Neither
stable patch-id occurred in the branch history. The numbered patches were
applied once with `git am`, without reset, rebase or force push:

| Package commit | Applied commit | Stable patch-id |
| --- | --- | --- |
| `a37e0b16c62ab265ada510a64ead535afae8ace0` | `10392292c5f7e206d48a08eab48e0cc0194b3b36` | `72d94fa4c97936beea1894dae069f4fe89de4702` |
| `c7255329950bb4641f2fafb9d8f250282d049f97` | `d835eeaf82cee5f1f940a1905ea882d29e1a6ce1` | `c40b19a5df3d5cdc710d22e2a8c65b4e4f1fa019` |

All earlier corrective work, including the preparation/deletion identity and
canonical-revision fix in `3927c9e`, remains in the branch. The package's original
report is preserved in [workspace iteration](S09A-workspace-iteration.md); its
absence of Chromium described the package environment, not this validation.

## Browser-discovered corrections

- At 320px, scrolling to a waveform put it under the expanded sticky transport.
  A touch drag hit the listening-volume input. Lane scroll margins now account
  for the transport's bounded height. The original touch-selection assertion
  remains, plus a real hit-target assertion.
- Speaker actions wrapped onto an extra row; the selected badge added another
  line. A desktop grid keeps the five actions together and positions the badge
  beside the track number. The original <=210px lane and majority-waveform-width
  requirements remain unchanged.
- Announcement controls inherited a two-column grid inside the narrow panel,
  wrapping filenames one character per line. An explicit single-column panel
  restores compact lanes; the original <=150px requirement is unchanged.
- Linux CI on `0033ae7` found 154.98px Announcement lanes because a platform font wrapped the last action. The five desktop actions now use explicit grid columns with their status below; the <=150px limit is unchanged.
- Workspace headings inherited dark text on the new dark header. Heading color
  now inherits the light header foreground; browser contrast must be >=4.5:1.
- The retained Announcement identity/close block now has workspace spacing and
  a readable 44px close control.
- Monitoring labels describe inclusion in listening, not a claim that paused audio is sounding. Failed preparation explicitly says listening is unavailable, with a browser regression.
- Existing processor geometry tests now check the visible custom Play/Stop/volume controls and assert the native source clock is hidden. Follow retains its exact accessible name and an aria-hidden icon.
- Existing mobile DSP tests now open the new disclosure through its summary
  before selecting a setting. No DSP/output assertion was removed.

## Additional regressions

[Native audio signal smoke](s09a_playback_signal_smoke.py) runs in the full
browser suite with default Chromium security and isolated local files. Distinct
330/660Hz WAVs are played through the actual HTML media elements. Native
MediaElementAudioSourceNode/AnalyserNode taps measure RMS and frequency after
media mute/volume, without mocking playback methods or replacing samples.
Twenty cases cover both editors, each Mute, each Solo, multiple Solo, monitoring
volume, reorder with stable track identity, mute after reorder, exclusion from
render while retaining source monitoring, and source/result mutual exclusion.
The rendered MP3 contains the retained 660Hz track. Browser signal measurement
is not a claim to have listened through the user's physical speakers.

The same regression checks long filenames, side-by-side lanes at
320/390/768/1280, heading contrast, mobile DSP touch/keyboard toggles and focus,
and sticky transport bounded to 45% of a 320x450 viewport. Existing selection
tests exercise exact track identity, global cut versus track silence, boundaries,
drag-time selection, zoom/Fit/Follow and Undo/Redo.

Management smoke also exercises viewport-bounded top-layer menus at short-screen
edges, resizing an open menu between desktop and mobile flow, Escape focus
return, and outside-click closure. Its captures retain scroll position so taking
a screenshot does not itself close the menu.

The complete suite retains preparation/deletion with exact File/payload/epoch
and latest canonical revision, decoder failure/retry, exact Blob preservation,
401/403 and reconnect, delayed newer intent, saved payload/reopen/render, actual
bundled FFmpeg, synthetic 1:02:27 M4A and root/subpath CORS.

## Source-bound results and preview

[Evidence index](evidence/s09a/workspace/README.md) identifies the final source
SHA, original before/after PNGs, signal measurements and command logs. Submitted
HEAD and its exact `local-safety` result are recorded in draft PR #36 after the
separate evidence commit; historical PR #36 CI is not reused as current proof.

`python3 scripts/preview-audio-editor.py` serves the checkout on a free loopback
port and opens the real interface. The preview is left running for the user.
[AGENTS.md](../../AGENTS.md) now permanently requires a working preview before
merge for every UI change, with URL/version/checked scenarios and availability
during follow-up work. Notify the user when they can refresh; never reload their
unsaved page automatically.

Actual user Zoom files were not supplied. Chromium and synthetic signal tests
are not physical-device/Safari/Firefox/screen-reader or user Acceptance.
