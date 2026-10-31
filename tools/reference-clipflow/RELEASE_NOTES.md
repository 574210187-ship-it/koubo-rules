# v0.6.0 release record

## Replaced failure modes

- Replaces the old 9.8-second reference behavior with a hard encoded-duration
  contract of `3.000 < seconds <= 8.000`.
- Replaces single-pass OCR with multi-frame RapidOCR cue consolidation.
- Stops before encoding for empty visual text, unreliable visual text, and
  uncertified sentence endpoints.
- Replaces incomplete output with one validated media ZIP, one validated
  evidence ZIP, and one standalone UTF-8 text file.

## Real-video acceptance

Input SHA-256: `e1fa4c96e1877df6215a7e5d8291cbf227e3274e9f65bfc3c6561bf8fa9c797e`

- 79 decoded frame samples; 72 text observations; 16 reliable visible cues.
- With no timeline-bound visual review: `SENTENCE_END_UNVERIFIABLE`, before
  encoding, with `encoded_segments_created=false`.
- With a visual-only review tied to the OCR timeline: five verified segments
  of 7.00, 4.56, 5.28, 6.68, and 4.16 seconds; all package CRC checks passed.

This source release carries no alternate audio-to-text implementation or
dependency. The review gate is intentional: it prevents a screen-text cue from
being silently treated as a proven sentence ending.
