#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

CORE_PAYLOAD_SHA = "0f46e824a6955c11b91ab9d64b95b10fc0d6e971f1ff7099ca446fa0f9de9113"
CORE_SOURCE_SHA = "1c05f173076a8900c472b0f0f93fd3959461a6db8623ca5fb019d0e931506527"
V33_PAYLOAD_SHA = "e73316a720647fd156f96fbb4375987979bc525c310b31b8bd5e36e9e042e575"
V33_SOURCE_SHA = "ae88701e4e1bd3162921efeb4dc826e0c513b2ddad2bc33d6cc819ea5087de2e"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(str(x) for x in cmd), flush=True)
    subprocess.run(cmd, check=True, env=env)


def restore_core(root: Path) -> Path:
    parts = sorted((root / "automation/runner_parts").glob("part-*.b64"))
    if not parts:
        raise SystemExit("RUNNER_NOT_READY: missing core runner parts")
    payload = b"".join(p.read_bytes() for p in parts)
    if sha256_bytes(payload) != CORE_PAYLOAD_SHA:
        raise SystemExit("RUNNER_NOT_READY: core payload checksum mismatch")
    raw = base64.b64decode(payload)
    import gzip
    source = gzip.decompress(raw)
    if sha256_bytes(source) != CORE_SOURCE_SHA:
        raise SystemExit("RUNNER_NOT_READY: core source checksum mismatch")
    out = root / "automation/production_runner.py"
    out.write_bytes(source)
    return out


def restore_v33(root: Path) -> Path:
    payload_path = root / "automation/v33/v33_finalize.py.gz.b64"
    if not payload_path.exists():
        raise SystemExit("RUNNER_NOT_READY: missing V3.3 finalizer payload")
    payload = payload_path.read_bytes()
    if sha256_bytes(payload) != V33_PAYLOAD_SHA:
        raise SystemExit("RUNNER_NOT_READY: V3.3 payload checksum mismatch")
    import gzip
    source = gzip.decompress(base64.b64decode(payload))
    if sha256_bytes(source) != V33_SOURCE_SHA:
        raise SystemExit("RUNNER_NOT_READY: V3.3 source checksum mismatch")
    out = root / "automation/v33_finalize.py"
    out.write_bytes(source)
    return out


def validate_job(job: dict) -> None:
    if job.get("mode") != "production" or job.get("enabled") is not True:
        raise SystemExit("JOB_CONTRACT_ERROR: production job must be enabled")
    sb = job.get("storyboard") or {}
    if not sb.get("locked"):
        raise SystemExit("JOB_CONTRACT_ERROR: storyboard must be locked")
    if job.get("visualProfile") != "conhan-visual-v1" and sb.get("visualProfile") != "conhan-visual-v1":
        raise SystemExit("JOB_CONTRACT_ERROR: visualProfile=conhan-visual-v1 required")
    pages = sb.get("pages") or []
    if not pages:
        raise SystemExit("JOB_CONTRACT_ERROR: storyboard has no pages")
    for page in pages:
        elements = page.get("elements") or []
        if not 3 <= len(elements) <= 4:
            raise SystemExit(f"JOB_CONTRACT_ERROR: {page.get('sceneId')} must have 3-4 elements")
        expected_slots = {"top", "mid", "bottom"} if len(elements) == 3 else {"tl", "tr", "bl", "br"}
        actual_slots = {str(e.get("slot")) for e in elements}
        if actual_slots != expected_slots:
            raise SystemExit(f"JOB_CONTRACT_ERROR: {page.get('sceneId')} slots={sorted(actual_slots)} expected={sorted(expected_slots)}")
        seq = [e.get("sequence") for e in elements]
        if seq != list(range(1, len(elements) + 1)):
            raise SystemExit(f"JOB_CONTRACT_ERROR: {page.get('sceneId')} sequence must be 1..N")
        for e in elements:
            if not e.get("anchorText"):
                raise SystemExit(f"JOB_CONTRACT_ERROR: missing anchorText {page.get('sceneId')}/{e.get('id')}")
            if not e.get("renderKind"):
                raise SystemExit(f"JOB_CONTRACT_ERROR: missing renderKind {page.get('sceneId')}/{e.get('id')}")
            if not e.get("mustRenderAs"):
                raise SystemExit(f"JOB_CONTRACT_ERROR: missing mustRenderAs {page.get('sceneId')}/{e.get('id')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--fixture-audio")
    ap.add_argument("--fixture-srt")
    args = ap.parse_args()

    root = Path.cwd()
    job_path = Path(args.job)
    out_dir = Path(args.out)
    upstream = Path(args.upstream)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    validate_job(job)

    # Decode transport-safe assets and install the approved drawing hand into upstream.
    runtime_assets = root / "automation/v33/runtime-assets"
    run([
        sys.executable,
        str(root / "automation/v33/prepare_portable_assets.py"),
        "--source-dir", str(root / "automation/v33/assets_b64"),
        "--out", str(runtime_assets),
        "--upstream", str(upstream),
    ])

    core = restore_core(root)
    v33 = restore_v33(root)
    run([sys.executable, "-m", "py_compile", str(core), str(v33)])

    core_job = copy.deepcopy(job)
    core_job["imageProvider"] = "local-doodle-v2"
    compat_job = root / "automation/jobs/core-compat.json"
    compat_job.parent.mkdir(parents=True, exist_ok=True)
    compat_job.write_text(json.dumps(core_job, ensure_ascii=False, indent=2), encoding="utf-8")

    core_cmd = [
        sys.executable, str(core),
        "--job", str(compat_job),
        "--out", str(out_dir),
        "--upstream", str(upstream),
    ]
    if args.fixture_audio or args.fixture_srt:
        if not (args.fixture_audio and args.fixture_srt):
            raise SystemExit("SELF_TEST_ERROR: fixture audio and SRT must be supplied together")
        core_cmd += ["--fixture-audio", args.fixture_audio, "--fixture-srt", args.fixture_srt]
    run(core_cmd, env=os.environ.copy())

    run([
        sys.executable, str(v33),
        "--job", str(job_path),
        "--out", str(out_dir),
        "--upstream", str(upstream),
        "--assets", str(out_dir / "v33-assets"),
        "--character-sheet", str(runtime_assets / "conhan-front.png"),
        "--eraser-hand", str(runtime_assets / "eraser-hand.png"),
    ], env=os.environ.copy())

    required = [
        out_dir / "final/final.mp4",
        out_dir / "project.zip",
        out_dir / "status.json",
        out_dir / "qc/v33-runner-qc.json",
        out_dir / "qc/source-contact-sheet.jpg",
        out_dir / "qc/final-contact-sheet.jpg",
    ]
    missing = [str(p) for p in required if not p.exists() or p.stat().st_size == 0]
    if missing:
        raise SystemExit("RUNNER_FAILED: missing deliverables: " + ", ".join(missing))
    status = json.loads((out_dir / "status.json").read_text(encoding="utf-8"))
    qc = json.loads((out_dir / "qc/v33-runner-qc.json").read_text(encoding="utf-8"))
    if status.get("state") != "completed" or status.get("runnerVersion") != "3.3.0":
        raise SystemExit("RUNNER_FAILED: invalid V3.3 status")
    if qc.get("pass") is not True:
        raise SystemExit("QC_FAILED: deterministic runner QC failed")
    if qc.get("requiresChatGPTVisionGate") is not True:
        raise SystemExit("QC_FAILED: independent vision gate must remain mandatory")
    print("V3.3 RUNNER PASS. Independent ChatGPT vision gate is still mandatory before FINAL.")


if __name__ == "__main__":
    main()
