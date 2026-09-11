#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from chia.base.ChiaFunction import ChiaFunction, get


@ChiaFunction(
    resources={"verilator_run": 1}
)
def verilator_lint(
    pe_rtl: str,
    array_rtl: str,
    n: int,
    data_w: int,
    acc_w: int,
) -> dict:

    verilator = shutil.which("verilator")

    if verilator is None:
        return {
            "status": "TOOL_NOT_FOUND",
            "returncode": -1,
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
            f"-GN={n}",
            f"-GDATA_W={data_w}",
            f"-GACC_W={acc_w}",
            str(pe),
            str(array),
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        combined = (
            result.stdout
            + "\n"
            + result.stderr
        )

        warning_lines = [
            line
            for line in combined.splitlines()
            if "%Warning-" in line
        ]

        error_lines = [
            line
            for line in combined.splitlines()
            if "%Error" in line
        ]

        if result.returncode != 0 or error_lines:
            status = "FAIL"

        elif warning_lines:
            status = "WARN"

        else:
            status = "PASS"

        return {
            "status": status,
            "returncode": result.returncode,
            "N": n,
            "DATA_W": data_w,
            "ACC_W": acc_w,
            "verilator_path": verilator,
            "command": cmd,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "warnings": warning_lines,
            "errors": error_lines,
            "warning_count": len(warning_lines),
            "error_count": len(error_lines),
        }


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--n",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--data-w",
        type=int,
        default=8,
    )

    parser.add_argument(
        "--acc-w",
        type=int,
        default=32,
    )

    parser.add_argument(
        "--pe",
        required=True,
    )

    parser.add_argument(
        "--array",
        required=True,
    )

    parser.add_argument(
        "--report",
        required=True,
    )

    args = parser.parse_args()

    pe_path = Path(args.pe)
    array_path = Path(args.array)
    report_path = Path(args.report)

    if not pe_path.exists():
        raise SystemExit(
            f"PE RTL not found: {pe_path}"
        )

    if not array_path.exists():
        raise SystemExit(
            f"Array RTL not found: {array_path}"
        )

    print(
        f"[AccelClosure] Dispatching N={args.n} "
        "Verilator lint..."
    )

    report = get(
        verilator_lint.chia_remote(
            pe_path.read_text(),
            array_path.read_text(),
            args.n,
            args.data_w,
            args.acc_w,
        )
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
        )
        + "\n"
    )

    print(
        "[AccelClosure] PARAMETRIC_LINT_STATUS:",
        report["status"],
    )

    print(
        "[AccelClosure] WARNING_COUNT:",
        report.get(
            "warning_count",
            0,
        ),
    )

    print(
        "[AccelClosure] ERROR_COUNT:",
        report.get(
            "error_count",
            0,
        ),
    )

    if report.get("stderr"):
        print()
        print("========== LINT STDERR ==========")
        print(report["stderr"])

    print()
    print(
        "[AccelClosure] Report:",
        report_path.resolve(),
    )

    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
