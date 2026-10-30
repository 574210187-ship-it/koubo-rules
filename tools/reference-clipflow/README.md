# Reference ClipFlow v0.4.8

Reference ClipFlow is a first-stage Python + FFmpeg workflow for cutting one original reference MP4 into short numbered clips. The active release produces a final **two ZIP plus one TXT** delivery and can be directed by a connected ChatGPT Work Mode window through a Feishu Bitable record.

It does not run the historical second stage: no new-clip assembly, grading, voice replacement, or burned subtitles.

## Non-negotiable result contract

Every accepted source produces exactly these formal deliverables:

| File | Required contents |
|---|---|
| `videos_and_screenshot.zip` | `segments/NNN_镜头.mp4` and matching `segment_stills/NNN_镜头.jpg` only |
| `supporting_materials.zip` | SRT, per-segment MD, manifest, CSV, style JSON and source-frame samples |
| `文案.txt` | Standalone UTF-8-no-BOM plain transcript; one spoken cue per line, no IDs, timecodes, filenames, Markdown or explanation |

The TXT must not be inside either ZIP. Old `ClipFlow_完整交付.zip`, `numbered_segments.zip` and `subtitle_reference_stylekit.zip` are no longer formal deliveries.

## Quality contract

- Actual encoded duration of every clip is **strictly more than 3 seconds and no more than 8 seconds**.
- Cut points preferentially follow visual shot changes, but every non-final cut must be a credible complete sentence ending from raw ASR or a user-verified SRT. If all three constraints cannot be satisfied, the run writes `cut_conflict.json` and stops.
- One JPG accompanies every MP4. It is selected only from the first ten sequential decoded frames of that clip’s original source, prioritizing fewest Chinese OCR characters, then OCR area, clarity/stability and earlier frame. The matching C-style number watermark is added only after selection.
- `文案.txt` needs trustworthy audio ASR or verified SRT. Visual OCR alone cannot prove speech sentence boundaries or invent spoken copy.
- The packager checks member lists, file sizes, ZIP CRC, sequential numbering, MP4/JPG mapping, manifest mapping and standalone TXT encoding before output.

## Local use

Prerequisites: Python 3.10+, `ffmpeg`, `ffprobe`, Chinese Tesseract (`chi_sim` or `HanS`) and an ASR runtime, or a verified SRT.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[asr,test]'
clipflow doctor
clipflow reference --input "source.mp4" --out "delivery" --model small --language zh
```

With a verified SRT:

```bash
clipflow reference --input "source.mp4" --out "delivery" --srt "checked.srt"
```

A successful output directory includes working files (`segments/`, `segment_stills/`, SRT, MD, manifest, samples) and these three final upload files:

```text
delivery/
├── videos_and_screenshot.zip
├── supporting_materials.zip
└── 文案.txt
```

Run the delivery tests with:

```bash
pytest -q tests/test_delivery.py
```

## Pure online Work Mode use

The online workflow is defined in [ONLINE_WORK_MODE.md](ONLINE_WORK_MODE.md); its copy/paste command is [PROMPT_FOR_CHATGPT.md](PROMPT_FOR_CHATGPT.md). It uses this Bitable binding:

- app: `TRbibTAzmagpV4shYbcchcIVnhd`
- table: `tblgYhWtUJDDKJjJ`
- view: `剧情` / `vewG1nXQcP`
- input: `对标视频、图文`
- output: `处理后音、视频`

The controller selects only rows whose output is empty and whose fields satisfy the documented `ZED` / `二次分类` predicate. It processes rows serially and append-uploads exactly the three final files, then re-reads each attachment and verifies complete SHA-256.

**Important:** a Feishu resource link, temporary URL, remote SHA or `chatgpt_widget_transfer_ready` does not put an MP4 in the Work Mode media runtime. Until the connector returns a real current-runtime path that passes `stat`, local SHA-256 and `ffprobe`, the correct result is `INPUT_BRIDGE_HOLD`; it must not process or upload a fabricated delivery.

## Repository boundary

This repository contains code, tests and public instructions only. Do not commit user video, audio, transcripts, private fonts, OAuth credentials, API keys or attachment tokens.