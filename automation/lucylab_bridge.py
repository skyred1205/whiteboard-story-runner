#!/usr/bin/env python3
"""LucyLab TTS bridge for GitHub Actions.

Reads one JSON job, calls LucyLab from the GitHub runner, downloads the WAV + SRT,
and writes a small status file. The API key is read only from LUCYLAB_API_KEY.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.lucylab.io/json-rpc"
VOICE_ALIASES = {
    "co-nhan": "vobfq29MDccJJPpsVLHZxV",
    "quang-anh": "24oEtXGic7NhDjXzmDbDvt",
    "huy-vu": "hruBcESGYx2AUWRppNacCd",
    "chi-mai": "cLZiqtzLcKYqwYrWJemAJK",
}


def write_status(out_dir: Path, **data: object) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "status.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def rpc(method: str, input_data: dict, api_key: str, retries: int = 5) -> dict:
    payload = json.dumps({"method": method, "input": input_data}, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "whiteboard-story-runner/1.0",
    }

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(ENDPOINT, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if body.get("error"):
                raise RuntimeError(f"LucyLab RPC error: {body['error']}")
            result = body.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("LucyLab response missing result object")
            return result
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError("LucyLab authentication failed. Check LUCYLAB_API_KEY.") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            last_error = exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("LucyLab returned invalid JSON") from exc

        if attempt < retries:
            delay = min(2 ** (attempt - 1), 12)
            print(f"Temporary LucyLab/network error; retry {attempt}/{retries} in {delay}s")
            time.sleep(delay)

    raise RuntimeError(f"LucyLab request failed after {retries} attempts: {last_error}")


def download(url: str, path: Path, retries: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "whiteboard-story-runner/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp, path.open("wb") as fh:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    fh.write(chunk)
            return
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"Download failed: {last_error}")


def resolve_voice(job: dict) -> tuple[str, str]:
    alias = str(job.get("voiceAlias") or "co-nhan")
    voice_id = str(job.get("voiceId") or VOICE_ALIASES.get(alias, ""))
    if not voice_id:
        raise ValueError(f"Unknown voice alias: {alias}")
    return alias, voice_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--poll-sec", type=float, default=2.5)
    parser.add_argument("--max-wait-sec", type=int, default=900)
    args = parser.parse_args()

    job_path = Path(args.job)
    out_dir = Path(args.out)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job_id = str(job.get("jobId") or "current")

    if not bool(job.get("enabled", False)):
        write_status(out_dir, jobId=job_id, state="skipped", reason="job disabled")
        print("Job is disabled; nothing to do.")
        return 0

    text = str(job.get("text") or "").strip()
    if not text:
        raise SystemExit("Job text is empty")

    speed = float(job.get("speed", 1.0))
    if not 0.5 <= speed <= 2.0:
        raise SystemExit("speed must be between 0.5 and 2.0")

    api_key = os.environ.get("LUCYLAB_API_KEY", "").strip()
    if not api_key:
        write_status(out_dir, jobId=job_id, state="failed", reason="missing LUCYLAB_API_KEY")
        raise SystemExit("LUCYLAB_API_KEY is not configured in GitHub Actions secrets")

    voice_alias, voice_id = resolve_voice(job)

    # Lightweight auth preflight. Do not print the key or the script text.
    voices = rpc("getUserVoices", {"limit": 100, "page": 1}, api_key)
    items = voices.get("items") if isinstance(voices, dict) else None
    if isinstance(items, list) and items:
        known_ids = {str(item.get("id")) for item in items if isinstance(item, dict)}
        if voice_id not in known_ids:
            print("Warning: requested voice ID was not returned by getUserVoices; continuing anyway.")

    created = rpc(
        "ttsLongText",
        {"text": text, "userVoiceId": voice_id, "speed": speed},
        api_key,
    )
    export_id = str(created.get("projectExportId") or "")
    if not export_id:
        write_status(out_dir, jobId=job_id, state="failed", reason="missing projectExportId")
        raise RuntimeError("LucyLab did not return projectExportId")

    deadline = time.time() + args.max_wait_sec
    while True:
        status = rpc("getExportStatus", {"projectExportId": export_id}, api_key)
        state = str(status.get("state") or "")
        print(f"LucyLab state={state or 'unknown'}")

        if state == "completed":
            audio_url = str(status.get("url") or "")
            srt_url = str(status.get("srtUrl") or "")
            if not audio_url or not srt_url:
                raise RuntimeError("LucyLab completed without audio or SRT URL")
            audio_path = out_dir / "voice.wav"
            srt_path = out_dir / "subtitles.srt"
            download(audio_url, audio_path)
            download(srt_url, srt_path)
            write_status(
                out_dir,
                jobId=job_id,
                state="completed",
                voiceAlias=voice_alias,
                voiceId=voice_id,
                speed=speed,
                projectExportId=export_id,
                audio="voice.wav",
                srt="subtitles.srt",
            )
            print("LucyLab output downloaded successfully.")
            return 0

        if state == "failed":
            write_status(out_dir, jobId=job_id, state="failed", projectExportId=export_id)
            raise RuntimeError("LucyLab export failed")

        if time.time() >= deadline:
            write_status(out_dir, jobId=job_id, state="failed", reason="timeout", projectExportId=export_id)
            raise TimeoutError(f"LucyLab export timed out after {args.max_wait_sec}s")

        time.sleep(max(2.0, args.poll_sec))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
