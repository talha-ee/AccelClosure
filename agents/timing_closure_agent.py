#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

from chia.base.ChiaFunction import get
from chia.models.opencode import (
    AdditionalModelProvider,
    OpenCodeLLM,
    QueryResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

PERSIST_ROOT = Path(
    os.environ.get(
        "ACCELCLOSURE_ROOT",
        str(PROJECT_ROOT),
    )
).expanduser().resolve()

MODEL = "google-vertex/gemini-3.1-pro-preview"


def load_json(path):
    with Path(path).open() as f:
        return json.load(f)


def sha256(path):
    return hashlib.sha256(
        Path(path).read_bytes()
    ).hexdigest()


def extract_json(text):
    text = text.strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    first = text.find("{")
    last = text.rfind("}")

    if first == -1 or last == -1 or last <= first:
        raise ValueError(
            "No JSON object found in timing-closure response"
        )

    return json.loads(
        text[first:last + 1]
    )


def make_prompt(
    run_context,
    contract,
    verification,
    sta,
    pe_rtl,
    array_rtl,
    golden_context,
    pipeline_policy,
):
    params = run_context["parameters"]

    n = params["n"]
    freq = params["target_frequency_mhz"]
    period = params["target_period_ns"]
    tech = params["technology"]

    requested = contract["requested_constraints"]

    return f"""
You are the AccelClosure Timing Closure Agent.

A REAL accelerator implementation has already passed functional
verification but FAILED real static timing analysis.

Your task is to redesign the accelerator microarchitecture using the
measured timing evidence.

This is not a cosmetic RTL repair.

The clock target is FIXED by the user and MUST NOT be relaxed.

================ USER DESIGN TARGET ================

Array:
{n}x{n}

Technology:
{tech}

Target frequency:
{freq} MHz

Target period:
{period} ns

Dataflow:
{requested["dataflow"]}

Input precision:
{requested["input_precision"]}

Weight precision:
{requested["weight_precision"]}

Accumulator precision:
{contract["proposed_architecture"]["accumulator_precision"]}

================ VERIFIED BASELINE ================

{json.dumps(verification, indent=2)}

================ REAL STA FAILURE ================

{json.dumps(sta, indent=2)}

================ CURRENT VERIFIED PE RTL ================

{pe_rtl}

================ CURRENT VERIFIED ARRAY RTL ================

{array_rtl}

================ GOLDEN ARCHITECTURE CONTEXT ================

{json.dumps(golden_context, indent=2)}

================ MANDATORY PIPELINE POLICY ================

{json.dumps(pipeline_policy, indent=2)}

================ CLOSURE OBJECTIVE ================

The baseline is functionally correct but does not meet the requested
clock.

Use the REAL STA critical path and measurements to redesign the
microarchitecture.

For this accelerator family the following requirements are mandatory:

1. Preserve the parameterized square N x N weight-stationary systolic
   architecture.

2. Preserve exactly N*N processing elements.

3. Preserve signed INT8 activation and signed INT8 stationary-weight
   multiplication with signed INT32 partial-sum accumulation.

4. Preserve activation propagation from left to right.

5. Preserve partial-sum propagation from top to bottom.

6. Preserve stationary weight B[k][j] at the PE corresponding to k,j.

7. Preserve all existing top-level external port names and widths unless
   an interface change is mathematically unavoidable.

8. Add synchronous ARRAY INPUT BOUNDARY REGISTERS.
   Primary activation and partial-sum inputs must not directly feed a
   substantial MAC combinational path.

9. The PE arithmetic pipeline must contain AT LEAST TWO arithmetic
   stages.

10. Multiplication and accumulation MUST NOT remain in the same
    combinational timing stage.

11. A sequential pipeline boundary must separate multiplication from
    accumulation.

12. Every PE-to-PE activation hop must be sequentially registered.

13. Every PE-to-PE partial-sum hop must be sequentially registered.

14. Valid signals must be pipelined with the corresponding data.

15. Activation-hop latency and partial-sum-hop latency must be equal.

16. Maintain steady-state initiation interval II=1 after pipeline fill.

17. Additional pipeline stages are allowed if they are structurally
    justified.

18. Do not insert multicycle paths, false paths, or other timing
    exceptions to hide the failure.

19. Do not relax the {period} ns / {freq} MHz target.

20. Do not add unrelated hardware such as DMA, CPU interfaces, SRAM
    macros, clock gating, or power gating.

21. Do not implement behavioral matrix multiplication.

22. The redesign remains UNVERIFIED until simulation, synthesis, and STA
    are rerun.

23. Do NOT claim that the requested frequency has been achieved.

================ REQUIRED OUTPUT ================

Return ONLY one valid JSON object.

No Markdown.
No code fences.

Use exactly this structure:

{{
  "closure_version": "2.0",

  "failure_class": "TIMING_ARCHITECTURE",

  "measured_failure": {{
    "target_frequency_mhz": {freq},
    "target_period_ns": {period},
    "wns_ns": {sta["measurement"]["wns_ns"]},
    "tns_ns": {sta["measurement"]["tns_ns"]},
    "minimum_period_ns": {sta["measurement"]["minimum_period_ns"]},
    "fmax_estimate_mhz": {sta["measurement"]["fmax_estimate_mhz"]},
    "critical_startpoint": {json.dumps(sta["critical_path"]["startpoint"])},
    "critical_endpoint": {json.dumps(sta["critical_path"]["endpoint"])}
  }},

  "root_cause": "...",

  "architecture_change": "...",

  "pipeline_metadata": {{
    "boundary_input_registers": true,
    "boundary_latency_cycles": 1,
    "pe_pipeline_stages": 2,
    "activation_hop_latency_cycles": 2,
    "psum_hop_latency_cycles": 2,
    "valid_alignment_preserved": true,
    "weight_stationary_preserved": true,
    "initiation_interval_cycles": 1,
    "multiply_accumulate_separated": true,
    "external_schedule_change_required": true
  }},

  "timing_reasoning": [
    "..."
  ],

  "files": [
    {{
      "path": "rtl/accelclosure_ws_pe.sv",
      "content": "..."
    }},
    {{
      "path": "rtl/accelclosure_ws_array.sv",
      "content": "..."
    }}
  ],

  "verification_required": [
    "Verilator lint",
    "Directed signed GEMM verification",
    "Random signed INT8 GEMM regression",
    "Sky130 synthesis at {period} ns",
    "OpenROAD STA at {period} ns"
  ],

  "measurement_status": {{
    "functional_verified_after_redesign": false,
    "timing_measured_after_redesign": false,
    "timing_closed": false
  }}
}}
"""


def validate_bundle(bundle, target_frequency, target_period):
    errors = []

    if bundle.get("failure_class") != "TIMING_ARCHITECTURE":
        errors.append(
            "failure_class must be TIMING_ARCHITECTURE"
        )

    measured = bundle.get("measured_failure")

    if not isinstance(measured, dict):
        errors.append(
            "measured_failure missing"
        )
    else:
        if float(
            measured.get(
                "target_frequency_mhz",
                -1,
            )
        ) != float(target_frequency):
            errors.append(
                "target frequency changed by closure agent"
            )

        if float(
            measured.get(
                "target_period_ns",
                -1,
            )
        ) != float(target_period):
            errors.append(
                "target period changed by closure agent"
            )

    metadata = bundle.get("pipeline_metadata")

    if not isinstance(metadata, dict):
        errors.append(
            "pipeline_metadata missing"
        )
    else:
        if metadata.get(
            "boundary_input_registers"
        ) is not True:
            errors.append(
                "Boundary input registers are mandatory"
            )

        boundary_latency = metadata.get(
            "boundary_latency_cycles"
        )

        if (
            not isinstance(boundary_latency, int)
            or boundary_latency < 1
        ):
            errors.append(
                "Boundary latency must be >= 1 cycle"
            )

        pe_stages = metadata.get(
            "pe_pipeline_stages"
        )

        if (
            not isinstance(pe_stages, int)
            or pe_stages < 2
        ):
            errors.append(
                "PE pipeline must contain at least 2 stages"
            )

        act_latency = metadata.get(
            "activation_hop_latency_cycles"
        )

        psum_latency = metadata.get(
            "psum_hop_latency_cycles"
        )

        if act_latency != psum_latency:
            errors.append(
                "Activation and psum hop latency must match"
            )

        if (
            not isinstance(act_latency, int)
            or act_latency < 2
        ):
            errors.append(
                "PE hop latency must be >= 2 cycles"
            )

        if metadata.get(
            "multiply_accumulate_separated"
        ) is not True:
            errors.append(
                "Multiply and accumulate must be separated"
            )

        if metadata.get(
            "valid_alignment_preserved"
        ) is not True:
            errors.append(
                "Valid alignment must be preserved"
            )

        if metadata.get(
            "weight_stationary_preserved"
        ) is not True:
            errors.append(
                "Weight-stationary behavior must be preserved"
            )

        if metadata.get(
            "initiation_interval_cycles"
        ) != 1:
            errors.append(
                "Initiation interval must remain 1"
            )

    measurement_status = bundle.get(
        "measurement_status"
    )

    if not isinstance(measurement_status, dict):
        errors.append(
            "measurement_status missing"
        )
    else:
        if measurement_status.get(
            "timing_closed"
        ) is not False:
            errors.append(
                "Agent may not claim timing closure before STA"
            )

        if measurement_status.get(
            "timing_measured_after_redesign"
        ) is not False:
            errors.append(
                "Redesigned timing has not yet been measured"
            )

    files = bundle.get(
        "files",
        [],
    )

    expected = {
        "rtl/accelclosure_ws_pe.sv",
        "rtl/accelclosure_ws_array.sv",
    }

    actual = {
        item.get("path")
        for item in files
        if isinstance(item, dict)
    }

    if actual != expected:
        errors.append(
            "Expected exactly the PE and array RTL files"
        )

    for item in files:
        if not isinstance(item, dict):
            errors.append(
                "Invalid file item"
            )
            continue

        path = item.get(
            "path",
            "",
        )

        content = item.get(
            "content",
            "",
        )

        if not content.strip():
            errors.append(
                f"Empty RTL content for {path}"
            )
            continue

        if "```" in content:
            errors.append(
                f"Markdown fence found in {path}"
            )

        if path.endswith(".sv"):
            module = Path(path).stem

            if f"module {module}" not in content:
                errors.append(
                    f"Expected module {module} missing from {path}"
                )

    return errors


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run-context",
        required=True,
    )

    parser.add_argument(
        "--iteration",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--pipeline-policy",
        default="configs/product/pipeline_policy.json",
    )

    args = parser.parse_args()

    ctx_path = Path(args.run_context)

    if not ctx_path.is_absolute():
        ctx_path = PERSIST_ROOT / ctx_path

    run_context = load_json(ctx_path)

    run_id = run_context["run_id"]

    run_dir = (
        PERSIST_ROOT
        / "results"
        / "runs"
        / run_id
    )

    contract_path = (
        run_dir
        / "contract"
        / "design_contract.json"
    )

    golden_path = (
        run_dir
        / "contract"
        / "golden_context.json"
    )

    verification_path = (
        run_dir
        / "verification"
        / "summary.json"
    )

    sta_path = (
        run_dir
        / "eda"
        / "sta"
        / "summary.json"
    )

    pe_path = (
        run_dir
        / "rtl"
        / "accelclosure_ws_pe.sv"
    )

    array_path = (
        run_dir
        / "rtl"
        / "accelclosure_ws_array.sv"
    )

    policy_path = Path(
        args.pipeline_policy
    )

    if not policy_path.is_absolute():
        policy_path = (
            PERSIST_ROOT
            / policy_path
        )

    required = [
        contract_path,
        golden_path,
        verification_path,
        sta_path,
        pe_path,
        array_path,
        policy_path,
    ]

    for path in required:
        if not path.exists():
            raise RuntimeError(
                f"Required closure input missing: {path}"
            )

    contract = load_json(
        contract_path
    )

    golden_context = load_json(
        golden_path
    )

    verification = load_json(
        verification_path
    )

    sta = load_json(
        sta_path
    )

    pipeline_policy = load_json(
        policy_path
    )

    if verification.get(
        "status"
    ) != "FUNCTIONALLY_VERIFIED":
        raise RuntimeError(
            "Closure blocked: baseline is not functionally verified"
        )

    if sta.get(
        "closure",
        {},
    ).get(
        "status"
    ) != "TIMING_FAILED":
        raise RuntimeError(
            "Closure blocked: measured timing failure not present"
        )

    if sta.get(
        "closure",
        {},
    ).get(
        "target_met"
    ) is not False:
        raise RuntimeError(
            "Closure blocked: target is already met"
        )

    # --------------------------------------------------------
    # Provenance gate:
    # closure must operate on exactly the RTL that was verified.
    # --------------------------------------------------------

    expected_pe_hash = (
        verification["rtl"]["pe_sha256"]
    )

    expected_array_hash = (
        verification["rtl"]["array_sha256"]
    )

    actual_pe_hash = sha256(
        pe_path
    )

    actual_array_hash = sha256(
        array_path
    )

    if actual_pe_hash != expected_pe_hash:
        raise RuntimeError(
            "Closure blocked: PE RTL changed after verification"
        )

    if actual_array_hash != expected_array_hash:
        raise RuntimeError(
            "Closure blocked: array RTL changed after verification"
        )

    params = run_context["parameters"]

    target_frequency = params[
        "target_frequency_mhz"
    ]

    target_period = params[
        "target_period_ns"
    ]

    pe_rtl = pe_path.read_text()
    array_rtl = array_path.read_text()

    prompt = make_prompt(
        run_context,
        contract,
        verification,
        sta,
        pe_rtl,
        array_rtl,
        golden_context,
        pipeline_policy,
    )

    project = os.environ.get(
        "GOOGLE_CLOUD_PROJECT"
    )

    if not project:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT is not set"
        )

    vertex = AdditionalModelProvider(
        id="google-vertex",
        npm="@ai-sdk/google-vertex",
        name="Google Vertex AI",
        models=[
            "gemini-3.1-pro-preview"
        ],
        options={
            "project": project,
            "location": "global",
        },
    )

    llm = OpenCodeLLM(
        model=MODEL,
        additional_providers=[
            vertex
        ],
    )

    iteration = args.iteration

    closure_dir = (
        run_dir
        / "closure"
        / f"iter{iteration}"
    )

    rtl_out = (
        closure_dir
        / "rtl"
    )

    if (
        rtl_out
        / "accelclosure_ws_pe.sv"
    ).exists() or (
        rtl_out
        / "accelclosure_ws_array.sv"
    ).exists():
        raise RuntimeError(
            f"Closure iteration {iteration} already contains RTL. "
            "Use a new iteration number to preserve provenance."
        )

    closure_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    rtl_out.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        "[AccelClosure] VERIFIED_BASELINE_HASH_GATE=PASS"
    )

    print(
        "[AccelClosure] TIMING_FAILURE_GATE=PASS"
    )

    print(
        "[AccelClosure] Run:",
        run_id,
    )

    print(
        "[AccelClosure] Iteration:",
        iteration,
    )

    print(
        "[AccelClosure] Target:",
        f"{target_frequency} MHz / {target_period} ns",
    )

    print(
        "[AccelClosure] Measured WNS:",
        sta["measurement"]["wns_ns"],
        "ns",
    )

    print(
        "[AccelClosure] Measured minimum period:",
        sta["measurement"]["minimum_period_ns"],
        "ns",
    )

    print(
        "[AccelClosure] Dispatching measured timing failure "
        "to Gemini closure agent..."
    )

    response: QueryResult = get(
        llm.prompt.chia_remote(
            llm,
            prompt,
        )
    )

    raw = response.result

    raw_path = (
        closure_dir
        / "agent_raw.txt"
    )

    raw_path.write_text(
        raw
    )

    bundle = extract_json(
        raw
    )

    errors = validate_bundle(
        bundle,
        target_frequency,
        target_period,
    )

    if errors:
        invalid_path = (
            closure_dir
            / "invalid_bundle.json"
        )

        invalid_path.write_text(
            json.dumps(
                {
                    "status":
                        "CLOSURE_BUNDLE_INVALID",

                    "errors":
                        errors,

                    "bundle":
                        bundle,
                },
                indent=2,
            )
            + "\n"
        )

        raise RuntimeError(
            "Timing closure bundle invalid: "
            + "; ".join(errors)
        )

    bundle_path = (
        closure_dir
        / "agent_bundle.json"
    )

    bundle_path.write_text(
        json.dumps(
            bundle,
            indent=2,
        )
        + "\n"
    )

    written = {}

    for item in bundle["files"]:
        relative = Path(
            item["path"]
        )

        destination = (
            rtl_out
            / relative.name
        )

        destination.write_text(
            item["content"]
        )

        written[
            destination.name
        ] = sha256(
            destination
        )

        print(
            "[AccelClosure] WROTE:",
            destination,
        )

    report = {
        "schema":
            "accelclosure.timing_closure_iteration.v1",

        "status":
            "REDESIGNED_UNVERIFIED",

        "run_id":
            run_id,

        "iteration":
            iteration,

        "source_baseline": {
            "pe_sha256":
                actual_pe_hash,

            "array_sha256":
                actual_array_hash,

            "verification_summary":
                str(
                    verification_path.relative_to(
                        PERSIST_ROOT
                    )
                ),

            "sta_summary":
                str(
                    sta_path.relative_to(
                        PERSIST_ROOT
                    )
                ),
        },

        "target": {
            "frequency_mhz":
                target_frequency,

            "period_ns":
                target_period,
        },

        "measured_failure":
            bundle["measured_failure"],

        "failure_class":
            bundle["failure_class"],

        "root_cause":
            bundle["root_cause"],

        "architecture_change":
            bundle["architecture_change"],

        "pipeline_metadata":
            bundle["pipeline_metadata"],

        "timing_reasoning":
            bundle.get(
                "timing_reasoning",
                [],
            ),

        "generated_rtl": {
            "directory":
                str(
                    rtl_out.relative_to(
                        PERSIST_ROOT
                    )
                ),

            "sha256":
                written,
        },

        "verification_required":
            bundle.get(
                "verification_required",
                [],
            ),

        "functional_verified":
            False,

        "timing_measured":
            False,

        "timing_closed":
            False,
    }

    report_path = (
        closure_dir
        / "report.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
        )
        + "\n"
    )

    print()
    print(
        "[AccelClosure] CLOSURE_ITERATION_GENERATED_UNVERIFIED"
    )

    print(
        "[AccelClosure] Report:",
        report_path,
    )

    print()
    print(
        json.dumps(
            report,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
