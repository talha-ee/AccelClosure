from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
CHIA_PYTHON = Path(
    os.environ.get(
        "ACCELCLOSURE_CHIA_PYTHON",
        str(Path.home() / "miniconda3/envs/chia_env/bin/python"),
    )
)
CLI = ROOT / "src/accelclosure_cli.py"
LAYOUT_VIEWER = ROOT / "src/layout_viewer.py"
RUNS_DIR = ROOT / "results/runs"
GUI_LOG_DIR = ROOT / "logs/gui"

st.set_page_config(
    page_title="AccelClosure",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# -----------------------------------------------------------------------------
# Visual system: flat, Google-inspired, research/product UI
# -----------------------------------------------------------------------------
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@400;500;600&family=Roboto:wght@400;500;600;700;900&display=swap');

:root {
  --g-blue: #1A73E8;
  --g-blue-700: #1557B0;
  --g-blue-50: #E8F0FE;
  --g-red: #EA4335;
  --g-red-50: #FCE8E6;
  --g-yellow: #FBBC04;
  --g-yellow-50: #FEF7E0;
  --g-green: #34A853;
  --g-green-50: #E6F4EA;
  --ink: #172033;
  --ink-soft: #334155;
  --muted: #64748B;
  --line: #D9E2EF;
  --line-soft: #E8EEF7;
  --canvas: #EEF4FB;
  --canvas-2: #F6F9FD;
  --surface: #FFFFFF;
  --navy: #111827;
}

html, body, [class*="css"], .stApp {
  font-family: "Google Sans", "Roboto", Arial, sans-serif !important;
}

html { font-size: 17px !important; }

[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(circle at 88% 5%, rgba(26,115,232,.08), transparent 26%),
    radial-gradient(circle at 8% 12%, rgba(52,168,83,.045), transparent 24%),
    linear-gradient(180deg, var(--canvas-2) 0%, var(--canvas) 100%);
  color: var(--ink);
}

[data-testid="stHeader"] {
  background: transparent !important;
  height: 0 !important;
}

[data-testid="stToolbar"], #MainMenu, footer, [data-testid="stDecoration"] {
  display: none !important;
}

.block-container {
  max-width: 1540px;
  padding-top: 1.05rem;
  padding-bottom: 3rem;
  padding-left: 2.35rem;
  padding-right: 2.35rem;
}

h1, h2, h3, h4, p, label { color: var(--ink); }
h1, h2, h3, h4 {
  font-family: "Google Sans", "Roboto", Arial, sans-serif !important;
  letter-spacing: -0.02em;
}

/* ------------------------------------------------------------------
   Original AccelClosure brand system — accelerator-array inspired mark
   ------------------------------------------------------------------ */
.ac-topbar {
  background: rgba(255,255,255,.96);
  border: 1px solid var(--line);
  border-radius: 20px;
  padding: 18px 22px;
  margin-bottom: 18px;
  box-shadow: 0 1px 2px rgba(15,23,42,.04);
}
.ac-brandrow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}
.ac-brandleft {
  display: flex;
  align-items: center;
  gap: 15px;
}
.ac-chipmark {
  position: relative;
  width: 52px;
  height: 52px;
  border-radius: 14px;
  background: var(--navy);
  border: 1px solid #263449;
  display: grid;
  place-items: center;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.05);
}
.ac-chipmark:before,
.ac-chipmark:after {
  content: "";
  position: absolute;
  inset: -5px 8px;
  border-top: 3px solid var(--g-blue);
  border-bottom: 3px solid var(--g-yellow);
  border-radius: 8px;
  pointer-events: none;
}
.ac-chipmark:after {
  inset: 8px -5px;
  border: 0;
  border-left: 3px solid var(--g-red);
  border-right: 3px solid var(--g-green);
}
.ac-arraygrid {
  width: 26px;
  height: 26px;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-template-rows: repeat(3, 1fr);
  gap: 4px;
}
.ac-arraygrid span {
  width: 6px;
  height: 6px;
  border-radius: 2px;
  background: #fff;
  opacity: .95;
}
.ac-brandname {
  font-size: 1.86rem;
  font-weight: 900;
  line-height: 1;
  letter-spacing: -0.035em;
  color: var(--ink);
}
.ac-brandtag {
  font-size: .9rem;
  color: var(--muted);
  margin-top: 6px;
  font-weight: 500;
}
.ac-statusrow {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 9px;
}
.ac-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 13px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #F9FBFE;
  color: var(--ink-soft);
  font-size: .84rem;
  font-weight: 600;
}
.ac-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  box-shadow: 0 0 0 3px rgba(52,168,83,.10);
}
.ac-dot.on { background: var(--g-green); }
.ac-dot.off { background: var(--g-red); box-shadow: 0 0 0 3px rgba(234,67,53,.10); }

/* Hero */
.ac-hero {
  position: relative;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(330px, .75fr);
  gap: 34px;
  padding: 34px 36px;
  border-radius: 24px;
  background: var(--navy);
  border: 1px solid #1F2C42;
  margin-bottom: 18px;
}
.ac-hero:before {
  content: "";
  position: absolute;
  width: 420px;
  height: 420px;
  right: -170px;
  top: -205px;
  border-radius: 50%;
  background: rgba(26,115,232,.20);
}
.ac-hero:after {
  content: "";
  position: absolute;
  width: 230px;
  height: 230px;
  right: 160px;
  bottom: -170px;
  border-radius: 50%;
  background: rgba(52,168,83,.12);
}
.ac-hero-left, .ac-hero-panel { position: relative; z-index: 1; }
.ac-eyebrow {
  color: #8AB4F8;
  font-size: .80rem;
  font-weight: 700;
  letter-spacing: .14em;
  text-transform: uppercase;
  margin-bottom: 9px;
}
.ac-herotitle {
  color: #FFFFFF;
  font-size: clamp(2.55rem, 4.1vw, 4.15rem);
  font-weight: 900;
  line-height: 1.01;
  max-width: 940px;
  letter-spacing: -0.048em;
}
.ac-herosub {
  max-width: 920px;
  color: #C8D4E5;
  font-size: 1.08rem;
  line-height: 1.6;
  margin-top: 16px;
  font-weight: 400;
}
.ac-colorbar {
  width: 220px;
  height: 5px;
  display: grid;
  grid-template-columns: repeat(4,1fr);
  overflow: hidden;
  border-radius: 999px;
  margin-top: 22px;
}
.ac-colorbar span:nth-child(1){background:var(--g-blue)}
.ac-colorbar span:nth-child(2){background:var(--g-red)}
.ac-colorbar span:nth-child(3){background:var(--g-yellow)}
.ac-colorbar span:nth-child(4){background:var(--g-green)}
.ac-hero-panel {
  align-self: stretch;
  background: #182338;
  border: 1px solid #2C3A52;
  border-radius: 18px;
  padding: 18px 20px;
  min-height: 190px;
}
.ac-panel-kicker {
  color: #94A3B8;
  font-size: .71rem;
  letter-spacing: .12em;
  font-weight: 700;
  text-transform: uppercase;
  margin-bottom: 10px;
}
.ac-panel-row {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 11px 0;
  border-top: 1px solid #2B384D;
}
.ac-panel-row:first-of-type { border-top: 0; }
.ac-panel-icon {
  flex: 0 0 10px;
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 3px;
}
.ac-panel-icon.blue{background:var(--g-blue)}
.ac-panel-icon.yellow{background:var(--g-yellow)}
.ac-panel-icon.green{background:var(--g-green)}
.ac-panel-label {
  color: #8FA0B8;
  font-size: .73rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .06em;
}
.ac-panel-value {
  color: #FFFFFF;
  font-size: .93rem;
  font-weight: 700;
  margin-top: 2px;
}

/* Section language */
.ac-section-title {
  font-size: 1.55rem;
  font-weight: 800;
  letter-spacing: -0.025em;
  margin: 4px 0 5px 0;
  color: var(--ink);
}
.ac-section-sub {
  color: var(--muted);
  font-size: .98rem;
  line-height: 1.55;
  margin-bottom: 18px;
}
.ac-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 21px 22px;
  box-shadow: 0 1px 2px rgba(15,23,42,.025);
}
.ac-card-title {
  font-size: 1.05rem;
  font-weight: 800;
  margin-bottom: 8px;
  color: var(--ink);
}
.ac-small { color: var(--muted); font-size: .88rem; line-height: 1.55; }
.ac-kv {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--line-soft);
  font-size: .91rem;
}
.ac-kv:last-child { border-bottom: 0; }
.ac-kv .k { color: var(--muted); font-weight: 500; }
.ac-kv .v { font-weight: 700; color: var(--ink); }
.ac-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 8px;
  padding: 7px 10px;
  font-size: .78rem;
  font-weight: 700;
  margin-right: 6px;
  margin-top: 8px;
}
.ac-badge.blue { background: var(--g-blue-50); color: #174EA6; }
.ac-badge.red { background: var(--g-red-50); color: #A50E0E; }
.ac-badge.yellow { background: var(--g-yellow-50); color: #7A4F00; }
.ac-badge.green { background: var(--g-green-50); color: #137333; }

/* Streamlit tabs as product navigation */
.stTabs [data-baseweb="tab-list"] {
  gap: 7px;
  background: rgba(255,255,255,.90);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 6px;
  margin: 6px 0 22px 0;
  box-shadow: 0 1px 2px rgba(15,23,42,.025);
}
.stTabs [data-baseweb="tab"] {
  height: 44px;
  border-radius: 9px;
  padding: 0 20px;
  color: var(--ink-soft);
  font-size: .92rem;
  font-weight: 600;
}
.stTabs [aria-selected="true"] {
  color: #FFFFFF !important;
  background: var(--g-blue) !important;
}
.stTabs [data-baseweb="tab-highlight"] { display: none; }

/* Native containers */
[data-testid="stVerticalBlockBorderWrapper"] {
  background: rgba(255,255,255,.94);
  border-color: var(--line) !important;
  border-radius: 18px !important;
}

/* Form controls */
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label,
label[data-testid="stWidgetLabel"] {
  font-size: .92rem !important;
  font-weight: 700 !important;
  color: var(--ink-soft) !important;
}
[data-baseweb="select"] > div,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stTextInput"] input {
  min-height: 48px !important;
  border-radius: 10px !important;
  border-color: #C8D5E5 !important;
  background: #FFFFFF !important;
  color: var(--ink) !important;
  font-size: .98rem !important;
  box-shadow: none !important;
}
[data-baseweb="select"] > div:focus-within,
[data-testid="stNumberInput"] div:focus-within,
[data-testid="stTextArea"] textarea:focus,
[data-testid="stTextInput"] input:focus {
  border-color: var(--g-blue) !important;
  box-shadow: 0 0 0 2px rgba(26,115,232,.10) !important;
}
[data-testid="stTextArea"] textarea {
  min-height: 132px !important;
  font-size: 1rem !important;
  line-height: 1.55 !important;
  padding: 14px 15px !important;
}
[data-testid="stCheckbox"] label p { font-size: .92rem !important; }

/* Buttons */
.stButton > button {
  min-height: 47px;
  border-radius: 10px;
  padding-left: 18px;
  padding-right: 18px;
  font-size: .92rem;
  font-weight: 700;
  border: 1px solid #C8D5E5;
  background: #FFFFFF;
  color: var(--ink);
  box-shadow: none !important;
}
.stButton > button:hover {
  border-color: var(--g-blue);
  color: var(--g-blue);
  background: #F8FBFF;
}
.stButton > button[kind="primary"] {
  background: var(--g-blue) !important;
  color: #FFFFFF !important;
  border-color: var(--g-blue) !important;
}
.stButton > button[kind="primary"]:hover {
  background: var(--g-blue-700) !important;
  border-color: var(--g-blue-700) !important;
}

/* Metrics */
[data-testid="stMetric"] {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 18px 19px;
  min-height: 112px;
}
[data-testid="stMetricLabel"] {
  color: var(--muted);
  font-size: .86rem !important;
  font-weight: 600;
}
[data-testid="stMetricValue"] {
  color: var(--ink);
  font-family: "Google Sans", "Roboto", sans-serif;
  font-size: 1.8rem !important;
  font-weight: 800;
}
[data-testid="stMetricDelta"] { font-size: .78rem !important; }

/* Capability / design-space cards */
.ac-capability {
  background: #FFFFFF;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 15px 16px;
  min-height: 116px;
}
.ac-capability .cap-label {
  color: var(--muted);
  font-size: .74rem;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.ac-capability .cap-title {
  color: var(--ink);
  font-size: 1.02rem;
  font-weight: 800;
  margin-top: 6px;
}
.ac-capability .cap-state {
  font-size: .84rem;
  line-height: 1.45;
  margin-top: 7px;
  color: var(--muted);
}
.ac-capability.available { border-top: 4px solid var(--g-green); }
.ac-capability.extension { border-top: 4px solid var(--g-yellow); }
.ac-capability.evidence { border-top: 4px solid var(--g-blue); }

/* Pipeline */
.ac-pipeline {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
  margin: 18px 0 9px 0;
  padding: 10px;
  background: #E7EEF8;
  border: 1px solid #D3DEEC;
  border-radius: 17px;
}
.ac-stage {
  position: relative;
  min-height: 102px;
  padding: 16px 14px 14px 15px;
  border: 1px solid #DDE6F1;
  border-radius: 11px;
  background: #FFFFFF;
}
.ac-stage .num {
  font-size: .68rem;
  font-weight: 700;
  color: #94A3B8;
  letter-spacing: .09em;
}
.ac-stage .name {
  font-size: .88rem;
  font-weight: 800;
  margin-top: 7px;
  color: var(--ink);
}
.ac-stage .state {
  font-size: .78rem;
  color: var(--muted);
  margin-top: 7px;
}
.ac-stage.done {
  background: var(--g-green-50);
  border-color: #B7DEC2;
}
.ac-stage.active {
  background: var(--g-blue-50);
  border-color: #A8C7FA;
}
.ac-stage.done:before,
.ac-stage.active:before {
  content: "";
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: 8px;
  height: 3px;
  border-radius: 999px;
}
.ac-stage.done:before { background: var(--g-green); }
.ac-stage.active:before { background: var(--g-blue); }

/* Callouts */
.ac-callout {
  background: #FFFFFF;
  border: 1px solid var(--line);
  border-left: 5px solid var(--g-blue);
  border-radius: 13px;
  padding: 15px 17px;
  color: var(--muted);
  font-size: .91rem;
  line-height: 1.55;
}
.ac-callout strong { color: var(--ink); }

[data-testid="stCode"] {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: #F8FAFD;
}
code, pre, [data-testid="stCode"] * {
  font-family: "Roboto Mono", "SFMono-Regular", Consolas, monospace !important;
  font-size: .85rem !important;
}
hr { border-color: var(--line) !important; }
[data-testid="stCaptionContainer"] { color: var(--muted); font-size: .84rem; }
[data-testid="stExpander"] {
  border: 1px solid var(--line) !important;
  border-radius: 13px !important;
  background: #FFFFFF;
}

/* Fine tuning for common Streamlit body text */
.stMarkdown p, .stMarkdown li {
  font-size: .95rem;
  line-height: 1.58;
}
.stAlert p { font-size: .92rem !important; }

@media (max-width: 1080px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; }
  .ac-brandrow { align-items: flex-start; flex-direction: column; }
  .ac-statusrow { justify-content: flex-start; }
  .ac-hero { grid-template-columns: 1fr; padding: 27px 24px; }
  .ac-hero-panel { min-height: auto; }
  .ac-pipeline { grid-template-columns: repeat(2, 1fr); }
}
</style>
""",
    unsafe_allow_html=True,
)


def backend_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("ACCELCLOSURE_ROOT", str(ROOT))
    env.setdefault("GOOGLE_CLOUD_PROJECT", "continual-rhino-507506-f6")
    env.setdefault("GOOGLE_CLOUD_LOCATION", "global")
    env.setdefault("RAY_ADDRESS", "172.17.28.2:6379")
    return env


def run_cli(args: list[str], timeout: int = 90) -> tuple[int, str]:
    cmd = [str(CHIA_PYTHON), str(CLI), *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=backend_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode(errors="replace")
        return 124, partial + "\nCommand timed out."


def start_autonomous_run(request: str, open_layout: bool) -> tuple[int, Path]:
    GUI_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = GUI_LOG_DIR / f"run_{stamp}.log"
    cmd = [str(CHIA_PYTHON), str(CLI), "run", request]
    if open_layout:
        cmd.append("--open")
    log_handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=backend_env(),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
    log_handle.close()
    return proc.pid, log_path


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    stat_path = Path(f"/proc/{pid}/stat")
    if not stat_path.exists():
        return False
    try:
        fields = stat_path.read_text(encoding="utf-8").split()
        return len(fields) > 2 and fields[2] != "Z"
    except OSError:
        return False


def read_log(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def tail(path: Path, lines: int = 48) -> str:
    data = read_log(path).splitlines()
    if not data:
        return "Waiting for run output..."
    return "\n".join(data[-lines:])


def latest_product_result() -> Path | None:
    if not RUNS_DIR.exists():
        return None
    matches = list(RUNS_DIR.glob("*/artifacts/product_result.json"))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def scalar_search(obj: Any, names: set[str]) -> Any:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() in names and not isinstance(value, (dict, list)):
                return value
        for value in obj.values():
            found = scalar_search(value, names)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = scalar_search(value, names)
            if found is not None:
                return found
    return None


def fmt(value: Any, suffix: str = "", digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


def load_result(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def open_klayout(product_result: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [str(CHIA_PYTHON), str(LAYOUT_VIEWER), "--product-result", str(product_result)],
        cwd=ROOT,
        env=backend_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    return proc.returncode == 0, proc.stdout


def docker_workers() -> list[str]:
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"],
            text=True,
            timeout=10,
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def status_chip(label: str, online: bool) -> str:
    dot = "on" if online else "off"
    state = "online" if online else "offline"
    return f'<span class="ac-status"><span class="ac-dot {dot}"></span>{label} · {state}</span>'


def pipeline_html(log_text: str, active: bool) -> str:
    stages = [
        ("01", "Intent", ["run_id", "request"]),
        ("02", "Contract", ["contract"]),
        ("03", "RTL", ["rtl"]),
        ("04", "Verify", ["verification"]),
        ("05", "Synthesis / STA", ["post_synth", "timing_closed"]),
        ("06", "Physical", ["physical", "post_route"]),
        ("07", "Evidence", ["evidence_complete"]),
    ]
    low = log_text.lower()
    completed = []
    for _, _, markers in stages:
        completed.append(any(marker in low for marker in markers))
    if "evidence_complete" in low:
        completed = [True] * len(stages)

    current = -1
    for i, done in enumerate(completed):
        if done:
            current = i
    if active and current < len(stages) - 1:
        active_idx = current + 1
    else:
        active_idx = -1

    cells = []
    for i, (num, name, _) in enumerate(stages):
        if completed[i]:
            cls = "done"
            state = "Complete"
        elif i == active_idx:
            cls = "active"
            state = "Running"
        else:
            cls = ""
            state = "Pending"
        cells.append(
            f'<div class="ac-stage {cls}"><div class="num">{num}</div>'
            f'<div class="name">{name}</div><div class="state">{state}</div></div>'
        )
    return '<div class="ac-pipeline">' + "".join(cells) + "</div>"


workers = docker_workers()
worker_checks = {
    "CHIA": CHIA_PYTHON.exists(),
    "Verilator": "chia-verilator-talha-0" in workers,
    "Yosys": "chia-yosys-talha-0" in workers,
    "Gemini": "chia-accelclosure-opencode-talha-0" in workers,
}
status_html = "".join(status_chip(k, v) for k, v in worker_checks.items())

st.markdown(
    f"""
<div class="ac-topbar">
  <div class="ac-brandrow">
    <div class="ac-brandleft">
      <div class="ac-chipmark" aria-hidden="true">
        <div class="ac-arraygrid">
          <span></span><span></span><span></span>
          <span></span><span></span><span></span>
          <span></span><span></span><span></span>
        </div>
      </div>
      <div>
        <div class="ac-brandname">AccelClosure</div>
        <div class="ac-brandtag">Agentic prompt-to-silicon design closure</div>
      </div>
    </div>
    <div class="ac-statusrow">{status_html}</div>
  </div>
</div>

<div class="ac-hero">
  <div class="ac-hero-left">
    <div class="ac-eyebrow">Agentic hardware co-design</div>
    <div class="ac-herotitle">Design hardware. Measure reality. Close the loop.</div>
    <div class="ac-herosub">
      Translate accelerator intent into verified RTL and implementation evidence. AccelClosure uses CHIA + Gemini
      for grounded design reasoning, then Verilator, Yosys and OpenROAD as the implementation source of truth.
    </div>
    <div class="ac-colorbar"><span></span><span></span><span></span><span></span></div>
  </div>
  <div class="ac-hero-panel">
    <div class="ac-panel-kicker">Current implementation path</div>
    <div class="ac-panel-row">
      <span class="ac-panel-icon blue"></span>
      <div><div class="ac-panel-label">Autonomous backend</div><div class="ac-panel-value">Square WS INT8 systolic arrays</div></div>
    </div>
    <div class="ac-panel-row">
      <span class="ac-panel-icon yellow"></span>
      <div><div class="ac-panel-label">Physical target</div><div class="ac-panel-value">Sky130HD · requested clock preserved</div></div>
    </div>
    <div class="ac-panel-row">
      <span class="ac-panel-icon green"></span>
      <div><div class="ac-panel-label">Evidence discipline</div><div class="ac-panel-value">Fresh verification + fresh EDA per configuration</div></div>
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)


tab_design, tab_results, tab_advisor, tab_evidence = st.tabs(
    ["Design", "Implementation", "Workload Advisor", "Evidence"]
)

with tab_design:
    st.markdown('<div class="ac-section-title">Design workspace</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ac-section-sub">Define the hardware intent, review the active implementation policy, and launch the autonomous closure flow.</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([2.25, 1], gap="large")
    with left:
        c1, c2, c3, c4 = st.columns([.9, 1.05, 1.0, 1.05])
        with c1:
            n = st.selectbox("Array geometry", [4, 8, 16, 32], index=1, format_func=lambda x: f"{x} × {x}")
        with c2:
            dataflow = st.selectbox(
                "Dataflow",
                ["ws", "os", "is"],
                index=0,
                format_func=lambda x: {"ws": "Weight-stationary", "os": "Output-stationary", "is": "Input-stationary"}[x],
            )
        with c3:
            frequency = st.number_input("Target frequency (MHz)", 50, 300, 180, 10)
        with c4:
            objective = st.selectbox("Optimization objective", ["latency", "area", "energy", "balanced"], index=0)

        dataflow_words = {
            "ws": "weight-stationary",
            "os": "output-stationary",
            "is": "input-stationary",
        }
        closure_supported = dataflow == "ws"
        backend_state = "IMPLEMENTED" if closure_supported else "PLUGIN EXTENSION"
        backend_note = (
            "Executable autonomous backend"
            if closure_supported
            else "Explorable design-space point; RTL/verification/EDA backend not yet implemented"
        )

        composed = (
            f"Design an {n}x{n} INT8 {dataflow_words[dataflow]} systolic array "
            f"targeting Sky130 at {frequency} MHz with a {objective} objective"
        )
        if "design_request" not in st.session_state:
            st.session_state.design_request = composed

        r1, r2, r3 = st.columns([1.0, 1.15, 2.0])
        with r1:
            if st.button("Build request", use_container_width=True):
                st.session_state.design_request = composed
        with r2:
            explore = st.button("Explore design space", use_container_width=True)

        request = st.text_area(
            "Hardware request",
            key="design_request",
            height=125,
            help="WS INT8 is the implemented autonomous backend. OS and IS are visible design-space extensions and are not presented as physically implemented paths.",
        )

        if explore:
            rc, out = run_cli([
                "plan",
                "--rows", str(n),
                "--columns", str(n),
                "--dataflow", dataflow,
                "--arithmetic", "int8",
                "--frequency", str(frequency),
                "--objective", objective,
            ])
            st.session_state.plan_output = out
            st.session_state.plan_rc = rc

        if closure_supported:
            st.markdown(
                '<div class="ac-callout"><strong>Executable backend.</strong> Weight-stationary INT8 can enter the autonomous verification and physical-closure flow. Fresh evidence is generated for the requested configuration.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="ac-callout" style="border-left-color:var(--g-yellow)"><strong>{dataflow_words[dataflow].title()} is a plugin extension.</strong> AccelClosure can classify and plan this design-space request, but Run autonomous closure is disabled until that architecture backend is independently implemented and verified.</div>',
                unsafe_allow_html=True,
            )

        open_after = st.checkbox(
            "Open validated final GDSII in KLayout after closure",
            value=False,
            disabled=not closure_supported,
        )

        a, b, c = st.columns([1.35, 1.0, 1.9])
        with a:
            start = st.button(
                "Run autonomous closure",
                type="primary",
                use_container_width=True,
                disabled=not closure_supported,
            )
        with b:
            status_btn = st.button("System status", use_container_width=True)

        if status_btn:
            rc, out = run_cli(["status"])
            st.session_state.status_output = out
            st.session_state.status_rc = rc

        if "plan_output" in st.session_state:
            with st.expander("Design-space assessment", expanded=not closure_supported):
                st.code(st.session_state.plan_output, language="text")

    with right:
        dataflow_label = {"ws": "Weight-stationary", "os": "Output-stationary", "is": "Input-stationary"}[dataflow]
        badge_class = "green" if closure_supported else "yellow"
        st.markdown(
            f"""
<div class="ac-card">
  <div class="ac-card-title">Selected backend status</div>
  <div class="ac-small">The interface separates design-space exploration from executable, evidence-backed implementation.</div>
  <div class="ac-kv"><span class="k">Architecture</span><span class="v">Square systolic</span></div>
  <div class="ac-kv"><span class="k">Dataflow</span><span class="v">{dataflow_label}</span></div>
  <div class="ac-kv"><span class="k">Arithmetic</span><span class="v">INT8 → INT32</span></div>
  <div class="ac-kv"><span class="k">Technology</span><span class="v">Sky130HD</span></div>
  <div class="ac-kv"><span class="k">Backend state</span><span class="v">{backend_state}</span></div>
  <div style="margin-top:10px">
    <span class="ac-badge {badge_class}">{backend_note}</span>
  </div>
</div>
<div style="height:12px"></div>
<div class="ac-card">
  <div class="ac-card-title">Dataflow maturity</div>
  <div class="ac-kv"><span class="k">Weight-stationary</span><span class="v" style="color:#137333">IMPLEMENTED</span></div>
  <div class="ac-kv"><span class="k">Output-stationary</span><span class="v" style="color:#8A5A00">PLUGIN EXTENSION</span></div>
  <div class="ac-kv"><span class="k">Input-stationary</span><span class="v" style="color:#8A5A00">PLUGIN EXTENSION</span></div>
  <div style="margin-top:10px">
    <span class="ac-badge blue">Fresh verification</span>
    <span class="ac-badge green">Fresh EDA</span>
    <span class="ac-badge red">No PPA reuse</span>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

    if start:
        if not closure_supported:
            st.error("This dataflow is a design-space plugin extension and cannot enter autonomous physical closure yet.")
        elif not request.strip():
            st.error("Enter a hardware request first.")
        elif st.session_state.get("run_pid") and pid_alive(st.session_state.run_pid):
            st.warning("An AccelClosure run is already active.")
        else:
            pid, log_path = start_autonomous_run(request.strip(), open_after)
            st.session_state.run_pid = pid
            st.session_state.run_log = str(log_path)
            st.session_state.run_started = time.time()
            st.success(f"Autonomous run started · PID {pid}")

    if "status_output" in st.session_state:
        with st.expander("Product capability status", expanded=False):
            st.code(st.session_state.status_output, language="text")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="ac-section-title">Autonomous closure pipeline</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ac-section-sub">Every stage is evidence-gated. Physical implementation begins only after correctness and timing requirements are satisfied.</div>',
        unsafe_allow_html=True,
    )

    @st.fragment(run_every="2s")
    def live_run_monitor() -> None:
        pid = st.session_state.get("run_pid")
        log_value = st.session_state.get("run_log")
        if not pid or not log_value:
            st.markdown(pipeline_html("", False), unsafe_allow_html=True)
            st.markdown(
                '<div class="ac-callout"><strong>Ready.</strong> Configure a request above. No autonomous EDA run starts until you explicitly launch it.</div>',
                unsafe_allow_html=True,
            )
            return

        log_path = Path(log_value)
        active = pid_alive(pid)
        elapsed = time.time() - st.session_state.get("run_started", time.time())
        whole_log = read_log(log_path)
        st.markdown(pipeline_html(whole_log, active), unsafe_allow_html=True)

        state_label = "RUNNING" if active else "FINISHED"
        state_color = "blue" if active else "green"
        st.markdown(
            f'<span class="ac-badge {state_color}">{state_label}</span>'
            f'<span class="ac-small">Elapsed · {elapsed / 60:.1f} min &nbsp;&nbsp; Log · {log_path.name}</span>',
            unsafe_allow_html=True,
        )
        with st.expander("Live execution log", expanded=active):
            st.code(tail(log_path), language="text")

    live_run_monitor()

with tab_results:
    st.markdown('<div class="ac-section-title">Latest implementation result</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ac-section-sub">Metrics are read from the newest retained <code>product_result.json</code>; they are not manually entered into the dashboard.</div>',
        unsafe_allow_html=True,
    )

    result_path = latest_product_result()
    result = load_result(result_path)
    if result is None:
        st.info("No local product_result.json was found.")
    else:
        status = scalar_search(result, {"status", "post_route_status"})
        fmax = scalar_search(result, {"fmax_mhz", "fmax_estimate_mhz", "estimated_fmax_mhz"})
        area = scalar_search(result, {"routed_area_mm2", "area_mm2", "core_area_mm2"})
        power = scalar_search(result, {"vectorless_power_w", "power_w", "total_power_w"})
        slack = scalar_search(result, {"worst_setup_slack_ns", "setup_slack_ns", "worst_slack_ns"})
        setup_v = scalar_search(result, {"setup_violations", "setup_violation_count"})
        hold_v = scalar_search(result, {"hold_violations", "hold_violation_count"})
        gds_sha = scalar_search(result, {"gds_sha256", "sha256"})

        st.markdown(
            f'<div class="ac-callout"><strong>Evidence source</strong><br>{result_path.relative_to(ROOT)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown("<br>", unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Closure status", fmt(status))
        m2.metric("Fmax estimate", fmt(fmax, " MHz", 2))
        m3.metric("Routed area", fmt(area, " mm²", 6))
        m4.metric("Vectorless power", fmt(power, " W", 4))

        n1, n2, n3 = st.columns(3)
        n1.metric("Worst setup slack", fmt(slack, " ns", 2))
        n2.metric("Setup violations", fmt(setup_v, "", 0))
        n3.metric("Hold violations", fmt(hold_v, "", 0))

        st.markdown("<br>", unsafe_allow_html=True)
        if gds_sha is not None:
            st.markdown('<div class="ac-card-title">Final GDSII integrity</div>', unsafe_allow_html=True)
            st.code(str(gds_sha), language=None)

        x1, x2, x3 = st.columns([1, 1, 3])
        with x1:
            if st.button("Open in KLayout", type="primary", use_container_width=True):
                try:
                    ok, out = open_klayout(result_path)
                    if ok:
                        st.success("Validated GDSII launched in KLayout.")
                    else:
                        st.error(out)
                except Exception as exc:
                    st.error(f"KLayout launch failed: {exc}")
        with x2:
            if st.button("Refresh result", use_container_width=True):
                st.rerun()

        with st.expander("Raw evidence record", expanded=False):
            st.json(result)

with tab_advisor:
    st.markdown('<div class="ac-section-title">Workload-aware hardware advisor</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ac-section-sub">Select a retained model scenario and compare it against the physically validated accelerator candidates.</div>',
        unsafe_allow_html=True,
    )

    a1, a2, a3 = st.columns(3)
    with a1:
        model = st.selectbox("Model", ["tinybert", "tinyllama", "qwen2.5-1.5b"], index=1)
    with a2:
        scenario = st.selectbox("Scenario", ["encoder", "prefill", "decode"], index=2)
    with a3:
        adv_objective = st.selectbox("Decision objective", ["latency", "area", "energy", "balanced"], index=1)

    c1, c2, c3 = st.columns([1, 1, 2.4])
    with c1:
        recommend = st.button("Recommend hardware", type="primary", use_container_width=True)
    with c2:
        explain = st.button("Explain decision", use_container_width=True)

    if recommend:
        rc, out = run_cli(["advise", "--model", model, "--scenario", scenario, "--objective", adv_objective])
        st.session_state.advisor_output = out
        st.session_state.advisor_rc = rc
    if explain:
        rc, out = run_cli(["explain", "--model", model, "--scenario", scenario, "--objective", adv_objective])
        st.session_state.explain_output = out
        st.session_state.explain_rc = rc

    if "advisor_output" in st.session_state:
        st.markdown("#### Recommendation")
        st.code(st.session_state.advisor_output, language="text")
    if "explain_output" in st.session_state:
        st.markdown("#### Evidence-backed explanation")
        st.code(st.session_state.explain_output, language="text")

with tab_evidence:
    st.markdown('<div class="ac-section-title">Evidence & provenance</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ac-section-sub">A compact view of the experimentally retained evidence behind AccelClosure.</div>',
        unsafe_allow_html=True,
    )

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Closed references", "3", "4×4 · 8×8 · 16×16")
    e2.metric("Scalability point", "32×32", "pre-layout STA")
    e3.metric("Real models", "3", "validated tensors")
    e4.metric("Evidence policy", "Fresh", "per configuration")

    st.markdown("<br>", unsafe_allow_html=True)
    image_paths = [
        ROOT / "evidence/figures/fig01_postroute_frequency.png",
        ROOT / "evidence/figures/fig02_routed_area.png",
        ROOT / "evidence/figures/fig03_vectorless_power.png",
    ]
    cols = st.columns(3)
    for col, path in zip(cols, image_paths):
        if path.exists():
            col.image(str(path), use_container_width=True)

    architecture = ROOT / "docs/images/fig01_accelclosure_system_architecture.png"
    if architecture.exists():
        st.markdown("#### System architecture")
        st.image(str(architecture), use_container_width=True)

    evidence_readme = ROOT / "evidence/README.md"
    if evidence_readme.exists():
        with st.expander("Read experimental evidence summary", expanded=False):
            st.markdown(evidence_readme.read_text(encoding="utf-8"))

st.markdown("<br>", unsafe_allow_html=True)
st.markdown(
    """
<div class="ac-callout">
  <strong>Evidence discipline.</strong>
  EDA results are authoritative. New configurations require fresh verification and implementation evidence.
  Vectorless power is not presented as workload-measured power, and generated GDSII is not presented as foundry signoff.
</div>
""",
    unsafe_allow_html=True,
)
