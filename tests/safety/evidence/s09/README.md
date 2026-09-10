# S09 · screenshot and validation index

Source commit for **all PNG files**: `c7a78a4bb956f8e5a95bdefcde95cf0e3658eb70`.
Base: `8be4a95602e46653ce72fb131b59f6d9f49de17b`. Captured 2026-09-10 from the local static server with Chromium and real in-memory gateway fixtures.

This directory is committed separately as evidence only. Its commit is not claimed as the screenshot source commit. The post-commit browser run passed with 191 local gateway requests and no outbound archive access.

The full regression run passed before the implementation commit. The final post-commit focused run recaptured every S09 image after the last UI edit (shortened sort labels at 320px). No runtime changes accompany this evidence commit.

Long section captures use page-origin clipping to avoid offscreen fixed-element artifacts; the CSS viewport widths below are the test widths, not the cropped image widths. Screenshots were visually reviewed alongside automated overflow, focus, dialog and read-only trace checks.

[Requirement mapping and exact commands](../../S09-validation.md) · [Full browser log](browser-smoke.txt) · [Command results](validation.txt)

| Scenario | CSS viewport | Evidence |
| --- | --- | --- |
| Неоднозначный сетевой ответ: повтор заблокирован, состояние запрошено заново | 390 × 900 | [ambiguous-deletion-390.png](ambiguous-deletion-390.png) |
| Совмещённые фильтры и поиск исходного файла | 1280 × 900 | [combined-filters-1280.png](combined-filters-1280.png) |
| Совмещённые фильтры и поиск исходного файла | 320 × 900 | [combined-filters-320.png](combined-filters-320.png) |
| Совмещённые фильтры и поиск исходного файла | 390 × 900 | [combined-filters-390.png](combined-filters-390.png) |
| Совмещённые фильтры и поиск исходного файла | 768 × 900 | [combined-filters-768.png](combined-filters-768.png) |
| Подтверждение удаления одной серии и сохранённые зависимости | 1280 × 900 | [delete-impact-1280.png](delete-impact-1280.png) |
| Подтверждение удаления одной серии и сохранённые зависимости | 320 × 900 | [delete-impact-320.png](delete-impact-320.png) |
| Подтверждение удаления одной серии и сохранённые зависимости | 390 × 900 | [delete-impact-390.png](delete-impact-390.png) |
| Подтверждение удаления одной серии и сохранённые зависимости | 768 × 900 | [delete-impact-768.png](delete-impact-768.png) |
| Две независимые истории: живые версии 1/3, удалённая 2 | 1280 × 900 | [detail-1280.png](detail-1280.png) |
| Две независимые истории: живые версии 1/3, удалённая 2 | 320 × 900 | [detail-320.png](detail-320.png) |
| Две независимые истории: живые версии 1/3, удалённая 2 | 390 × 900 | [detail-390.png](detail-390.png) |
| Две независимые истории: живые версии 1/3, удалённая 2 | 768 × 900 | [detail-768.png](detail-768.png) |
| Переход в Анонс-мейкер после входа | 390 × 900 | [editor-arrival-announcement-390.png](editor-arrival-announcement-390.png) |
| Переход в Спикерскую после входа | 390 × 900 | [editor-arrival-speaker-390.png](editor-arrival-speaker-390.png) |
| Неверная ссылка: обработка не начинается | 390 × 900 | [ineligible-bad-390.png](ineligible-bad-390.png) |
| Входящая запись с удалёнными исходниками: отказ в обработке | 390 × 900 | [ineligible-deleted-sources-390.png](ineligible-deleted-sources-390.png) |
| Архивированная запись: обработка не начинается | 390 × 900 | [ineligible-f7d-390.png](ineligible-f7d-390.png) |
| Полностью удалённая запись: отказ в обработке | 390 × 900 | [ineligible-purged-390.png](ineligible-purged-390.png) |
| Недоступные счётчики не превращаются в нули | 390 × 900 | [listing-error-390.png](listing-error-390.png) |
| Конфликт метаданных и сохранённый ввод | 390 × 900 | [metadata-conflict-390.png](metadata-conflict-390.png) |
| Отсутствие совпадений | 1280 × 900 | [no-matches-1280.png](no-matches-1280.png) |
| Отсутствие совпадений | 320 × 900 | [no-matches-320.png](no-matches-320.png) |
| Отсутствие совпадений | 390 × 900 | [no-matches-390.png](no-matches-390.png) |
| Отсутствие совпадений | 768 × 900 | [no-matches-768.png](no-matches-768.png) |
| Обзор и счётчики | 1280 × 900 | [overview-1280.png](overview-1280.png) |
| Обзор и счётчики | 320 × 900 | [overview-320.png](overview-320.png) |
| Обзор и счётчики | 390 × 900 | [overview-390.png](overview-390.png) |
| Обзор и счётчики | 768 × 900 | [overview-768.png](overview-768.png) |
| Точное подтверждение полного удаления | 390 × 900 | [purge-confirmation-390.png](purge-confirmation-390.png) |
| Незавершённые операции, pending delete и отдельные наблюдения | 1280 × 900 | [recovery-1280.png](recovery-1280.png) |
| Незавершённые операции, pending delete и отдельные наблюдения | 320 × 900 | [recovery-320.png](recovery-320.png) |
| Незавершённые операции, pending delete и отдельные наблюдения | 390 × 900 | [recovery-390.png](recovery-390.png) |
| Незавершённые операции, pending delete и отдельные наблюдения | 768 × 900 | [recovery-768.png](recovery-768.png) |
| Результаты после архивирования, удаления исходников и перезагрузки | 390 × 900 | [results-restored-after-source-deletion-390.png](results-restored-after-source-deletion-390.png) |
| Проверенный WAV анонса | 390 × 900 | [verified-announcement-390.png](verified-announcement-390.png) |
| Проверенный MP3 спикерской | 390 × 900 | [verified-speaker-390.png](verified-speaker-390.png) |

## Review boundary

No production mutations or deployment. The pre-existing unsupported-browser test context was found without outbound isolation during earlier baseline runs, which may have issued a configuration GET. It now reuses the processor gateway isolation; the stored final full-run log is from the corrected suite. S09’s own context blocks external archive access throughout. No independent acceptance or Stage COMPLETE is claimed.
