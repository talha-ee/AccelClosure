import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from chia.base.ChiaFunction import ChiaFunction, get


PROJECT_ROOT = Path(
    os.environ.get(
        "ACCELCLOSURE_ROOT",
        Path(__file__).resolve().parents[1],
    )
).expanduser().resolve()

RTL_DIR = PROJECT_ROOT / "rtl"
RESULTS_DIR = PROJECT_ROOT / "results"


@ChiaFunction(resources={"yosys_run": 1})
def yosys_generic_synth(
    pe_rtl: str,
    array_rtl: str,
) -> dict:

    yosys = shutil.which("yosys")

    if yosys is None:
        return {
            "status": "TOOL_NOT_FOUND",
            "returncode": -1,
            "stderr": "yosys not found on yosys_run worker",
        }

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)

        pe_path = work / "accelclosure_ws_pe.sv"
        array_path = work / "accelclosure_ws_array.sv"
        script_path = work / "synth.ys"
        netlist_path = work / "synthesized_16x16.v"

        pe_path.write_text(pe_rtl)
        array_path.write_text(array_rtl)

        synth_script = r'''
read_verilog -sv accelclosure_ws_pe.sv accelclosure_ws_array.sv

chparam -set N 16 accelclosure_ws_array
chparam -set DATA_W 8 accelclosure_ws_array
chparam -set ACC_W 32 accelclosure_ws_array

hierarchy -check -top accelclosure_ws_array

synth -top accelclosure_ws_array

check
stat

write_verilog -noattr synthesized_16x16.v
'''

        script_path.write_text(synth_script)

        proc = subprocess.run(
            [
                yosys,
                "-s",
                str(script_path),
            ],
            cwd=work,
            capture_output=True,
            text=True,
        )

        full_log = proc.stdout + "\n" + proc.stderr

        cell_matches = re.findall(
            r"Number of cells:\s+(\d+)",
            full_log,
        )

        wire_matches = re.findall(
            r"Number of wires:\s+(\d+)",
            full_log,
        )

        wire_bit_matches = re.findall(
            r"Number of wire bits:\s+(\d+)",
            full_log,
        )

        netlist_exists = netlist_path.exists()

        netlist_bytes = (
            netlist_path.stat().st_size
            if netlist_exists
            else 0
        )

        netlist_sha256 = None

        if netlist_exists:
            netlist_sha256 = hashlib.sha256(
                netlist_path.read_bytes()
            ).hexdigest()

        return {
            "status": (
                "PASS"
                if proc.returncode == 0
                else "FAIL"
            ),
            "returncode": proc.returncode,
            "yosys_path": yosys,
            "yosys_script": synth_script,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "generic_statistics": {
                "number_of_cells": (
                    int(cell_matches[-1])
                    if cell_matches
                    else None
                ),
                "number_of_wires": (
                    int(wire_matches[-1])
                    if wire_matches
                    else None
                ),
                "number_of_wire_bits": (
                    int(wire_bit_matches[-1])
                    if wire_bit_matches
                    else None
                ),
            },
            "configuration": {
                "N": 16,
                "PE_count_structural": 256,
                "DATA_W": 8,
                "ACC_W": 32,
                "dataflow": "weight-stationary",
            },
            "netlist_generated": netlist_exists,
            "netlist_bytes": netlist_bytes,
            "netlist_sha256": netlist_sha256,
            "measurement_status": {
                "generic_synthesis_completed":
                    proc.returncode == 0,
                "sky130_mapped": False,
                "timing_measured": False,
                "area_measured": False,
                "power_measured": False,
                "physical_design_completed": False,
            },
        }


def main():

    pe_path = (
        RTL_DIR
        / "accelclosure_ws_pe.sv"
    )

    array_path = (
        RTL_DIR
        / "accelclosure_ws_array.sv"
    )

    if not pe_path.exists():
        raise FileNotFoundError(pe_path)

    if not array_path.exists():
        raise FileNotFoundError(array_path)

    print(
        "[AccelClosure] Dispatching 16x16 "
        "generic synthesis to yosys_run worker..."
    )

    report = get(
        yosys_generic_synth.chia_remote(
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
        / "yosys_generic_16x16_report.json"
    )

    log_path = (
        RESULTS_DIR
        / "yosys_generic_16x16.log"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
        )
    )

    log_path.write_text(
        report.get("stdout", "")
        + "\n"
        + report.get("stderr", "")
    )

    print(
        "[AccelClosure] YOSYS_STATUS:",
        report["status"],
    )

    print(
        "[AccelClosure] RETURN_CODE:",
        report["returncode"],
    )

    print(
        "[AccelClosure] YOSYS_PATH:",
        report.get("yosys_path"),
    )

    print(
        "[AccelClosure] GENERIC_STATS:",
        json.dumps(
            report.get(
                "generic_statistics", {}
            ),
            indent=2,
        ),
    )

    print(
        "[AccelClosure] NETLIST_GENERATED:",
        report.get("netlist_generated"),
    )

    print(
        "[AccelClosure] NETLIST_BYTES:",
        report.get("netlist_bytes"),
    )

    if report["status"] != "PASS":
        print(
            "\n========== YOSYS STDERR =========="
        )
        print(
            report.get("stderr", "")
        )

        print(
            "\n========== LAST LOG LINES =========="
        )

        lines = report.get(
            "stdout", ""
        ).splitlines()

        print(
            "\n".join(lines[-100:])
        )

    print(
        "[AccelClosure] REPORT:",
        report_path,
    )

    print(
        "[AccelClosure] LOG:",
        log_path,
    )

    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
