#!/usr/bin/env python3

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads(
        path.read_text()
    )


def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def resolve_context(path_text):
    path = Path(path_text)

    if not path.is_absolute():
        path = ROOT / path

    path = path.resolve()

    if not path.exists():
        raise FileNotFoundError(
            f"Run context not found: {path}"
        )

    return path


def container_path(relative_path):
    return (
        "/workspace/AccelClosure/"
        + str(relative_path).replace("\\", "/")
    )


def generate_sdc(period_ns):
    return f'''current_design accelclosure_ws_array

set clk_name      core_clock
set clk_port_name clk
set clk_period    {period_ns:.6f}
set clk_io_pct    0.20

set clk_port [get_ports $clk_port_name]

create_clock \\
  -name $clk_name \\
  -period $clk_period \\
  $clk_port

set non_clock_inputs \\
  [lsearch -inline -all -not -exact \\
    [all_inputs] $clk_port]

set_input_delay \\
  [expr $clk_period * $clk_io_pct] \\
  -clock $clk_name \\
  $non_clock_inputs

set_output_delay \\
  [expr $clk_period * $clk_io_pct] \\
  -clock $clk_name \\
  [all_outputs]

# Active-low asynchronous reset is not a functional
# data timing path.
set_false_path -from [get_ports rst_n]
'''


def generate_config(
    rtl_dir,
    sdc_path,
):
    pe_path = (
        rtl_dir
        / "accelclosure_ws_pe.sv"
    )

    array_path = (
        rtl_dir
        / "accelclosure_ws_array.sv"
    )

    return f'''export PLATFORM        = sky130hd

export DESIGN_NAME     = accelclosure_ws_array
export DESIGN_NICKNAME = accelclosure_ws_array

export VERILOG_FILES = \\
  {container_path(pe_path)} \\
  {container_path(array_path)}

export SDC_FILE = \\
  {container_path(sdc_path)}

# Generic initial physical-design settings.
# These are implementation knobs, not measured results.
export CORE_UTILIZATION = 35
export PLACE_DENSITY    = 0.55

export TNS_END_PERCENT = 100
'''


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate per-run Sky130/OpenROAD "
            "configuration from an AccelClosure "
            "run context."
        )
    )

    parser.add_argument(
        "--context",
        required=True,
        help="Path to run_context.json",
    )

    args = parser.parse_args()

    context_path = resolve_context(
        args.context
    )

    context = load_json(
        context_path
    )

    if (
        context.get("schema")
        != "accelclosure.run_context.v1"
    ):
        raise RuntimeError(
            "Unsupported run-context schema"
        )

    params = context["parameters"]
    paths = context["paths"]

    technology = params["technology"]

    if technology != "sky130hd":
        raise RuntimeError(
            "Current physical backend supports "
            "sky130hd only"
        )

    n = int(
        params["n"]
    )

    frequency_mhz = float(
        params["target_frequency_mhz"]
    )

    period_ns = float(
        params["target_period_ns"]
    )

    calculated_period = (
        1000.0
        / frequency_mhz
    )

    if (
        abs(
            period_ns
            - calculated_period
        )
        > 0.001
    ):
        raise RuntimeError(
            "Run-context frequency and period "
            "are inconsistent"
        )

    config_dir = (
        ROOT
        / paths["config_dir"]
    )

    rtl_dir = Path(
        paths["rtl_dir"]
    )

    config_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    analysis_dir = (
        config_dir
        / "analysis"
    )

    analysis_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    sdc_path = (
        config_dir
        / "constraint.sdc"
    )

    config_path = (
        config_dir
        / "config.mk"
    )

    manifest_path = (
        config_dir
        / "eda_manifest.json"
    )

    sdc_text = generate_sdc(
        period_ns
    )

    config_text = generate_config(
        rtl_dir,
        sdc_path.relative_to(ROOT),
    )

    sdc_path.write_text(
        sdc_text
    )

    config_path.write_text(
        config_text
    )

    run_id = context["run_id"]

    variant = run_id

    manifest = {
        "schema":
            "accelclosure.eda_config.v1",

        "generated_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "run_id":
            run_id,

        "variant":
            variant,

        "design_name":
            "accelclosure_ws_array",

        "technology":
            technology,

        "architecture": {
            "n":
                n,

            "rows":
                params["rows"],

            "cols":
                params["cols"],

            "dataflow":
                params["dataflow"],

            "activation_width":
                params["activation_width"],

            "weight_width":
                params["weight_width"],

            "accumulator_width":
                params["accumulator_width"],
        },

        "timing": {
            "target_frequency_mhz":
                frequency_mhz,

            "target_period_ns":
                period_ns,

            "io_delay_fraction":
                0.20,

            "clock_name":
                "core_clock",

            "clock_port":
                "clk",
        },

        "physical_defaults": {
            "core_utilization_percent":
                35,

            "place_density":
                0.55,
        },

        "files": {
            "config_mk":
                str(
                    config_path.relative_to(ROOT)
                ),

            "constraint_sdc":
                str(
                    sdc_path.relative_to(ROOT)
                ),

            "rtl_pe":
                str(
                    rtl_dir
                    / "accelclosure_ws_pe.sv"
                ),

            "rtl_array":
                str(
                    rtl_dir
                    / "accelclosure_ws_array.sv"
                ),
        },

        "orfs_output": {
            "platform":
                technology,

            "design":
                "accelclosure_ws_array",

            "variant":
                variant,

            "results_directory":
                (
                    "orfs_runs/results/"
                    f"{technology}/"
                    "accelclosure_ws_array/"
                    f"{variant}"
                ),

            "reports_directory":
                (
                    "orfs_runs/reports/"
                    f"{technology}/"
                    "accelclosure_ws_array/"
                    f"{variant}"
                ),
        },

        "provenance": {
            "run_context":
                str(
                    context_path.relative_to(ROOT)
                ),

            "run_context_sha256":
                sha256(
                    context_path
                ),

            "constraint_sdc_sha256":
                sha256(
                    sdc_path
                ),

            "config_mk_sha256":
                sha256(
                    config_path
                ),
        },

        "measurement_status": {
            "synthesis_run":
                False,

            "sta_run":
                False,

            "physical_design_run":
                False,

            "timing_closed":
                False,

            "gds_generated":
                False,
        },
    }

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
        )
        + "\n"
    )

    # Update execution state.
    context["stages"][
        "eda_config_generated"
    ] = True

    context_path.write_text(
        json.dumps(
            context,
            indent=2,
        )
        + "\n"
    )

    print(
        "ACCELCLOSURE_EDA_CONFIG_GENERATED"
    )

    print(
        f"run_id={run_id}"
    )

    print(
        f"N={n}"
    )

    print(
        f"target_frequency_mhz="
        f"{frequency_mhz}"
    )

    print(
        f"target_period_ns="
        f"{period_ns}"
    )

    print(
        f"variant={variant}"
    )

    print(
        f"sdc={sdc_path}"
    )

    print(
        f"config={config_path}"
    )

    print(
        f"manifest={manifest_path}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
