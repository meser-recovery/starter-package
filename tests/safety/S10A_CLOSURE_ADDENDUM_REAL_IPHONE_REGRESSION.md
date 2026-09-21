# S10A closure addendum — real iPhone production regression

Status: **MOBILE ACCEPTANCE REOPENED**

The earlier S10A Closure Record remains historical evidence for the activation,
same-origin service session, Archive auto-connect, recovery workflow and public
return work. Its mobile Audio Editor acceptance statement is superseded by this
addendum.

After activation of source `00087057a233ed40500d77706d54f8b9b22df45d`, a
physical iPhone reproduced a production failure on the exact Archive record
“Яаков”. Authentication, Archive auto-connect, record selection, source-part
verification and Editor opening passed. Waveform preparation for the three real
M4A tracks failed with “Не удалось декодировать аудио для формы сигнала.” while
the same record passed on desktop.

The previous physical-iPhone PASS used a synthetic 3,747.648-second fixture of
only 1,767,839 bytes. It did not reproduce the approximately 49 MiB three-track
Archive multipart workload and therefore was not equivalent acceptance evidence.
Those results are retained as unit/device-harness history, not production-record
acceptance.

Final mobile closure requires a separately authorized production activation and
a cold-cache physical-iPhone test of the exact “Яаков” record:

1. common service login and Archive auto-connect;
2. open the exact record and generate all three server-side waveforms;
3. verify all timelines, playback and a basic selection;
4. refresh and repeat;
5. close and reopen the record;
6. verify the warm-cache path;
7. confirm `ARCHIVE_MUTATIONS=0`.

Android Chrome and an alternative Android browser remain a separate mandatory
gate unless their absence is explicitly accepted again as residual risk.

No new production, VM, Archive, secret, timer or recovery mutation is evidenced
by this addendum.
