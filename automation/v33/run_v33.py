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


def apply_v33_runtime_fixes(path: Path) -> None:
    """Apply narrowly-scoped fixes after validating the immutable V3.3 payload."""
    text = path.read_text(encoding="utf-8")
    patches = [
        (
            "        rr(d,(cx-int(w*.31),yy+70,cx+int(w*.31),min(y1-12,yy+70+bh)),16,'#6F9F6D',width=5)",
            "        fy1=y1-12; fy0=max(y0+12,min(yy+35,fy1-max(38,min(bh,80)))); rr(d,(cx-int(w*.31),fy0,cx+int(w*.31),fy1),16,'#6F9F6D',width=5)",
            "compound-money final stack bounds",
        ),
        (
            "    n=max(2,round(duration_ms*fps/1000)); # serpentine sweeps across content area only",
            "    n=max(3,round(duration_ms*fps/1000)); clear_frames=2 if n>=6 else 1; sweep_n=max(2,n-clear_frames)  # reserve a clean hold within eraseMs",
            "eraser clean-hold frame budget",
        ),
        (
            "    rows=5; radius=150",
            "    rows=5; radius=190",
            "eraser sweep overlap",
        ),
        (
            "    for i in range(n):\n        p=i/(n-1); pos=p*(rows-1e-6); row=min(rows-1,int(pos)); frac=pos-row",
            "    for i in range(sweep_n):\n        p=i/(sweep_n-1); pos=p*(rows-1e-6); row=min(rows-1,int(pos)); frac=pos-row",
            "eraser sweep duration",
        ),
        (
            "        md.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)\n        frame=Image.composite(bg,src,mask)",
            "        md.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)\n        if i==sweep_n-1: md.rectangle((0,0,W,H),fill=255)\n        frame=Image.composite(bg,src,mask)",
            "eraser final full clear",
        ),
        (
            "        frame.alpha_composite(hand,(hx,hy)); frame.convert('RGB').save(frames_dir/f'{i:05d}.jpg',quality=90)\n    run(['ffmpeg','-y','-loglevel','error','-framerate',str(fps),'-i',str(frames_dir/'%05d.jpg'),'-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(output)])",
            "        frame.alpha_composite(hand,(hx,hy)); frame.convert('RGB').save(frames_dir/f'{i:05d}.jpg',quality=90)\n    for i in range(sweep_n,n):\n        bg.convert('RGB').save(frames_dir/f'{i:05d}.jpg',quality=90)\n    run(['ffmpeg','-y','-loglevel','error','-framerate',str(fps),'-i',str(frames_dir/'%05d.jpg'),'-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(output)])",
            "eraser blank tail inside transition",
        ),
    ]
    for old, new, label in patches:
        if old not in text:
            raise SystemExit(f"RUNNER_NOT_READY: expected V3.3 patch point not found: {label}")
        text = text.replace(old, new, 1)
        print(f"Applied V3.3 runtime fix: {label}", flush=True)
    path.write_text(text, encoding="utf-8")


def apply_upstream_runtime_fixes(upstream: Path) -> Path:
    """Patch known defects in the pinned upstream checkout without changing the pin."""
    path = upstream / "scripts/render_stream_whiteboard.py"
    if not path.exists():
        raise SystemExit("RUNNER_NOT_READY: pinned upstream renderer missing")
    text = path.read_text(encoding="utf-8")
    old = "                        self._lay_ink(writer, ink_frames, [], set(), None, allowed)"
    new = "                        self._lay_ink(writer, ink_frames, [], set(), allowed)"
    if old not in text:
        raise SystemExit("RUNNER_NOT_READY: expected upstream empty-grid _lay_ink patch point not found")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print("Applied upstream runtime fix: empty-grid _lay_ink arity", flush=True)
    return path


def build_transition_contact_sheet(out_dir: Path) -> Path | None:
    """Create transition visual-QC and hard-fail if the erase ends with remnants."""
    erase_files = [
        p for p in sorted((out_dir / "scenes").glob("*/erase.mp4"))
        if p.is_file() and p.stat().st_size > 0
    ]
    if not erase_files:
        return None

    import numpy as np
    from PIL import Image

    qc_dir = out_dir / "qc"
    frame_dir = qc_dir / "transition-sample-frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    thumbs: list[Image.Image] = []

    for row, erase in enumerate(erase_files, start=1):
        raw_duration = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(erase),
        ], text=True).strip()
        duration = max(0.05, float(raw_duration))
        for col, frac in enumerate((0.15, 0.55, 0.95), start=1):
            timestamp = min(duration * frac, max(0.0, duration - 0.02))
            frame = frame_dir / f"transition-{row:02d}-{col:02d}.jpg"
            run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{timestamp:.3f}", "-i", str(erase),
                "-frames:v", "1", str(frame),
            ])
            with Image.open(frame) as im:
                thumbs.append(im.convert("RGB").resize((270, 480), Image.Resampling.LANCZOS))

        final_frame = frame_dir / f"transition-{row:02d}-final.png"
        run([
            "ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.035",
            "-i", str(erase), "-frames:v", "1", str(final_frame),
        ])
        with Image.open(final_frame) as im:
            arr = np.array(im.convert("RGB").resize((270, 480), Image.Resampling.BILINEAR), dtype=np.int16)
        corners = np.concatenate([
            arr[:12, :12].reshape(-1, 3), arr[:12, -12:].reshape(-1, 3),
            arr[-12:, :12].reshape(-1, 3), arr[-12:, -12:].reshape(-1, 3),
        ], axis=0)
        bg = np.median(corners, axis=0)
        occupancy = float((np.abs(arr - bg).sum(axis=2) > 36).mean())
        print(f"ERASER_CLEANUP scene={erase.parent.name} occupancy={occupancy:.6f}", flush=True)
        if occupancy > 0.002:
            raise SystemExit(
                f"QC_FAILED: erase transition leaves visible remnants in {erase.parent.name} "
                f"(occupancy={occupancy:.6f})"
            )

    sheet = Image.new("RGB", (810, 480 * len(erase_files)), "white")
    for idx, thumb in enumerate(thumbs):
        row = idx // 3
        col = idx % 3
        sheet.paste(thumb, (col * 270, row * 480))
    out = qc_dir / "transition-contact-sheet.jpg"
    sheet.save(out, format="JPEG", quality=90, optimize=True)
    print(f"TRANSITION_CONTACT_SHEET={out}", flush=True)
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

    runtime_assets = root / "automation/v33/runtime-assets"
    run([
        sys.executable,
        str(root / "automation/v33/prepare_portable_assets.py"),
        "--source-dir", str(root / "automation/v33/assets_b64"),
        "--out", str(runtime_assets),
        "--upstream", str(upstream),
    ])
    upstream_renderer = apply_upstream_runtime_fixes(upstream)

    core = restore_core(root)
    v33 = restore_v33(root)
    apply_v33_runtime_fixes(v33)
    run([sys.executable, "-m", "py_compile", str(core), str(v33), str(upstream_renderer)])

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

    transition_sheet = build_transition_contact_sheet(out_dir)
    required = [
        out_dir / "final/final.mp4",
        out_dir / "project.zip",
        out_dir / "status.json",
        out_dir / "qc/v33-runner-qc.json",
        out_dir / "qc/source-contact-sheet.jpg",
        out_dir / "qc/final-contact-sheet.jpg",
    ]
    if transition_sheet is not None:
        required.append(transition_sheet)
    missing = [str(p) for p in required if not p.exists() or p.stat().st_size == 0]
    if missing:
        raise SystemExit("RUNNER_FAILED: missing deliverables: " + ", ".join(missing))
    status = json.loads((out_dir / "status.json").read_text(encoding="utf-8"))
    qc_path = out_dir / "qc/v33-runner-qc.json"
    qc = json.loads(qc_path.read_text(encoding="utf-8"))
    if transition_sheet is not None:
        qc["transitionContactSheet"] = "qc/transition-contact-sheet.jpg"
        qc["eraserCleanupPass"] = True
        qc_path.write_text(json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8")
    if status.get("state") != "completed" or status.get("runnerVersion") != "3.3.0":
        raise SystemExit("RUNNER_FAILED: invalid V3.3 status")
    if qc.get("pass") is not True:
        raise SystemExit("QC_FAILED: deterministic runner QC failed")
    if qc.get("requiresChatGPTVisionGate") is not True:
        raise SystemExit("QC_FAILED: independent vision gate must remain mandatory")
    print("V3.3 RUNNER PASS. Independent ChatGPT vision gate is still mandatory before FINAL.")


if __name__ == "__main__":
    main()
