#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORFS_IMAGE = "openroad/orfs@sha256:4886dd9c9723ea5539c2bfc1d6ceaf556f71f5827908c569523e430656ecec5c"

def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def launch(product_result):
    product_result = Path(product_result).resolve()
    data = json.loads(product_result.read_text())

    if data.get("status") != "EVIDENCE_COMPLETE":
        raise RuntimeError("product result is not EVIDENCE_COMPLETE")

    gds_info = data.get("gds") or {}
    gds_rel = gds_info.get("path")
    expected_sha = gds_info.get("sha256")

    if not gds_rel or not expected_sha:
        raise RuntimeError("final GDS evidence missing")

    gds = ROOT / gds_rel
    final_def = gds.with_name("6_final.def")

    if not gds.is_file():
        raise RuntimeError("final GDS missing: " + str(gds))
    if not final_def.is_file():
        raise RuntimeError("final DEF missing: " + str(final_def))

    actual_sha = sha256_file(gds)
    if actual_sha != expected_sha:
        raise RuntimeError("final GDS SHA256 mismatch")

    display = os.environ.get("DISPLAY")
    wayland = os.environ.get("WAYLAND_DISPLAY")

    if not display:
        raise RuntimeError("DISPLAY is not set")

    name = "accelclosure-klayout-" + actual_sha[:12]
    container_gds = "/workspace/AccelClosure/" + gds_rel

    command = [
        "docker", "run", "--rm", "-d",
        "--name", name,
        "-e", "DISPLAY=" + display,
    ]

    if wayland:
        command.extend(["-e", "WAYLAND_DISPLAY=" + wayland])

    command.extend([
        "-e", "XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir",
        "-e", "QT_QPA_PLATFORM=xcb",
        "-e", "LIBGL_ALWAYS_SOFTWARE=1",
        "-v", "/tmp/.X11-unix:/tmp/.X11-unix",
        "-v", "/mnt/wslg:/mnt/wslg",
        "-v", str(ROOT) + ":/workspace/AccelClosure",
        ORFS_IMAGE,
        "/usr/bin/klayout",
        container_gds,
    ])

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError("KLayout launch failed: " + result.stderr.strip())

    print("FINAL_ARTIFACT_GATE=PASS")
    print("FINAL_GDS=" + str(gds))
    print("FINAL_DEF=" + str(final_def))
    print("GDS_SHA256=" + actual_sha)
    print("KLAYOUT_CONTAINER=" + result.stdout.strip())
    print("OPENING_FINAL_LAYOUT=PASS")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-result", required=True)
    args = parser.parse_args()
    launch(args.product_result)

if __name__ == "__main__":
    main()
