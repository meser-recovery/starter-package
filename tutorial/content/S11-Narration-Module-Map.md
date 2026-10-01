# S11 · Narration Block Map

The [Canonical Content Pack](meser-audio-tutorial-canonical-content-pack.md) is the source for exact spoken text. `tutorial.yaml` maps that text once, in order, to B01–B14 and the 54 technical scene units. The block title and delivery tags are never part of spoken narration or subtitles.

| Block | Approved title | Scene units |
|---|---|---|
| B01 | Вступление | 001–003 |
| B02 | Запись в виде отдельных аудиодорожек | 004–007 |
| B03 | Выбор источника файлов | 008–009 |
| B04 | Два режима обработки | 010 |
| B05 | Анонс-мейкер: выбираем дорожки | 011–014 |
| B06 | Анонс-мейкер: сокращаем паузы | 015–018 |
| B07 | Спикерская: обработка звука | 019–022 |
| B08 | Спикерская: рабочая область | 023–027 |
| B09 | Спикерская: монтаж | 028–034 |
| B10 | Создаём финальную версию | 035–037 |
| B11 | Роль Аудиоархива | 038–041 |
| B12 | Связь Аудиоархива и Аудиоредактора | 042–045 |
| B13 | Проекты и версии | 046–051 |
| B14 | Как найти запись и продолжить работу | 052–054 |

One complete block is one continuous ElevenLabs request. B01 audio has `AUDIO_APPROVED`; its visual pass uses the pinned approved WAV and shifted alignment. Each later block first receives its own reasoned semantic pause map, then audio and visual review in sequence. The next block stays gated until the preceding complete block is approved. Final assembly uses only the approved block versions and does not call TTS again.

The previous N01–N08 map is preserved as [historical material](historical/S11-Narration-Module-Map-N01-N08.md). Its source text, scene numbers, and ending do not apply to this production pass.
