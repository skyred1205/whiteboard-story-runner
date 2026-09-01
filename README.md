# whiteboard-story-runner

External GitHub Actions production runner for **Tạo video bảng trắng V3.3**. ChatGPT/Skill owns script, semantic storyboard and the final visual review. GitHub owns LucyLab TTS, timing, deterministic visual generation, pinned whiteboard rendering, eraser transitions, captions, technical QC and MP4 packaging. Heavy production rendering does not run inside ChatGPT Work/Codex.

## Architecture

```text
ChatGPT Skill
  -> locked semantic storyboard + renderKind/mustRenderAs
  -> automation/jobs/current.json
  -> GitHub Whiteboard Production
     -> core runner 3.1.1: LucyLab + SRT + timeline/project contract
     -> V3.3 finalizer 3.3.0: conhan-visual-v1 + render + eraser + orange captions + QC contact sheets
  -> whiteboard-current artifact
  -> mandatory ChatGPT vision gate
  -> FINAL only when vision gate passes
```

## Production contract

- Branch: `chatgpt-tts`
- Job: `automation/jobs/current.json`
- Workflow: `.github/workflows/whiteboard-production.yml`
- Artifact: `whiteboard-current`
- Effective runner: `3.3.0`
- Visual provider/profile: `conhan-visual-v1`
- Upstream renderer: `geeklee/srt-whiteboard-animation` `v1.0.0`
- Pinned upstream commit: `696a7243c0e6ffb6827676e539c2ca5ebae2bf6b`
- V3.3 payload: `automation/v33/v33_finalize.py.gz.b64`
- Approved compact character reference: `automation/v33/assets/conhan-front.webp`
- Approved eraser-hand reference: `automation/v33/assets/eraser-hand.webp`

The workflow verifies SHA-256 values for both the core runner and V3.3 finalizer before execution.

## V3.3 visual rules

- Vertical 9:16 output, normally 1080 × 1920 at 30 fps.
- Exactly 3–4 primary visual beats per page.
- Every beat requires an explicit supported `renderKind`; unsupported kinds fail instead of silently falling back to an unrelated icon.
- `mustRenderAs` is part of the semantic contract.
- Fixed Cổ Nhân identity uses the approved character reference for character beats.
- Drawing phase uses the pinned upstream pen-hand after sanitizing the marker barrel so foreign text is not visible.
- Page transition uses a visible hand holding an eraser and ends on clean paper.
- Captions are hard-gated to one line and at most 6 words, with dark text, warm paper fill and orange outer border near the bottom.
- V3.3 scene generator enforces a clear caption safe zone and minimum per-object pixel occupancy to reject tiny visuals.

## Two-layer QC — mandatory

Runner `PASS` is **not enough to call a video FINAL**.

Layer 1 — GitHub runner QC:
- schema/storyboard contract;
- explicit render kinds;
- object pixel occupancy;
- caption safe zone;
- caption one-line/word-count rule;
- codecs/duration/artifacts;
- transition output.

Layer 2 — ChatGPT vision gate:
- compare `qc/source-contact-sheet.jpg` against storyboard + `mustRenderAs`;
- inspect `qc/final-contact-sheet.jpg` for layout density, character identity, pen-hand and caption style;
- inspect `qc/transition-contact-sheet.jpg` for visible eraser-hand and clean erase behavior;
- reject the run as `VISUAL_QC_FAILED` if semantics or style are wrong even when GitHub runner QC says pass.

The artifact records `requiresChatGPTVisionGate: true` to prevent a metadata-only PASS from being mistaken for final approval.

## Artifact contract

`whiteboard-current` contains at least:

```text
final/final.mp4
project.zip
status.json
qc-report.json
qc/v33-runner-qc.json
qc/source-contact-sheet.jpg
qc/final-contact-sheet.jpg
qc/transition-contact-sheet.jpg   # when the video has erase transitions
manifest.json
script.txt
storyboard.json
project.json
audio/
scenes/
v33-assets/
```

## Self-test

`.github/workflows/whiteboard-runner-self-test.yml` is secret-free. It uses fixture audio/SRT but exercises:
- core project/timing pipeline;
- V3.3 `conhan-visual-v1` source generation;
- approved character/eraser assets;
- pinned upstream line→color renderer;
- erase transition;
- single-line orange caption pipeline;
- V3.3 QC/contact-sheet generation.

A successful self-test proves the compute/render plane. Live LucyLab production still depends on the GitHub Actions secret `LUCYLAB_API_KEY`.

## TTS-only diagnostics

- Job: `automation/jobs/tts.json`
- Workflow: `.github/workflows/lucylab-tts.yml`
- Artifact: `lucylab-current`

TTS-only and production workflows share the LucyLab concurrency group so exports do not overlap.

## Security

- Never commit LucyLab API keys.
- Store the key only as GitHub Actions secret `LUCYLAB_API_KEY`.
- Never put secrets in job JSON, logs or artifacts.

## Dispatch

Write a schema-v2 production payload to `automation/jobs/current.json` on branch `chatgpt-tts`. Production jobs must use `visualProfile: "conhan-visual-v1"`, explicit `renderKind` per element, and a locked storyboard. After GitHub success, download `whiteboard-current` and perform the mandatory ChatGPT vision gate before reporting FINAL.
