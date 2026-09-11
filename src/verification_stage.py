#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve(text):
    p = Path(text)

    if not p.is_absolute():
        p = ROOT / p

    return p.resolve()


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


def relative(path):
    return str(
        path.resolve().relative_to(ROOT)
    )


def fail(message, code=1):
    print(
        "VERIFICATION_STAGE_ERROR: "
        + message
    )
    raise SystemExit(code)


def write_json_exclusive(path, data):

    if path.exists():
        fail(
            f"refusing overwrite: {path}"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            data,
            indent=2,
        )
        + "\n"
    )


def execute(cmd, log_path):

    if log_path.exists():
        fail(
            f"refusing overwrite: {log_path}"
        )

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    log_path.write_text(
        result.stdout or ""
    )

    if result.stdout:
        print(
            result.stdout,
            end=(
                ""
                if result.stdout.endswith("\n")
                else "\n"
            ),
        )

    return result.returncode


def numeric_value(data, names):

    for name in names:

        value = data.get(name)

        if isinstance(value, bool):
            continue

        if isinstance(value, int):
            return value

        if isinstance(value, list):
            return len(value)

    return None


def lint_evidence(report):

    status = None
    warnings = None
    errors = None

    sections = [
        report,
    ]

    for name in (
        "summary",
        "result",
        "verilator",
    ):
        section = report.get(name)

        if isinstance(section, dict):
            sections.append(section)

    for section in sections:

        if status is None:

            for key in (
                "status",
                "result",
                "lint_status",
            ):
                value = section.get(key)

                if isinstance(value, str):
                    status = value.upper()
                    break

        if warnings is None:
            warnings = numeric_value(
                section,
                (
                    "warnings",
                    "warning_count",
                    "warnings_count",
                    "lint_warnings",
                ),
            )

        if errors is None:
            errors = numeric_value(
                section,
                (
                    "errors",
                    "error_count",
                    "errors_count",
                    "lint_errors",
                ),
            )

    return status, warnings, errors


def metadata_schedule(
    metadata,
):

    if not isinstance(
        metadata,
        dict,
    ):
        return None

    hop = metadata.get(
        "activation_hop_latency_cycles"
    )

    psum = metadata.get(
        "psum_hop_latency_cycles"
    )

    if (
        not isinstance(hop, int)
        or hop < 1
    ):
        return None

    if (
        psum is not None
        and psum != hop
    ):
        fail(
            "pipeline metadata has unequal "
            "activation/psum hop latency"
        )

    boundary = 0

    if metadata.get(
        "boundary_input_registers"
    ) is True:
        boundary = 1

    if (
        metadata.get(
            "boundary_latency_cycles"
        )
        not in (None, 0)
    ):
        boundary = 1

    return (
        hop,
        boundary,
    )


def structural_schedule(
    pe_path,
    array_path,
):

    pe = pe_path.read_text(
        errors="replace"
    )

    array = array_path.read_text(
        errors="replace"
    )

    boundary = (
        1
        if (
            "act_data_in_reg" in array
            and "psum_data_in_reg" in array
        )
        else 0
    )

    two_stage_signals = (
        "mult_reg",
        "act_stg1",
        "psum_stg1",
    )

    two_stage_score = sum(
        token in pe
        for token in two_stage_signals
    )

    hop = (
        2
        if two_stage_score >= 2
        else 1
    )

    return (
        hop,
        boundary,
    )


def schedule_candidates(
    ctx,
    run_dir,
    iteration,
    pe_path,
    array_path,
):

    # --------------------------------------------------------
    # Closure iterations MUST use the schedule the closure
    # agent itself declared. No guessing after a redesign.
    # --------------------------------------------------------

    if iteration > 0:

        report_path = (
            run_dir
            / "closure"
            / f"iter{iteration}"
            / "report.json"
        )

        if not report_path.exists():
            fail(
                "closure report missing for "
                f"iteration {iteration}"
            )

        report = load_json(
            report_path
        )

        candidate = metadata_schedule(
            report.get(
                "pipeline_metadata"
            )
        )

        if candidate is None:
            fail(
                "closure report does not contain "
                "usable pipeline metadata"
            )

        return (
            [candidate],
            "closure_report_pipeline_metadata",
        )

    # --------------------------------------------------------
    # Initial RTL: prefer explicit generator metadata when
    # present.
    # --------------------------------------------------------

    generator_report = (
        run_dir
        / "rtl_meta"
        / "rtl_generation_report.json"
    )

    if generator_report.exists():

        data = load_json(
            generator_report
        )

        candidate = metadata_schedule(
            data.get(
                "pipeline_metadata"
            )
        )

        if candidate is not None:

            return (
                [candidate],
                "rtl_generator_pipeline_metadata",
            )

    # --------------------------------------------------------
    # Compatibility for generators predating explicit schedule
    # metadata.
    #
    # Structural inspection provides the first candidate.
    # The regression then PROVES which checker schedule matches
    # the RTL; no RTL is modified during this search.
    # --------------------------------------------------------

    detected = structural_schedule(
        pe_path,
        array_path,
    )

    raw_candidates = [
        detected,
        (2, 1),
        (1, 0),
        (2, 0),
        (3, 1),
        (3, 0),
        (4, 1),
        (4, 0),
    ]

    candidates = []

    for item in raw_candidates:
        if item not in candidates:
            candidates.append(item)

    return (
        candidates,
        "rtl_structural_hint_plus_functional_proof",
    )


def failure_record(
    run_id,
    iteration,
    subtype,
    rtl,
    details,
):

    return {
        "schema":
            "accelclosure.verification_failure.v1",

        "status":
            "VERIFICATION_FAILED",

        "failure_class":
            "FUNCTIONAL_RTL",

        "failure_subtype":
            subtype,

        "run_id":
            run_id,

        "iteration":
            iteration,

        "rtl":
            rtl,

        "details":
            details,

        "timing_closure_agent_allowed":
            False,
    }


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Run lint and functional verification "
            "for one AccelClosure implementation."
        )
    )

    parser.add_argument(
        "--run-context",
        required=True,
    )

    parser.add_argument(
        "--iteration",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--random-cases",
        type=int,
        default=25,
    )

    args = parser.parse_args()

    ctx_path = resolve(
        args.run_context
    )

    if not ctx_path.exists():
        fail(
            f"run context missing: {ctx_path}"
        )

    ctx = load_json(
        ctx_path
    )

    if (
        ctx.get("schema")
        != "accelclosure.run_context.v1"
    ):
        fail(
            "unsupported run-context schema"
        )

    run_id = ctx["run_id"]

    run_dir = (
        ROOT
        / "results"
        / "runs"
        / run_id
    )

    iteration = args.iteration

    if iteration < 0:
        fail(
            "iteration must be >= 0"
        )

    if iteration == 0:

        rtl_dir = (
            run_dir
            / "rtl"
        )

        verification_dir = (
            run_dir
            / "verification"
        )

    else:

        impl_root = (
            run_dir
            / "closure"
            / f"iter{iteration}"
        )

        rtl_dir = (
            impl_root
            / "rtl"
        )

        verification_dir = (
            impl_root
            / "verification"
        )

    verification_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    pe_path = (
        rtl_dir
        / "accelclosure_ws_pe.sv"
    )

    array_path = (
        rtl_dir
        / "accelclosure_ws_array.sv"
    )

    if not pe_path.exists():
        fail(
            "PE RTL missing"
        )

    if not array_path.exists():
        fail(
            "array RTL missing"
        )

    params = ctx[
        "parameters"
    ]

    n = int(
        params["n"]
    )

    data_w = int(
        params["activation_width"]
    )

    acc_w = int(
        params["accumulator_width"]
    )

    if n > 32:
        fail(
            "current functional harness supports "
            "N <= 32",
            32,
        )

    pe_hash = sha256(
        pe_path
    )

    array_hash = sha256(
        array_path
    )

    rtl_record = {
        "pe_path":
            relative(pe_path),

        "array_path":
            relative(array_path),

        "pe_sha256":
            pe_hash,

        "array_sha256":
            array_hash,
    }

    print()
    print(
        "============================================================"
    )
    print(
        " ACCELCLOSURE VERIFICATION STAGE"
    )
    print(
        "============================================================"
    )
    print(
        f"RUN_ID={run_id}"
    )
    print(
        f"ITERATION={iteration}"
    )
    print(
        f"N={n}"
    )
    print(
        f"PE_SHA256={pe_hash}"
    )
    print(
        f"ARRAY_SHA256={array_hash}"
    )

    # ========================================================
    # RTL policy gate
    # ========================================================

    policy_report = (
        verification_dir
        / "rtl_policy_gate.json"
    )

    policy_log = (
        verification_dir
        / "rtl_policy_gate.log"
    )

    if policy_report.exists():
        fail(
            f"refusing overwrite: {policy_report}"
        )

    policy_cmd = [
        sys.executable,
        str(
            ROOT
            / "src"
            / "rtl_policy_gate.py"
        ),
        "--run-context",
        str(ctx_path),
        "--iteration",
        str(iteration),
        "--output",
        str(policy_report),
    ]

    policy_rc = execute(
        policy_cmd,
        policy_log,
    )

    if not policy_report.exists():
        failure = failure_record(
            run_id,
            iteration,
            "RTL_POLICY_REPORT_MISSING",
            rtl_record,
            {
                "returncode": policy_rc,
                "log": relative(policy_log),
            },
        )

        write_json_exclusive(
            verification_dir
            / "failure_summary.json",
            failure,
        )

        print(
            "FAILURE_CLASS=FUNCTIONAL_RTL"
        )
        print(
            "FAILURE_SUBTYPE=RTL_POLICY_REPORT_MISSING"
        )
        print(
            "TIMING_CLOSURE_AGENT_ALLOWED=false"
        )

        raise SystemExit(30)

    policy = load_json(
        policy_report
    )

    if (
        policy_rc != 0
        or policy.get("status") != "PASS"
        or policy.get("eda_authorized") is not True
    ):
        failure = failure_record(
            run_id,
            iteration,
            "RTL_POLICY_VIOLATION",
            rtl_record,
            {
                "returncode": policy_rc,
                "status": policy.get("status"),
                "eda_authorized":
                    policy.get("eda_authorized"),
                "errors":
                    policy.get("errors", []),
                "report":
                    relative(policy_report),
                "log":
                    relative(policy_log),
            },
        )

        write_json_exclusive(
            verification_dir
            / "failure_summary.json",
            failure,
        )

        print(
            "FAILURE_CLASS=FUNCTIONAL_RTL"
        )
        print(
            "FAILURE_SUBTYPE=RTL_POLICY_VIOLATION"
        )
        print(
            "TIMING_CLOSURE_AGENT_ALLOWED=false"
        )
        print(
            "EDA_AUTHORIZED=false"
        )

        raise SystemExit(30)

    print(
        "RTL_POLICY_GATE=PASS"
    )
    print(
        "EDA_POLICY_AUTHORIZATION=PASS"
    )

    # ========================================================
    # Lint
    # ========================================================

    lint_report = (
        verification_dir
        / "verilator_lint.json"
    )

    lint_log = (
        verification_dir
        / "verilator_lint.log"
    )

    if lint_report.exists():
        fail(
            f"refusing overwrite: {lint_report}"
        )

    lint_cmd = [
        sys.executable,
        str(
            ROOT
            / "tests"
            / "run_verilator_parametric_lint.py"
        ),
        "--n",
        str(n),
        "--data-w",
        str(data_w),
        "--acc-w",
        str(acc_w),
        "--pe",
        str(pe_path),
        "--array",
        str(array_path),
        "--report",
        str(lint_report),
    ]

    lint_rc = execute(
        lint_cmd,
        lint_log,
    )

    if not lint_report.exists():

        failure = failure_record(
            run_id,
            iteration,
            "LINT_REPORT_MISSING",
            rtl_record,
            {
                "returncode":
                    lint_rc,

                "log":
                    relative(
                        lint_log
                    ),
            },
        )

        write_json_exclusive(
            verification_dir
            / "failure_summary.json",
            failure,
        )

        fail(
            "lint report was not produced",
            31,
        )

    lint = load_json(
        lint_report
    )

    lint_status, warnings, errors = (
        lint_evidence(
            lint
        )
    )

    if (
        lint_rc != 0
        or lint_status != "PASS"
        or warnings != 0
        or errors != 0
    ):

        failure = failure_record(
            run_id,
            iteration,
            "LINT_FAILED",
            rtl_record,
            {
                "returncode":
                    lint_rc,

                "status":
                    lint_status,

                "warnings":
                    warnings,

                "errors":
                    errors,

                "report":
                    relative(
                        lint_report
                    ),

                "log":
                    relative(
                        lint_log
                    ),
            },
        )

        write_json_exclusive(
            verification_dir
            / "failure_summary.json",
            failure,
        )

        print(
            "FAILURE_CLASS=FUNCTIONAL_RTL"
        )
        print(
            "FAILURE_SUBTYPE=LINT_FAILED"
        )
        print(
            "TIMING_CLOSURE_AGENT_ALLOWED=false"
        )

        raise SystemExit(31)

    print(
        "LINT_GATE=PASS"
    )

    # ========================================================
    # Functional schedule + regression
    # ========================================================

    candidates, schedule_source = (
        schedule_candidates(
            ctx,
            run_dir,
            iteration,
            pe_path,
            array_path,
        )
    )

    print(
        "SCHEDULE_SOURCE="
        + schedule_source
    )

    print(
        "SCHEDULE_CANDIDATES="
        + ",".join(
            f"H{h}/B{b}"
            for h, b
            in candidates
        )
    )

    selected = None
    attempts = []

    for hop, boundary in candidates:

        report_path = (
            verification_dir
            / (
                "verilator_gemm_"
                f"h{hop}_b{boundary}.json"
            )
        )

        log_path = (
            verification_dir
            / (
                "verilator_gemm_"
                f"h{hop}_b{boundary}.log"
            )
        )

        cmd = [
            sys.executable,
            str(
                ROOT
                / "tests"
                / "run_verilator_parametric.py"
            ),
            "--n",
            str(n),
            "--data-w",
            str(data_w),
            "--acc-w",
            str(acc_w),
            "--hop-latency",
            str(hop),
            "--boundary-registers",
            str(boundary),
            "--random-cases",
            str(
                args.random_cases
            ),
            "--pe",
            str(pe_path),
            "--array",
            str(array_path),
            "--report",
            str(report_path),
        ]

        print()
        print(
            "FUNCTIONAL_ATTEMPT="
            f"H{hop}/B{boundary}"
        )

        rc = execute(
            cmd,
            log_path,
        )

        status = None
        functional_verified = False

        if report_path.exists():

            report = load_json(
                report_path
            )

            value = report.get(
                "status"
            )

            if isinstance(
                value,
                str,
            ):
                status = (
                    value.upper()
                )

            functional_verified = (
                report.get(
                    "functional_verified"
                )
                is True
                or status == "PASS"
            )

        attempts.append(
            {
                "hop_latency":
                    hop,

                "boundary_registers":
                    boundary,

                "returncode":
                    rc,

                "status":
                    status,

                "report":
                    (
                        relative(
                            report_path
                        )
                        if report_path.exists()
                        else None
                    ),

                "log":
                    relative(
                        log_path
                    ),
            }
        )

        if (
            status == "PASS"
            and functional_verified
        ):

            selected = {
                "hop_latency":
                    hop,

                "boundary_registers":
                    boundary,

                "report_path":
                    report_path,
            }

            break

        # Closure iterations declared an exact schedule.
        # A failure here is a real functional failure;
        # do not silently try a different schedule.
        if iteration > 0:
            break

    if selected is None:

        failure = failure_record(
            run_id,
            iteration,
            "SIGNED_GEMM_REGRESSION_FAILED",
            rtl_record,
            {
                "schedule_source":
                    schedule_source,

                "attempts":
                    attempts,
            },
        )

        write_json_exclusive(
            verification_dir
            / "failure_summary.json",
            failure,
        )

        print(
            "FAILURE_CLASS=FUNCTIONAL_RTL"
        )
        print(
            "FAILURE_SUBTYPE="
            "SIGNED_GEMM_REGRESSION_FAILED"
        )
        print(
            "TIMING_CLOSURE_AGENT_ALLOWED=false"
        )

        raise SystemExit(30)

    # ========================================================
    # Freeze verification provenance
    # ========================================================

    hashes_path = (
        verification_dir
        / "verified_rtl_sha256.txt"
    )

    if hashes_path.exists():
        fail(
            f"refusing overwrite: {hashes_path}"
        )

    hashes_path.write_text(
        f"{pe_hash}  {relative(pe_path)}\n"
        f"{array_hash}  {relative(array_path)}\n"
    )

    summary = {
        "schema":
            "accelclosure.verification_summary.v2",

        "status":
            "FUNCTIONALLY_VERIFIED",

        "run_id":
            run_id,

        "iteration":
            iteration,

        "configuration": {
            "n":
                n,

            "data_w":
                data_w,

            "acc_w":
                acc_w,

            "hop_latency":
                selected[
                    "hop_latency"
                ],

            "boundary_registers":
                selected[
                    "boundary_registers"
                ],

            "random_cases":
                args.random_cases,

            "schedule_source":
                schedule_source,
        },

        "rtl":
            rtl_record,

        "lint": {
            "status":
                "PASS",

            "warnings":
                0,

            "errors":
                0,

            "report":
                relative(
                    lint_report
                ),
        },

        "functional": {
            "status":
                "PASS",

            "report":
                relative(
                    selected[
                        "report_path"
                    ]
                ),

            "attempts":
                attempts,
        },

        "functional_verified":
            True,

        "lint_verified":
            True,

        "timing_measured":
            False,

        "physical_design_completed":
            False,

        "timing_closure_agent_allowed":
            False,
    }

    summary_path = (
        verification_dir
        / "summary.json"
    )

    write_json_exclusive(
        summary_path,
        summary,
    )

    print()
    print(
        "VERIFICATION_STAGE=PASS"
    )
    print(
        "STATUS=FUNCTIONALLY_VERIFIED"
    )
    print(
        "HOP_LATENCY="
        + str(
            selected[
                "hop_latency"
            ]
        )
    )
    print(
        "BOUNDARY_REGISTERS="
        + str(
            selected[
                "boundary_registers"
            ]
        )
    )
    print(
        "SUMMARY="
        + relative(
            summary_path
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
