# Approved shared timeline UX evidence

Implementation and capture source:
`7408600b81385eb7a4a1188c51f1b02747c64fdc`.
The evidence-only commit is validated again as the final submitted HEAD and the
exact local/CI result is recorded in draft PR #36.

[Scope, requirement mapping and validation](../../../S09A-approved-timeline-ux.md).

## Captures

- [Speaker before expansion](speaker-before-expand.png): the retained normal
  page layout, shared selection and semantic regions.
- [Speaker expanded](speaker-expanded.png): independent track colors, gray
  recording bounds, Cut/Silence/Loop intervals and 1000 px/s scale.
- [Announcement expanded](announcement-expanded.png): shared full-range
  selection/Loop, per-track colors and the common scale controls.
- [Interaction recording](approved-timeline-interactions.webm): real source
  preparation, both editors, Cut/Silence/Loop handle, Time/Height, track color,
  anchored pinch-shaped zoom, Space source/result transport and expansion.

All PNGs are original DPR 2 Chromium captures; they were visually inspected at
their native dimensions. The recording and screenshots use generated WAV tones
and contain no user media.

## SHA-256 and dimensions

| Artifact | Dimensions | SHA-256 |
| --- | --- | --- |
| `speaker-before-expand.png` | 2240×3604 | `4806a4905c4609a0bd8640fd634d3a98df19201142067d7d599beb98542366f9` |
| `speaker-expanded.png` | 2880×2000 | `47af459b0ad1d84dde180faf8fd6ec1306531ed1d13d419e98f8b34ce0f221ac` |
| `announcement-expanded.png` | 2880×2000 | `c070a0069098510250d273d093b84d4c7995a683388ac5d95719a5fd7eb4e04b` |
| `approved-timeline-interactions.webm` | 1440×1000 recording | `ce7aa0bed2b14597cd38816aa8b1367f02e8ea9212be2f340d2838b91ed37077` |

Preview remains available at
**http://127.0.0.1:56893/Audio-Editor.html**. Existing user pages were not
reloaded. These artifacts are implementation evidence, not user Acceptance.
PR #36 remains draft; no merge, production mutation or Closure Record.
