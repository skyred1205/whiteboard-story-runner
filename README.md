# whiteboard-story-runner

External GitHub Actions runner for **Whiteboard Story Cổ Nhân**. ChatGPT/Skill prepares a locked production job; GitHub performs TTS, scene generation, upstream whiteboard rendering, eraser transitions, subtitles, technical QA, and MP4 packaging. Production rendering therefore does not run inside ChatGPT Work.

## Architecture

```text
ChatGPT Skill
  -> automation/jobs/current.json
  -> Whiteboard Production workflow
  -> LucyLab voice + SRT
  -> source scenes + annotation
  -> pinned upstream renderer
  -> eraser transitions + subtitles + QA
  -> whiteboard-current artifact
```

## Production contract

- Branch: `chatgpt-tts`
- Job: `automation/jobs/current.json`
- Workflow: `.github/workflows/whiteboard-production.yml`
- Artifact: `whiteboard-current`
- Runner: `3.1.0`
- Upstream repository: `geeklee/srt-whiteboard-animation`
- Upstream release: `v1.0.0`
- Pinned commit: `696a7243c0e6ffb6827676e539c2ca5ebae2bf6b`

The workflow checks out and verifies that exact upstream commit before rendering. It reconstructs the production runner from the checked-in payload parts, verifies both payload and source SHA-256 values, and compiles the runner before use.

## Production outputs

The `whiteboard-current` artifact contains at least:

```text
final/final.mp4
project.zip
status.json
qc-report.json
manifest.json
```

The project bundle also includes the script, LucyLab audio/SRT, scene sources, annotations, intermediate clips, final subtitle files, and the locked job specification.

## Locked rules enforced by the runner

- Vertical 9:16 output, normally 1080 x 1920 at 30 fps.
- Exactly 3 or 4 primary visual objects per page.
- Storyboard must be locked before production.
- Drawing order is line art first, then color.
- A visible eraser transition is inserted between pages.
- Subtitle chunks target 4–6 words and remain in the caption-safe zone.
- Final output must pass codec, dimensions, duration, storyboard, scene-occupancy, caption, and transition checks.

## Scene source provider

The working baseline provider is `local-doodle-v2`. It deterministically creates clean whiteboard source scenes from the locked storyboard and is suitable for end-to-end production and regression testing. A future character-consistent generative image provider can be added behind the same provider contract without changing the Skill-to-runner architecture.

## TTS-only workflow

A separate TTS-only job is available for diagnostics:

- Job: `automation/jobs/tts.json`
- Workflow: `.github/workflows/lucylab-tts.yml`
- Artifact: `lucylab-current`

Production jobs no longer trigger the TTS-only workflow, preventing duplicate LucyLab exports. Both workflows share one concurrency group so only one LucyLab export is started at a time.

## Security

- Never commit LucyLab API keys.
- Store the key only as the GitHub Actions secret `LUCYLAB_API_KEY`.
- The runner reads the secret only during the workflow.
- Logs, job payloads, and output artifacts must not contain the secret.

## Dispatching a production job

Write a schema-v2 production payload to `automation/jobs/current.json` on branch `chatgpt-tts`. A push to that file starts the production workflow. Monitor the matching workflow run and download artifact `whiteboard-current` after it completes.
