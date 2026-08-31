# whiteboard-story-runner

GitHub Actions bridge for Whiteboard Story Co Nhan.

## Security
- Never commit LucyLab API keys.
- Store the key only as the Actions secret `LUCYLAB_API_KEY`.
- Job payloads are written to `automation/jobs/current.json` on branch `chatgpt-tts`.
- TTS outputs are uploaded as the workflow artifact `lucylab-current` and retained for 7 days.

## Flow
1. ChatGPT writes a job JSON to `automation/jobs/current.json`.
2. A push to branch `chatgpt-tts` triggers `.github/workflows/lucylab-tts.yml`.
3. The runner calls LucyLab `getUserVoices`, then `ttsLongText`, then polls `getExportStatus`.
4. The runner downloads `voice.wav` and `subtitles.srt`.
5. GitHub Actions uploads them as artifact `lucylab-current`.

The repository intentionally contains no API secret.
