#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import shutil
from pathlib import Path

from PIL import Image

EXPECTED = {
    "conhan-front": "6a4be8f49c86da61e54e89bb21e907d8c616aca5a9dc6676b79b3525d21cb1c7",
    "eraser-hand": "e52b5585b4d3f62ed4f5556893ad2d902049643ec21890fad53ee4cf322250b4",
    "drawing-hand": "c86c019a49a39e4021c6bd5d356d48323cba3f44f5f37f8d5bc3db1855dad92e",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def decode(name: str, src: Path, dst: Path) -> None:
    raw = base64.b64decode("".join(src.read_text(encoding="utf-8").split()), validate=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(raw)
    observed = sha256(dst)
    if observed != EXPECTED[name]:
        raise SystemExit(f"ASSET_INTEGRITY_ERROR: {name} sha256={observed}, expected={EXPECTED[name]}")
    with Image.open(dst) as im:
        im.load()
        if im.width < 64 or im.height < 120:
            raise SystemExit(f"ASSET_INTEGRITY_ERROR: {name} too small: {im.size}")
        print(f"VALID {name}: {im.size} {im.mode} sha256={observed}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default="automation/v33/assets_b64")
    ap.add_argument("--out", default="automation/v33/runtime-assets")
    ap.add_argument("--upstream", required=True)
    args = ap.parse_args()

    src = Path(args.source_dir)
    out = Path(args.out)
    mapping = {
        "conhan-front": (src / "conhan-front.b64", out / "conhan-front.png"),
        "eraser-hand": (src / "eraser-hand.b64", out / "eraser-hand.png"),
        "drawing-hand": (src / "drawing-hand.b64", out / "drawing-hand.png"),
    }
    for name, (s, d) in mapping.items():
        if not s.exists():
            raise SystemExit(f"ASSET_INTEGRITY_ERROR: missing {s}")
        decode(name, s, d)

    upstream_hand = Path(args.upstream) / "assets" / "drawing-hand.png"
    upstream_hand.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out / "drawing-hand.png", upstream_hand)
    print(f"Installed approved drawing-hand into upstream: {upstream_hand}")


if __name__ == "__main__":
    main()
