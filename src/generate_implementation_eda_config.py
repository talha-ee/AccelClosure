#!/usr/bin/env python3

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads(path.read_text())


def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b""
        ):
            h.update(block)

    return h.hexdigest()


def resolve(text):
    p = Path(text)

    if not p.is_absolute():
        p = ROOT / p

    return p.resolve()


def container_path(path):
    rel = path.resolve().relative_to(ROOT)

    return (
        "/workspace/AccelClosure/"
        + str(rel)
    )


def require(condition, message):
    if not condition:
        raise SystemExit(
            "IMPLEMENTATION_EDA_CONFIG_ERROR: "
            + message
        )


def generate_sdc(period_ns):

    return f'''current_design accelclosure_ws_array

set clk_name core_clock
set clk_port_name clk
set clk_period {period_ns:.6f}
set clk_io_pct 0.20

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

set_false_path -from [get_ports rst_n]
'''


def generate_config(pe, array, sdc):

    return f'''export PLATFORM = sky130hd

export DESIGN_NAME = accelclosure_ws_array
export DESIGN_NICKNAME = accelclosure_ws_array

export VERILOG_FILES = \\
  {container_path(pe)} \\
  {container_path(array)}

export SDC_FILE = \\
  {container_path(sdc)}

export CORE_UTILIZATION = 35
export PLACE_DENSITY = 0.55
export TNS_END_PERCENT = 100
'''


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--implementation-context",
        required=True
    )

    parser.add_argument(
        "--validate-only",
        action="store_true"
    )

    args = parser.parse_args()

    impl_path = resolve(
        args.implementation_context
    )

    require(
        impl_path.exists(),
        f"context missing: {impl_path}"
    )

    impl = load_json(
        impl_path
    )

    require(
        impl.get("schema")
        == "accelclosure.implementation_context.v1",
        "unsupported implementation-context schema"
    )

    req = impl["request"]
    eda = impl["eda"]
    rtl = impl["implementation"]["rtl"]

    require(
        req["technology"] == "sky130hd",
        "current backend supports sky130hd only"
    )

    frequency = float(
        req["target_frequency_mhz"]
    )

    period = float(
        req["target_period_ns"]
    )

    require(
        abs(
            period - 1000.0 / frequency
        ) <= 0.001,
        "frequency/period mismatch"
    )

    pe = resolve(
        rtl["pe"]["path"]
    )

    array = resolve(
        rtl["array"]["path"]
    )

    require(
        pe.exists(),
        "PE RTL missing"
    )

    require(
        array.exists(),
        "array RTL missing"
    )

    require(
        sha256(pe)
        == rtl["pe"]["sha256"],
        "PE RTL hash gate failed"
    )

    require(
        sha256(array)
        == rtl["array"]["sha256"],
        "array RTL hash gate failed"
    )

    config_dir = resolve(
        eda["config_dir"]
    )

    sdc = (
        config_dir
        / "constraint.sdc"
    )

    config = (
        config_dir
        / "config.mk"
    )

    manifest = (
        config_dir
        / "implementation_eda_manifest.json"
    )

    print(
        "IMPLEMENTATION_EDA_PREFLIGHT=PASS"
    )

    print(
        "RUN_ID="
        + impl["run_id"]
    )

    print(
        "IMPLEMENTATION_ID="
        + impl["implementation_id"]
    )

    print(
        "VARIANT="
        + eda["variant"]
    )

    print(
        "TARGET_FREQUENCY_MHZ="
        + str(frequency)
    )

    print(
        "TARGET_PERIOD_NS="
        + str(period)
    )

    print(
        "VERIFIED_RTL_HASH_GATE=PASS"
    )

    if args.validate_only:

        print(
            "MODE=VALIDATE_ONLY"
        )

        print(
            "CONFIG_DIR="
            + str(
                config_dir.relative_to(ROOT)
            )
        )

        return

    config_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    sdc_text = generate_sdc(
        period
    )

    # Build SDC path before generating config.
    if sdc.exists():

        if sdc.read_text() != sdc_text:
            raise SystemExit(
                "IMPLEMENTATION_EDA_CONFIG_ERROR: "
                "existing SDC differs; overwrite forbidden"
            )

    else:
        sdc.write_text(
            sdc_text
        )

    config_text = generate_config(
        pe,
        array,
        sdc
    )

    if config.exists():

        if config.read_text() != config_text:
            raise SystemExit(
                "IMPLEMENTATION_EDA_CONFIG_ERROR: "
                "existing config differs; overwrite forbidden"
            )

    else:
        config.write_text(
            config_text
        )

    record = {
        "schema":
            "accelclosure.implementation_eda_config.v1",

        "run_id":
            impl["run_id"],

        "implementation_id":
            impl["implementation_id"],

        "variant":
            eda["variant"],

        "technology":
            req["technology"],

        "target": {
            "frequency_mhz":
                frequency,

            "period_ns":
                period
        },

        "rtl": {
            "pe": {
                "path":
                    rtl["pe"]["path"],

                "sha256":
                    rtl["pe"]["sha256"]
            },

            "array": {
                "path":
                    rtl["array"]["path"],

                "sha256":
                    rtl["array"]["sha256"]
            }
        },

        "files": {
            "config_mk":
                str(
                    config.relative_to(ROOT)
                ),

            "constraint_sdc":
                str(
                    sdc.relative_to(ROOT)
                )
        },

        "hashes": {
            "implementation_context_sha256":
                sha256(impl_path),

            "config_mk_sha256":
                sha256(config),

            "constraint_sdc_sha256":
                sha256(sdc)
        },

        "orfs": {
            "results_dir":
                eda["results_dir"],

            "reports_dir":
                eda["reports_dir"]
        },

        "measurement_status": {
            "synthesis":
                False,

            "prelayout_sta":
                False,

            "physical_design":
                False,

            "post_route_sta":
                False,

            "power":
                False,

            "gds":
                False
        }
    }

    text = (
        json.dumps(
            record,
            indent=2
        )
        + "\n"
    )

    if manifest.exists():

        existing = load_json(
            manifest
        )

        # Ignore no fields: manifest must be identical.
        require(
            existing == record,
            (
                "existing implementation EDA "
                "manifest differs; overwrite forbidden"
            )
        )

    else:
        manifest.write_text(
            text
        )

    print(
        "IMPLEMENTATION_EDA_CONFIG_READY"
    )

    print(
        "CONFIG="
        + str(
            config.relative_to(ROOT)
        )
    )

    print(
        "SDC="
        + str(
            sdc.relative_to(ROOT)
        )
    )

    print(
        "MANIFEST="
        + str(
            manifest.relative_to(ROOT)
        )
    )


if __name__ == "__main__":
    main()
