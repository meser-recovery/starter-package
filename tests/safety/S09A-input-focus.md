# S09A: relaxed pointer focus for Space

Base: e1a1cb0a2f40fab281458cc8dacdbb5cfb753890.

Reproduced in Chromium: opening the local speaker editor leaves focus on
`open-local-speaker`; Space is excluded by the native-button guard. The wave
itself does not need focus for ctrl-wheel or Safari-shaped gesture events.

The two launcher buttons now identify their workspace with aria-controls.
Space routes to the visible ready editor after a pointer click on its launcher
or a studio button. It does not repeat the clicked command. Tab clears that
exception, so keyboard button activation remains native. Inputs, contenteditable,
menus, dialogs, repeats, composition and modified Space remain protected.
Source/result context and readiness checks remain in place; no automatic focus,
page reload or gesture handler changes were introduced.

Supplied-patch validation (Linux Chromium; generated WAV fixtures, real media transport):
- 33 frontend unit tests PASS.
- JavaScript syntax and site contract PASS.
- s09a_input_focus_smoke: both editors PASS, including initial launcher focus,
  toolbar pointer focus, Tab button activation, input protection, neutral page
  focus, menu protection, hidden editor isolation, unfocused ctrl-wheel and
  Safari-shaped gestures, ordinary wheel without zoom.
- Existing s09a_approved_timeline_ux_smoke PASS, including source/result Space,
  shared selection/Loop, regions, colors, Time/Height, pinch and maximize.

Receiving Mac validation:
- patch SHA-256 matched and `git apply --check` passed on the exact clean base;
- site contract, JavaScript syntax and 33/33 frontend unit tests PASS;
- focused input regression and existing approved timeline regression PASS in both
  editors with actual media transport and a rendered result;
- gateway syntax and 80/80 tests PASS;
- complete browser smoke PASS, including the new test through its standard suite
  registration and all retained archive/CORS, waveform, Follow, signal, edit,
  meter, preparation, render and responsive checks.

The final submitted SHA and exact-head GitHub CI result are recorded in draft PR
#36. Physical Mac pinch and physical audio listening were not automated or
claimed. Synthetic Safari-shaped event checks are not a Safari test.
