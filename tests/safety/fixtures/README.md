# S10A mobile waveform fixture

`s10a-long-aac-lc-3747s.m4a` is a synthetic silent AAC-LC/M4A file used only
for long-duration waveform regression. It contains no user or Archive audio.

- Duration: `3747.648` seconds
- Codec/profile: AAC LC
- Sample rate/channels: 48000 Hz, stereo
- Size: `1767839` bytes
- SHA-256: `dc6446f9e6f32145ca1d6173726a129f28bcfe1479939a4b37279383580f1d0b`

It was generated locally with FFmpeg from `anullsrc`; the committed hash is the
canonical fixture identity. Tests do not regenerate it or depend on a host
FFmpeg executable.
