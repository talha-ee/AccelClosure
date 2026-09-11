import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from chia.base.ChiaFunction import ChiaFunction, get


PROJECT_ROOT = Path(
    os.environ.get(
        "ACCELCLOSURE_ROOT",
        Path(__file__).resolve().parents[1]
    )
).expanduser().resolve()

RTL_DIR = PROJECT_ROOT / "rtl"
RESULTS_DIR = PROJECT_ROOT / "results"


@ChiaFunction(resources={"verilator_run": 1})
def verilator_lint(
    pe_rtl: str,
    array_rtl: str,
) -> dict:

    verilator = shutil.which("verilator")

    if verilator is None:
        return {
            "status": "TOOL_NOT_FOUND",
            "returncode": -1,
            "stdout": "",
            "stderr": "verilator not found on verilator_run worker",
            "verilator_path": None,
        }

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)

        pe = work / "accelclosure_ws_pe.sv"
        array = work / "accelclosure_ws_array.sv"

        pe.write_text(pe_rtl)
        array.write_text(array_rtl)

        cmd = [
            verilator,
            "--lint-only",
            "--sv",
            "-Wall",
            "-Wno-fatal",
            "--top-module",
            "accelclosure_ws_array",
            str(pe),
            str(array),
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        return {
            "status": (
                "PASS"
                if proc.returncode == 0
                else "FAIL"
            ),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "verilator_path": verilator,
            "command": cmd,
        }


def main():

    pe_path = RTL_DIR / "accelclosure_ws_pe.sv"
    array_path = RTL_DIR / "accelclosure_ws_array.sv"

    if not pe_path.exists():
        raise FileNotFoundError(pe_path)

    if not array_path.exists():
        raise FileNotFoundError(array_path)

    print("[AccelClosure] Dispatching RTL lint to verilator_run worker...")

    report = get(
        verilator_lint.chia_remote(
            pe_path.read_text(),
            array_path.read_text(),
        )
    )

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path = (
        RESULTS_DIR
        / "verilator_lint_report.json"
    )

    report_path.write_text(
        json.dumps(report, indent=2)
    )

    print(
        "[AccelClosure] VERILATOR_PATH:",
        report.get("verilator_path"),
    )

    print(
        "[AccelClosure] LINT_STATUS:",
        report["status"],
    )

    print(
        "[AccelClosure] RETURN_CODE:",
        report["returncode"],
    )

    if report["stdout"]:
        print("\n========== STDOUT ==========")
        print(report["stdout"])

    if report["stderr"]:
        print("\n========== STDERR ==========")
        print(report["stderr"])

    print(
        "\n[AccelClosure] REPORT:",
        report_path,
    )

    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
