#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHIA_PYTHON = Path(
    os.environ.get(
        "ACCELCLOSURE_CHIA_PYTHON",
        str(Path.home() / "miniconda3/envs/chia_env/bin/python"),
    )
)
CLI = ROOT / "src/accelclosure_cli.py"
GUI = ROOT / "gui/app.py"


def run(args: list[str], timeout: int = 90) -> tuple[int, str]:
    env = os.environ.copy()
    env.setdefault("ACCELCLOSURE_ROOT", str(ROOT))
    env.setdefault("GOOGLE_CLOUD_PROJECT", "continual-rhino-507506-f6")
    env.setdefault("GOOGLE_CLOUD_LOCATION", "global")
    env.setdefault("RAY_ADDRESS", "172.17.28.2:6379")
    proc = subprocess.run(
        [str(CHIA_PYTHON), str(CLI), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout


def require(condition: bool, label: str, detail: str = "") -> None:
    if not condition:
        print(f"{label}=FAIL")
        if detail:
            print(detail)
        raise SystemExit(1)
    print(f"{label}=PASS")


require(CHIA_PYTHON.exists(), "GUI_BACKEND_PYTHON_GATE", str(CHIA_PYTHON))
require(CLI.exists(), "GUI_CLI_GATE", str(CLI))
require(GUI.exists(), "GUI_SOURCE_GATE", str(GUI))

compile_proc = subprocess.run(
    [sys.executable, "-m", "py_compile", str(GUI)],
    cwd=ROOT,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
require(compile_proc.returncode == 0, "GUI_COMPILE_GATE", compile_proc.stdout)

source = GUI.read_text(encoding="utf-8")
require('"ws", "os", "is"' in source, "GUI_DATAFLOW_SELECTOR_GATE")
require("disabled=not closure_supported" in source, "GUI_UNSUPPORTED_CLOSURE_GUARD_GATE")
require("PLUGIN EXTENSION" in source, "GUI_PLUGIN_DISCLOSURE_GATE")

rc, out = run(["status"])
require(rc == 0 and "ACCELCLOSURE_STATUS=READY" in out, "GUI_STATUS_WORKFLOW_GATE", out)

for flow in ["ws", "os", "is"]:
    rc, out = run([
        "plan",
        "--rows", "8",
        "--columns", "8",
        "--dataflow", flow,
        "--arithmetic", "int8",
        "--frequency", "180",
        "--objective", "latency",
    ])
    require(rc == 0, f"GUI_PLAN_{flow.upper()}_RETURN_GATE", out)
    normalized = out.upper()
    require("VALID_DESIGN_SPACE_REQUEST" in normalized, f"GUI_PLAN_{flow.upper()}_VALIDITY_GATE", out)
    if flow == "ws":
        require("DATAFLOW_PLUGIN_EXTENSION" not in normalized, "GUI_PLAN_WS_BACKEND_GATE", out)
    else:
        require("DATAFLOW_PLUGIN_EXTENSION" in normalized, f"GUI_PLAN_{flow.upper()}_PLUGIN_GATE", out)

rc, out = run([
    "advise",
    "--model", "tinyllama",
    "--scenario", "decode",
    "--objective", "area",
])
require(rc == 0, "GUI_ADVISOR_WORKFLOW_GATE", out)

rc, out = run([
    "explain",
    "--model", "tinyllama",
    "--scenario", "decode",
    "--objective", "area",
])
require(rc == 0, "GUI_EXPLAIN_WORKFLOW_GATE", out)

runs_dir = ROOT / "results/runs"
results = list(runs_dir.glob("*/artifacts/product_result.json")) if runs_dir.exists() else []
require(bool(results), "GUI_RESULT_DISCOVERY_GATE")
latest = max(results, key=lambda p: p.stat().st_mtime)
try:
    payload = json.loads(latest.read_text(encoding="utf-8"))
except Exception as exc:
    require(False, "GUI_RESULT_JSON_GATE", str(exc))
else:
    require(isinstance(payload, dict) and bool(payload), "GUI_RESULT_JSON_GATE")
    print(f"GUI_RESULT_SOURCE={latest.relative_to(ROOT)}")

require((ROOT / "src/layout_viewer.py").exists(), "GUI_KLAYOUT_ACTION_GATE")
require((ROOT / "bin/accelclosure-openroad").exists(), "GUI_OPENROAD_ACTION_GATE")

print("GUI_WORKFLOW_VALIDATION=PASS")
print("NOTE=No autonomous EDA run was launched by this validation.")
