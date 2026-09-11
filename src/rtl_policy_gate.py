#!/usr/bin/env python3

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PIPELINE_POLICY = (
    ROOT
    / "configs"
    / "product"
    / "pipeline_policy.json"
)


def load_json(path):
    return json.loads(Path(path).read_text())


def resolve(path):
    p = Path(path)

    if not p.is_absolute():
        p = ROOT / p

    return p.resolve()


def parameter_default(text, name):
    patterns = [
        rf"\bparameter\s+{re.escape(name)}\s*=\s*(\d+)",
        rf"\bparameter\s+(?:integer|int)\s+"
        rf"{re.escape(name)}\s*=\s*(\d+)",
    ]

    for pattern in patterns:
        m = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if m:
            return int(m.group(1))

    return None


def find_product_register(pe_text):
    candidates = [
        "mult_reg",
        "product_reg",
        "prod_reg",
    ]

    for name in candidates:
        if re.search(
            rf"\b{re.escape(name)}\b",
            pe_text,
        ):
            return name

    return None


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic AccelClosure RTL contract "
            "and strong-pipeline policy gate."
        )
    )

    parser.add_argument(
        "--run-context",
        required=True,
    )

    parser.add_argument(
        "--iteration",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--output",
        default=None,
    )

    args = parser.parse_args()

    ctx_path = resolve(args.run_context)

    if not ctx_path.exists():
        raise SystemExit(
            f"RTL_POLICY_GATE_ERROR: missing run context: "
            f"{ctx_path}"
        )

    ctx = load_json(ctx_path)

    if ctx.get("schema") != "accelclosure.run_context.v1":
        raise SystemExit(
            "RTL_POLICY_GATE_ERROR: invalid run context schema"
        )

    run_id = ctx["run_id"]

    run_dir = (
        ROOT
        / "results"
        / "runs"
        / run_id
    )

    if args.iteration == 0:
        rtl_dir = run_dir / "rtl"
        generation_report = (
            run_dir
            / "rtl_meta"
            / "rtl_generation_report.json"
        )
    else:
        rtl_dir = (
            run_dir
            / "closure"
            / f"iter{args.iteration}"
            / "rtl"
        )

        generation_report = (
            run_dir
            / "closure"
            / f"iter{args.iteration}"
            / "report.json"
        )

    pe_path = rtl_dir / "accelclosure_ws_pe.sv"
    array_path = rtl_dir / "accelclosure_ws_array.sv"

    errors = []
    checks = []

    def passed(name):
        checks.append(name)

    if not pe_path.exists():
        errors.append("PE RTL missing")

    if not array_path.exists():
        errors.append("Array RTL missing")

    if errors:
        raise SystemExit(
            "RTL_POLICY_GATE_FAIL: "
            + "; ".join(errors)
        )

    pe = pe_path.read_text()
    array = array_path.read_text()

    params = ctx["parameters"]

    expected = {
        "N": int(params["n"]),
        "DATA_W": int(params["activation_width"]),
        "ACC_W": int(params["accumulator_width"]),
    }

    observed = {
        "pe": {
            "DATA_W": parameter_default(
                pe,
                "DATA_W",
            ),
            "ACC_W": parameter_default(
                pe,
                "ACC_W",
            ),
        },
        "array": {
            "N": parameter_default(
                array,
                "N",
            ),
            "DATA_W": parameter_default(
                array,
                "DATA_W",
            ),
            "ACC_W": parameter_default(
                array,
                "ACC_W",
            ),
        },
    }

    # --------------------------------------------------------
    # Canonical parameter contract.
    # --------------------------------------------------------

    parameter_checks = [
        (
            "PE DATA_W",
            observed["pe"]["DATA_W"],
            expected["DATA_W"],
        ),
        (
            "PE ACC_W",
            observed["pe"]["ACC_W"],
            expected["ACC_W"],
        ),
        (
            "ARRAY N",
            observed["array"]["N"],
            expected["N"],
        ),
        (
            "ARRAY DATA_W",
            observed["array"]["DATA_W"],
            expected["DATA_W"],
        ),
        (
            "ARRAY ACC_W",
            observed["array"]["ACC_W"],
            expected["ACC_W"],
        ),
    ]

    for label, actual, wanted in parameter_checks:
        if actual != wanted:
            errors.append(
                f"{label} mismatch: "
                f"RTL={actual}, contract={wanted}"
            )
        else:
            passed(
                f"{label}_MATCH"
            )

    if expected["ACC_W"] < (
        2 * expected["DATA_W"]
    ):
        errors.append(
            "Canonical ACC_W is smaller than "
            "2*DATA_W"
        )
    else:
        passed(
            "CANONICAL_ACCUMULATOR_WIDTH_VALID"
        )

    # --------------------------------------------------------
    # Strong array-boundary policy.
    #
    # These names are deliberately mandatory for the current
    # product family so structural compliance is mechanically
    # inspectable instead of inferred from LLM prose.
    # --------------------------------------------------------

    required_boundary_registers = [
        "weight_load_valid_reg",
        "weight_load_row_reg",
        "weight_load_data_reg",
        "act_valid_in_reg",
        "act_data_in_reg",
        "psum_valid_in_reg",
        "psum_data_in_reg",
    ]

    missing_boundary_registers = [
        name
        for name in required_boundary_registers
        if not re.search(
            rf"\b{re.escape(name)}\b",
            array,
        )
    ]

    if missing_boundary_registers:
        errors.append(
            "mandatory input boundary registers missing: "
            + ", ".join(
                missing_boundary_registers
            )
        )
    else:
        passed(
            "MANDATORY_INPUT_BOUNDARY_REGISTERS"
        )

    # Ensure mesh boundary feeds come from registered inputs.
    required_registered_feeds = [
        r"act_valid_in_reg\s*\[",
        r"act_data_in_reg\s*\[",
        r"psum_valid_in_reg\s*\[",
        r"psum_data_in_reg\s*\[",
    ]

    feed_failures = []

    for pattern in required_registered_feeds:
        if not re.search(
            pattern,
            array,
        ):
            feed_failures.append(pattern)

    if feed_failures:
        errors.append(
            "mesh inputs are not proven to originate "
            "from mandatory boundary registers"
        )
    else:
        passed(
            "REGISTERED_MESH_BOUNDARY_FEEDS"
        )

    # --------------------------------------------------------
    # Strong PE arithmetic pipeline.
    # --------------------------------------------------------

    product_reg = find_product_register(
        pe
    )

    if product_reg is None:
        errors.append(
            "mandatory multiply result register missing "
            "(expected mult_reg/product_reg/prod_reg)"
        )
    else:
        passed(
            "MULTIPLY_RESULT_REGISTER_PRESENT"
        )

        # ----------------------------------------------------
        # Prove that the product register captures the result
        # of a multiplication.
        #
        # Accept either:
        #
        #   mult_reg <= act * weight;
        #
        # or the common synthesizable form:
        #
        #   assign mult_res = act * weight;
        #   mult_reg <= mult_res;
        # ----------------------------------------------------

        direct_mult_capture = re.search(
            rf"\b{re.escape(product_reg)}\b"
            rf"\s*<=\s*[^;]*\*[^;]*;",
            pe,
            flags=re.DOTALL,
        )

        indirect_mult_capture = False
        multiply_source = None

        capture_match = re.search(
            rf"\b{re.escape(product_reg)}\b"
            rf"\s*<=\s*"
            rf"([A-Za-z_][A-Za-z0-9_$]*)"
            rf"\s*;",
            pe,
        )

        if capture_match:
            multiply_source = (
                capture_match.group(1)
            )

            continuous_mult = re.search(
                rf"\bassign\s+"
                rf"{re.escape(multiply_source)}"
                rf"\s*=\s*[^;]*\*[^;]*;",
                pe,
                flags=re.DOTALL,
            )

            procedural_mult = re.search(
                rf"\b{re.escape(multiply_source)}"
                rf"\s*=\s*[^;]*\*[^;]*;",
                pe,
                flags=re.DOTALL,
            )

            indirect_mult_capture = (
                continuous_mult is not None
                or procedural_mult is not None
            )

        if (
            direct_mult_capture is None
            and not indirect_mult_capture
        ):
            errors.append(
                f"{product_reg} is present but is not "
                "proven to capture a multiplication result"
            )
        else:
            passed(
                "MULTIPLY_REGISTER_CAPTURE"
            )

        # ----------------------------------------------------
        # Build a small combinational dependency graph rooted
        # at the registered multiplication result.
        #
        # This allows:
        #
        #   assign prod_extended = {
        #       sign bits,
        #       mult_reg
        #   };
        #
        #   psum_out <= psum_stg1 + prod_extended;
        #
        # without requiring psum_out to mention mult_reg
        # literally.
        # ----------------------------------------------------

        derived_signals = {
            product_reg
        }

        assignments = []

        for match in re.finditer(
            r"\bassign\s+"
            r"([A-Za-z_][A-Za-z0-9_$]*)"
            r"\s*=\s*"
            r"(.*?);",
            pe,
            flags=re.DOTALL,
        ):
            assignments.append(
                (
                    match.group(1),
                    match.group(2),
                )
            )

        # Resolve a few levels of combinational aliases.
        for _ in range(8):
            changed = False

            for lhs, rhs in assignments:

                if lhs in derived_signals:
                    continue

                if any(
                    re.search(
                        rf"\b{re.escape(source)}\b",
                        rhs,
                    )
                    for source
                    in derived_signals
                ):
                    derived_signals.add(
                        lhs
                    )
                    changed = True

            if not changed:
                break

        accumulation_uses_registered_product = False

        for match in re.finditer(
            r"\b(?:psum_out|psum_reg|acc_reg)"
            r"\b\s*<=\s*"
            r"(.*?);",
            pe,
            flags=re.DOTALL,
        ):

            rhs = match.group(1)

            if any(
                re.search(
                    rf"\b{re.escape(source)}\b",
                    rhs,
                )
                for source
                in derived_signals
            ):
                accumulation_uses_registered_product = True
                break

        if not accumulation_uses_registered_product:
            errors.append(
                "accumulation is not proven to consume "
                "the registered multiplication result "
                "or a combinational derivative of it"
            )
        else:
            passed(
                "REGISTERED_MULTIPLY_TO_ACCUMULATE"
            )

    # Explicitly reject the known one-cycle MAC form.
    direct_one_cycle_mac = re.search(
        r"(?:psum_out|psum_reg|acc_reg)"
        r"\s*<=\s*"
        r"(?:psum_in|psum_reg|acc_reg)"
        r"\s*\+\s*"
        r"(?:extended_product|product|mult_res)"
        r"\s*;",
        pe,
    )

    if direct_one_cycle_mac:
        errors.append(
            "single-cycle multiply+accumulate path detected"
        )
    else:
        passed(
            "NO_DIRECT_SINGLE_CYCLE_MAC"
        )

    # --------------------------------------------------------
    # Generator/closure metadata.
    # --------------------------------------------------------

    metadata = None

    if not generation_report.exists():
        errors.append(
            f"generation report missing: "
            f"{generation_report}"
        )
    else:
        report = load_json(
            generation_report
        )

        metadata = report.get(
            "pipeline_metadata"
        )

        if not isinstance(metadata, dict):
            errors.append(
                "pipeline_metadata missing from "
                "generation report"
            )
        else:
            metadata_requirements = {
                "boundary_input_registers": True,
                "valid_alignment_preserved": True,
                "weight_stationary_preserved": True,
                "multiply_accumulate_separated": True,
            }

            for key, wanted in (
                metadata_requirements.items()
            ):
                if metadata.get(key) is not wanted:
                    errors.append(
                        f"pipeline_metadata.{key} "
                        f"must be {wanted}"
                    )
                else:
                    passed(
                        f"METADATA_{key.upper()}"
                    )

            if (
                metadata.get(
                    "boundary_latency_cycles"
                )
                is None
                or metadata[
                    "boundary_latency_cycles"
                ] < 1
            ):
                errors.append(
                    "boundary_latency_cycles must be >= 1"
                )
            else:
                passed(
                    "METADATA_BOUNDARY_LATENCY"
                )

            if (
                metadata.get(
                    "pe_pipeline_stages"
                )
                is None
                or metadata[
                    "pe_pipeline_stages"
                ] < 2
            ):
                errors.append(
                    "pe_pipeline_stages must be >= 2"
                )
            else:
                passed(
                    "METADATA_PE_PIPELINE_STAGES"
                )

            act_hop = metadata.get(
                "activation_hop_latency_cycles"
            )

            psum_hop = metadata.get(
                "psum_hop_latency_cycles"
            )

            if (
                act_hop is None
                or psum_hop is None
                or act_hop < 2
                or psum_hop < 2
                or act_hop != psum_hop
            ):
                errors.append(
                    "activation/psum hop latency must be "
                    "equal and >= 2"
                )
            else:
                passed(
                    "METADATA_SYMMETRIC_HOP_LATENCY"
                )

            if (
                metadata.get(
                    "initiation_interval_cycles"
                )
                != 1
            ):
                errors.append(
                    "initiation_interval_cycles must be 1"
                )
            else:
                passed(
                    "METADATA_II1"
                )

    policy_schema = None

    if PIPELINE_POLICY.exists():
        try:
            policy = load_json(
                PIPELINE_POLICY
            )
            policy_schema = policy.get(
                "schema"
            )
        except Exception as exc:
            errors.append(
                f"cannot load pipeline policy: {exc}"
            )
    else:
        errors.append(
            "canonical pipeline policy file missing"
        )

    if (
        policy_schema
        != "accelclosure.pipeline_policy.v2"
    ):
        errors.append(
            "canonical pipeline policy schema is not v2"
        )
    else:
        passed(
            "CANONICAL_PIPELINE_POLICY_V2"
        )

    status = (
        "PASS"
        if not errors
        else "FAIL"
    )

    result = {
        "schema":
            "accelclosure.rtl_policy_gate.v1",
        "status": status,
        "run_id": run_id,
        "iteration": args.iteration,
        "canonical_parameters": expected,
        "rtl_parameter_defaults": observed,
        "pipeline_policy_schema":
            policy_schema,
        "generation_report":
            str(
                generation_report.relative_to(
                    ROOT
                )
            ),
        "pipeline_metadata": metadata,
        "checks_passed": checks,
        "errors": errors,
        "eda_authorized": (
            status == "PASS"
        ),
    }

    if args.output:
        output = resolve(
            args.output
        )
    else:
        output = (
            run_dir
            / "verification"
            / "rtl_policy_gate.json"
        )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if output.exists():
        raise SystemExit(
            f"RTL_POLICY_GATE_ERROR: "
            f"refusing overwrite: {output}"
        )

    output.write_text(
        json.dumps(
            result,
            indent=2,
        )
        + "\n"
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    print()
    print(
        f"RTL_POLICY_GATE={status}"
    )
    print(
        f"EDA_AUTHORIZED="
        f"{str(status == 'PASS').lower()}"
    )
    print(
        f"REPORT="
        f"{output.relative_to(ROOT)}"
    )

    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
