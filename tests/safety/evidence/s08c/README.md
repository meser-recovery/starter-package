# S08C Speaker Editor visual evidence

Generated locally by:

```bash
venv/bin/python tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000 --screenshot-dir tests/safety/evidence/s08c
```

The committed evidence is limited to the S08C states; unrelated screenshots emitted by the full
regression suite were removed.

- `s08c-speaker-opened-390.png` and `s08c-speaker-opened-1280.png`: separate opened Speaker workspace,
  immutable original-time selection, synchronized source controls, default-Off DSP, and disabled history.
- `s08c-regions-distinct-390.png`: one global cut over all three waveforms and one visually distinct
  per-track silence overlay only on its target track, plus editable region rows.
- `s08c-excluded-dsp-768.png`: excluded middle track remains present and monitorable, while the first
  included track shows gentle enhancement and medium compression.
- `s08c-undo-redo-390.png`: completed edit history state with correct Undo/Redo availability after a new
  edit cleared the Redo branch.
- `s08c-render-progress-cancel-390.png`: bounded local progress beside an enabled cancel action and no result;
  every render-affecting control is disabled while monitoring and navigation remain available.
- `s08c-local-result-390.png` and `s08c-local-result-1280.png`: independent result player/waveform,
  3.0 s original duration, 2.499 s result after one 0.5 s global cut, MP3 128 kbit/s metadata, local download,
  the result waveform filling its complete independent timeline, and the explicit not-saved-to-Speaker warning.

All eight images were visually inspected after generation. Labels are readable, the region colors remain
distinct, controls stay inside their cards, and no horizontal page overflow or overlap is visible at the
captured sizes. The browser smoke additionally checks the opened workspace at 320 and 768 CSS pixels.
