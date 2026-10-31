# ClipFlow v0.6 agent contract

Use only this v0.6 source tree. Do not select or reconstruct any earlier
release as a fallback.

Before encoding, require a verified input video, reliable multi-frame visible
text, and verified sentence endpoints. A failure is a `cut_conflict.json` HOLD,
not an approximate cut. Never relax the `(3, 8]` duration contract.

After a local PASS, use the existing Feishu MCP only to append the exact three
artifacts described by `feishu_append_contract.json`, then re-read the target
record and verify all SHA-256 values. Keep prior attachments intact.
