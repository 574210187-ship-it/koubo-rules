# ClipFlow Visual v0.6.0

This is the only production package for this workflow. It inherits the v0.4.8
structure—strict global cut planning, opening-frame stills, two ZIPs plus a
standalone TXT, verification, and append-only Feishu handoff—while using only
decoded video frames as its text evidence.

## Non-negotiable gates

- Every encoded segment must be strictly longer than 3 seconds and no longer
  than 8 seconds.
- A cut must be a verified visible-caption sentence endpoint. The planner gives
  scene boundaries priority only among legal endpoints.
- The opening JPG is selected from the first ten original decoded frames by
  least visible text, then receives its matching `C001`-style watermark.
- The only success payload is `videos_and_screenshot.zip`,
  `supporting_materials.zip`, and UTF-8-without-BOM `文案.txt`.
- The upload contract is append-only to `处理后音视频`; the existing Feishu MCP
  must read back all three remote attachments and their SHA-256 values.

## Visual evidence gates

Before any segment is encoded, the program writes `cut_conflict.json` and exits
with status 2 when any of the following occurs:

1. `OCR_EMPTY`: no visible subtitle text was found in multi-frame sampling.
2. `OCR_UNRELIABLE`: there were isolated readings but no reliable multi-frame
   cue.
3. `SENTENCE_END_UNVERIFIABLE`: visible text exists but no complete sentence
   endpoint can be certified from visible terminal punctuation or a separately
   supplied visual-only review bound to this run's OCR timeline.

The review file is a safety gate, not a shortcut: it must declare
`visible_video_frames_only`, carry the SHA-256 of this run's
`visual_ocr_timeline.json`, reference an existing cue, and provide visual
evidence for each endpoint. The program rejects it otherwise.

## Run

```bash
clipflow-visual run --input source.mp4 --out output
```

When a visual reviewer has verified valid complete endpoints, rerun into an
empty output directory with its timeline-bound review:

```bash
clipflow-visual run --input source.mp4 --out output --review-json review.json
```

No earlier package, especially v0.5, is a production fallback.
