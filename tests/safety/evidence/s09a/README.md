# S09A screenshot and validation index

Final implementation/source SHA for all images except `before-*`: `884ef5345cdcc3049e58eb9b97f771a00a815388`.
Implementation commits: `87c5d8f6e7a962843d74f86c6b81bc122572b584` and the narrow 320px label correction `884ef5345cdcc3049e58eb9b97f771a00a815388`.
Base and `before-*` source SHA: `240e9e5fc45661d815f4193597cc04451bb1bdf0`.
Captured 2026-09-10 on the loopback static server with Chromium, synthetic WAVs and the real in-memory gateway. All screenshot files in this directory were copied only after the final capture run passed. They are added in a later evidence-only commit, which is not the screenshot source SHA.

[43-section PLAN matrix / A01–A18](../../S09A-validation.md) · [Full browser log](browser-smoke.txt) · [80 gateway tests](gateway-tests.txt) · [Final capture checks](capture-tests.txt) · [Command results](validation.txt).

The full regression suite passed before the implementation commit. The final post-commit S09A and Archive capture runs passed after the last mobile label CSS correction. Required PR `local-safety` is checked separately on the submitted HEAD; historical CI is not used as S09A proof. No live production archive or deployment was accessed for validation.

## Reading the evidence

- Compare `before-Audio-Editor-1280` with `after-Audio-Editor-1280`, and the matching Archive pair, for the same initial-page hierarchy. These pairs block external archive access and do not pretend to show production records.
- `import-*`, `announcement-*`, `speaker-edits-help-*`, `project-reopened-*` and `archive-*` without an additional scenario cover 320/390/768/1280 CSS pixels.
- Speaker samples use different synthetic tones with duplicate filenames; screenshots show reordered/excluded tracks, selection, boundaries, silence, monitoring and help. Tests compare the payload and file identity across partial save, failed/canceled reconnect, saved project and reopen.
- `*-viewport` images retain a readable 900px viewport. Full-page images document section order; they should be opened at original resolution to inspect text. Archive detail/deletion/recovery clips preserve the specified CSS viewport width, though the image itself is cropped to the target section.
- `sources-finalized-project-failed`, `repeated-403-no-login-loop`, `reconnect`, `project-saved-local-result-retained`, `part-download-reconnect-keeps-project` and `final-version-saved` show the relevant distinct save states. `unsaved-cancel` shows the three-choice protection dialog.
- `archive-contextual-recovery-*` shows affected source rows; `archive-recovery-*` shows the separately opened maintenance disclosure. `archive-delete-impact-*`, purge and ambiguous deletion show existing guarded destructive flows.

Images were inspected for desktop hierarchy/density, mobile text/control fit, waveform states, help, project status and dialogs. Automated checks cover overflow, mouse/keyboard/touch, focus return, hidden-workspace exclusion, protected transitions and gateway write traces. Chromium emulation is not a claim of physical-device, Safari/Firefox or manual screen-reader testing.

## Files

| Screenshot | Image pixels | SHA-256 |
| --- | --- | --- |
| [after-Audio-Archive-1280.png](after-Audio-Archive-1280.png) | 1280 × 1518 | `3fb4a07b34c5d141f9c7571cda6f2aa7841afe253ca4d70a3bb1768057f115fe` |
| [after-Audio-Editor-1280.png](after-Audio-Editor-1280.png) | 1280 × 1970 | `9753ab5c3d2119f1ffde5733cd89bacde52e57644cef6ed13b5417cbed742249` |
| [announcement-1280.png](announcement-1280.png) | 1280 × 3738 | `58afcbfd05b3eb8f845c39227beb0bacf28fb9f4698b5cd0089066025601f12c` |
| [announcement-320.png](announcement-320.png) | 320 × 6532 | `ed3eb214fc4a0dd015df2ad689bfbee880a193ef2c72d6a9fc8f2009f7fe338a` |
| [announcement-390.png](announcement-390.png) | 390 × 5816 | `ec5f81e19dab422e25c00a21fbb1f51d7e0093abc8a8884fe999983ff26cdfcd` |
| [announcement-768.png](announcement-768.png) | 768 × 4129 | `8a38a1159db6ee5b244e2c80d62f92007511f01329c53c77e19da25b64f41e20` |
| [archive-1280.png](archive-1280.png) | 1280 × 3101 | `2070b8d3cf1f66444a55a825138dedf8cbf3f1754c5214d0ddeded4eaac3fceb` |
| [archive-320.png](archive-320.png) | 320 × 5981 | `69f2c08a5e9d45ce7df2f182b80b28a95682dc785e26292db268fd8571d01856` |
| [archive-390.png](archive-390.png) | 390 × 4905 | `827cecbc76e4bf39420e5ac8ffd9f4bfa9ca056e3f572e676f59e82ff1035491` |
| [archive-768.png](archive-768.png) | 768 × 3347 | `3bcc81ef8b9ab19cd1ce8108f56fc1faf8d29e32c91092d9835bd6c8387360dc` |
| [archive-ambiguous-deletion-390.png](archive-ambiguous-deletion-390.png) | 352 × 876 | `2e6775fd9a756637f62f0e1f10eef40ba9208553b0dc67e383a66492d50a6ed2` |
| [archive-contextual-recovery-1280.png](archive-contextual-recovery-1280.png) | 1120 × 3186 | `789f2486597f27aa53bf9d4dcd7dead2b6db2ba5f8fc22948a5846e360190f9f` |
| [archive-contextual-recovery-320.png](archive-contextual-recovery-320.png) | 264 × 6596 | `770ca91303638e9fa40c9d2fe8c5817bda0efcad2161b9e7be57333e23f8ade4` |
| [archive-contextual-recovery-390.png](archive-contextual-recovery-390.png) | 334 × 5670 | `0ef5db15339c3c1073a5329a73913fe8cc0a1bb34c5b199eb45cf695b78b113c` |
| [archive-contextual-recovery-768.png](archive-contextual-recovery-768.png) | 736 × 3542 | `74e61c1f601a38904ceb05c9bbf0f6c78d23f2af4c08d909f01e15e8c685eee6` |
| [archive-delete-impact-1280.png](archive-delete-impact-1280.png) | 620 × 508 | `f721b7e207a75081dee157c169ddd11b8e35adc74261e962500c75f7ea7bc360` |
| [archive-delete-impact-320.png](archive-delete-impact-320.png) | 282 × 776 | `e1645e6d369e7531e8b870f465b63fd9e4057ae6d6abe223ed479b2102100ae9` |
| [archive-delete-impact-390.png](archive-delete-impact-390.png) | 352 × 687 | `8e9b69e4aabc551fb20f0178acc774ac7af7f666d09b286524a5619fb2747a26` |
| [archive-delete-impact-768.png](archive-delete-impact-768.png) | 620 × 508 | `f721b7e207a75081dee157c169ddd11b8e35adc74261e962500c75f7ea7bc360` |
| [archive-detail-1280.png](archive-detail-1280.png) | 1120 × 1750 | `3c71a7f0682aad21fc470d3dffb0262d0b039fb6daae9e8c6c3f83230341fcad` |
| [archive-detail-320.png](archive-detail-320.png) | 264 × 3136 | `87a1ea0c3e782e9cfcc7c3862800504e9182f1b6cc3e2499c9463515be00a58f` |
| [archive-detail-390.png](archive-detail-390.png) | 334 × 2829 | `3179838476013f0abd342eba92f0e145013bb96e861c3f12ff650b47615386b4` |
| [archive-detail-768.png](archive-detail-768.png) | 736 × 1892 | `2b94a45bbd4c32d28611f24f0c321d98e6d5359f9f78ed2357a175815a7c71bb` |
| [archive-purge-confirmation-390.png](archive-purge-confirmation-390.png) | 352 × 826 | `d7c33853bd6318acd66e455eb1d145e7cdf968aa06c2892efff0b2fc8a83afe6` |
| [archive-recovery-1280.png](archive-recovery-1280.png) | 1120 × 2770 | `dc8d7313516d6fd9e15001d07e37bad78347d7d6ab7439763e9f384ede33ddb1` |
| [archive-recovery-320.png](archive-recovery-320.png) | 264 × 4434 | `2866bd4b3cba1fc8181665a0e801fce00ffa43cb34b78b83a55fb89b638a638a` |
| [archive-recovery-390.png](archive-recovery-390.png) | 334 × 3971 | `f987d6b86c239b722fcae369b3cd40cae0a7a882f69f350f602c983914f511cb` |
| [archive-recovery-768.png](archive-recovery-768.png) | 736 × 2898 | `bdb274b6b753e825c17ab2bc2741a78720757f9e36f1e8097949dd5cf4efce0a` |
| [archive-results-restored-after-source-deletion-390.png](archive-results-restored-after-source-deletion-390.png) | 334 × 1878 | `e6404383dde3f5e13ad3775aa07a1477a976b7e2041842be6049b8a64ffaf5d5` |
| [archive-verified-announcement-390.png](archive-verified-announcement-390.png) | 334 × 362 | `ade9efad15de309666ef2689a567071931cac4706eca46b5364abf3972a33eb0` |
| [archive-verified-speaker-390.png](archive-verified-speaker-390.png) | 334 × 391 | `25226db5b865fa31ece29538ea6c7bd8162c488078ff50a06cf4c9b17f63b158` |
| [before-Audio-Archive-1280.png](before-Audio-Archive-1280.png) | 1280 × 2149 | `25d9979fbde6b91f1234302d30c9e8ed7747c94f51b6c3bcb287eb7da64f6a50` |
| [before-Audio-Editor-1280.png](before-Audio-Editor-1280.png) | 1280 × 2650 | `e67b1f0ad29880aefea746cf8dc6c7a1db4e91bfa7748b35ccce56e44329557d` |
| [final-version-saved.png](final-version-saved.png) | 1280 × 4490 | `1ed559cb4e270db95d72e06d16e3befc0e55459b62dd7655fd16af700125159d` |
| [import-1280.png](import-1280.png) | 1280 × 3816 | `74f38f289e0ce78731c5b94cca5d4572ba42f1931e5e863fc9b711cbb2ae9e20` |
| [import-320.png](import-320.png) | 320 × 6869 | `3fb552ac5104536312da02881fab818d0d2d7872e8b1bd5abfac670bf1766101` |
| [import-390.png](import-390.png) | 390 × 6073 | `38d96a90e5e77ea2810899004ef1cdaab969fab061165f225051afa624a11bb5` |
| [import-768.png](import-768.png) | 768 × 4306 | `c039cd303c6c4d63539d420d6aff48f3b31f1e97903d1f98130b164b0f1b9e98` |
| [part-download-reconnect-keeps-project-viewport.png](part-download-reconnect-keeps-project-viewport.png) | 1280 × 900 | `53dc6e34ec8025696a69f9e3fc12f4b0c97074673949e5edb074d345ceef811b` |
| [part-download-reconnect-keeps-project.png](part-download-reconnect-keeps-project.png) | 1280 × 4491 | `e001627e8de1d77b08b23fa2eba1c608b62d84321cffc4bb5eaa9df2fea60b54` |
| [project-reopened-1280-viewport.png](project-reopened-1280-viewport.png) | 1280 × 900 | `316aa52de39a12bd9ee63c5ef8aadf18624de85d8dcd921e8d21f06a0c1fe7e5` |
| [project-reopened-1280.png](project-reopened-1280.png) | 1280 × 3533 | `de2ada02b75a178e4c0249201742c0a86ce6f714a539e1f39c79a4178f4d337b` |
| [project-reopened-320-viewport.png](project-reopened-320-viewport.png) | 320 × 900 | `89fa16631cdab77b5ebf0353623cfdfbd0185cef333f4c31715c4a70ee127ba3` |
| [project-reopened-320.png](project-reopened-320.png) | 320 × 6506 | `9aca63fb390833a0f5e66e7efad1fa72999d15262680300f8d15aeed7c5b43e7` |
| [project-reopened-390-viewport.png](project-reopened-390-viewport.png) | 390 × 900 | `2b383082078925cbf87602cc147ae85369c2ad837eed526b385f84efa9436944` |
| [project-reopened-390.png](project-reopened-390.png) | 390 × 5782 | `5d71f6fb970dc0a28cfe7ad34b65782a4e0dc830949795122f709f36d2cc62ca` |
| [project-reopened-768-viewport.png](project-reopened-768-viewport.png) | 768 × 900 | `d5084d35d33c8ad9b27f35d0fe713561a7e77b508c06584020388d19abeffda9` |
| [project-reopened-768.png](project-reopened-768.png) | 768 × 3941 | `02a55ad1f82fc02568462dd71780caac39de919370245a5ac211f6a9000c96fd` |
| [project-saved-local-result-retained.png](project-saved-local-result-retained.png) | 1280 × 4490 | `f1271ece550d832ebac8ccba00c82a706c718557c30493b0ef921c64e1b67a70` |
| [reconnect-viewport.png](reconnect-viewport.png) | 1280 × 900 | `c71beda0afa46b464841d47594f95a7d82b724d014299857fb64244feec2e1d8` |
| [reconnect.png](reconnect.png) | 1280 × 4613 | `8c2371e583d970498ba7750af931b6b7172a87732e2dc19f9862e89a8d155c0b` |
| [repeated-403-no-login-loop.png](repeated-403-no-login-loop.png) | 1280 × 4613 | `faec367c6cbb9f48dbc72b4812bd19c5b8ad0518f5d08c5383e9879f8383fde7` |
| [sources-finalized-project-failed.png](sources-finalized-project-failed.png) | 1280 × 4490 | `eee732e821a6b9c585358de18e8b09919d7d66cfa9a6507636542067c0fa97b7` |
| [speaker-edits-help-1280-viewport.png](speaker-edits-help-1280-viewport.png) | 1280 × 900 | `3da7a3264083bfee014cc6c5e8d34124130439926a848406d269e3b88514c345` |
| [speaker-edits-help-1280.png](speaker-edits-help-1280.png) | 1280 × 3860 | `5380cacc13caa36e3460eb6c4edeefe4a19b717fc0b468a81119a79e8360ba9e` |
| [speaker-edits-help-320-viewport.png](speaker-edits-help-320-viewport.png) | 320 × 900 | `fc7eae46b4207a4364ebd5bc09de5a748dd1823d7796dc4f21ccc58c837ae883` |
| [speaker-edits-help-320.png](speaker-edits-help-320.png) | 320 × 7360 | `c1479fe0ff26ad22d132daf0a93395ff33fe15c2a48d5a522a10ea10c4db9f63` |
| [speaker-edits-help-390-viewport.png](speaker-edits-help-390-viewport.png) | 390 × 900 | `263356208f53d200272e82928092ed2af4d510feb2b65cc3f8110bfbbd15cbb0` |
| [speaker-edits-help-390.png](speaker-edits-help-390.png) | 390 × 6505 | `d611e4085daa0dea566adcdaa6c6a64be44d8b2c77c7f63ac73a2f922af525b6` |
| [speaker-edits-help-768-viewport.png](speaker-edits-help-768-viewport.png) | 768 × 900 | `c9aaa9ed0a05e70da9d92b3bf96d6ed8035c92bce763142175650723f10bd744` |
| [speaker-edits-help-768.png](speaker-edits-help-768.png) | 768 × 4442 | `8de5182e70429281af9056a2674ad17c711ba6d56dcac110573ab9c9fc9cb0d0` |
| [unsaved-cancel-viewport.png](unsaved-cancel-viewport.png) | 1280 × 900 | `8f66314bb3d7a9584e8769c4c51a60128ca971d018cfb4a3f58e1157c33565e3` |
| [unsaved-cancel.png](unsaved-cancel.png) | 1280 × 4490 | `41455ebdac2abfceadddd1ddea2454e7f676e203b4ac3d83c256befd535915e7` |

## CI follow-up

The first PR run (`bd4d9d1`, run [34466098987](https://github.com/meser-recovery/starter-package/actions/runs/34466098987)) failed an immediate visibility check after the help touch tap. A later test-only correction waits for that same visible state. The screenshot implementation SHA above is unchanged. See the PR for the corrected submitted HEAD and required local-safety result; the first failed run is not counted as successful validation.

The second run [34467864208](https://github.com/meser-recovery/starter-package/actions/runs/34467864208) also failed the touch sequence. The subsequent test correction separates native help tapping from the raw CDP drag and clears the old selection before requiring a newly created touch selection. Both checks remain mandatory; screenshot implementation is unchanged.
