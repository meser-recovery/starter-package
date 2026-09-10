# PR #36 P1 review follow-up

Reviewed base: `773975e402d083b860207629d20356e0d072e0e6`. Same branch: `codex/s09a-editor-corrective-ux`. This is review-fix evidence, not Acceptance or Closure.

`updateSpeakerSession` replaced the object captured by `prepareSources`, invalidating its identity check during an otherwise valid result deletion. The complete browser path also treated the increased revision as a competing source load and reopened the recording with new File objects. The first browser regression failed exact epoch/File preservation before this fix; a superficially ready editor was not sufficient.

Metadata/results refresh now retains the current session identity only when source state and all source descriptors are unchanged. Older revisions are ignored; a changed source is rejected with 409. The existing preparation epoch, object-identity and AbortController checks remain intact. The archive loader recognizes its own exact loaded File batch, keeps the current canonical session instead of restoring its captured revision, and does not reopen that batch after ordinary decode failure. Independent source intents still use the original sequence/auth/epoch guards.

The D browser suite now opens a canonical recording through visible controls, holds only the first actual native decode completion, and deletes a Speaker version or series via visible confirmation and the real in-memory gateway. It verifies readiness after release, exact File references/order/payload/source epoch, full latest canonical session equality, and exactly one delete write. A third case injects native and bundled-decoder failure after deletion, checks the named error/retry, and verifies the explicit retry preserves the same work. Metadata refresh guards reject source-hash replacement and revision rollback. Existing post-ready deletion, auth, close/new-source and decoder regressions remain enabled in the full suite.

The previous audit's PASS did not cover this sequence. It is preserved as a discovered coverage gap, with this new test mapping to PLAN §§9, 19–21, 35 and A05/A08/A15.

[New source-bound regression screenshots and command logs](evidence/s09a/pr36-review/README.md) record the implementation SHA and actual final validation. Prior S09A screenshots remain historical evidence for their stated SHA; no layout changes are introduced here. Exact submitted-head CI is linked in PR #36.

Real user Zoom files remain unprovided and untested. Tests use synthetic audio, Chromium and isolated gateways, with no production archive writes. No merge, Closure Record or COMPLETE declaration.
