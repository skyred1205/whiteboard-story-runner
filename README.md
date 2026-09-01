# whiteboard-story-runner

External GitHub Actions runner for **Whiteboard Story Co Nhan**.

The repository separates ChatGPT orchestration from heavy production compute so a normal chat can prepare/dispatch a locked storyboard while GitHub performs TTS, scene generation, whiteboard rendering, caption burn and MP4 packaging.

## Production flow

1. ChatGPT writes a schema-v2 production job to `automation/jobs/current.json` on branch `chatgpt-tts`.
2. `.github/workflows/whiteboard-production.yml` starts automatically.
3. The runner validates the locked storyboard (3–4 elements per page).
4. LucyLab creates voice + raw SRT using the Actions secret `LUCYLAB_API_KEY`.
5. The runner maps storyboard anchors to real SRT timing.
6. `local-doodle-v1` creates one deterministic source scene per page.
7. The runner creates page specs, annotations and scene QC.
8. It renders line-art -> color with pen hand, inserts hold + eraser transitions, and retimes audio/captions around those transitions.
9. FFmpeg burns short bottom captions and exports H.264/AAC MP4 at 1080x1920.
10. GitHub uploads artifact `whiteboard-current` for 7 days.

Production artifact includes at least:

- `final/final.mp4`
- `project.zip`
- `status.json`
- `qc-report.json`
- audio/SRT/captions
- storyboard/project metadata
- per-scene source, annotation and QC files

## TTS-only compatibility

`.github/workflows/lucylab-tts.yml` remains available for legacy/TTS-only jobs and uploads `lucylab-current`. Production and TTS workflows share concurrency group `lucylab-whiteboard` to avoid overlapping LucyLab jobs.

## Security

- Never commit LucyLab API keys.
- Store the key only as GitHub Actions secret `LUCYLAB_API_KEY`.
- Do not put provider secrets in `automation/jobs/current.json`.
- If LucyLab reports `Invalid or revoked API key`, update the repository secret in GitHub Settings rather than putting the key in chat or source code.

## Current source-generation note

`local-doodle-v1` is a deterministic baseline illustration generator designed to obey storyboard semantics/layout and make remote production self-contained. It is not an AI image model and should not be described as photorealistic or as an exact reproduction of the golden-reference art style.
