#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(
    0,
    str(ROOT / "src"),
)

from run_context import (  # noqa: E402
    build_context,
    initialize_run,
)


AUTOMATION_POLICY = (
    ROOT
    / "configs"
    / "product"
    / "automation_policy.json"
)

PIPELINE_POLICY = (
    ROOT
    / "configs"
    / "product"
    / "pipeline_policy.json"
)


def utc():
    return datetime.now(
        timezone.utc
    ).isoformat()


def load_json(path):
    return json.loads(
        Path(path).read_text()
    )


def relative(path):
    return str(
        Path(path)
        .resolve()
        .relative_to(ROOT)
    )


def require(cond, message):
    if not cond:
        raise RuntimeError(
            message
        )


def write_json_exclusive(
    path,
    data,
):

    path = Path(path)

    if path.exists():
        raise RuntimeError(
            "refusing overwrite: "
            + str(path)
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


class EventLog:

    def __init__(
        self,
        path,
    ):
        self.path = Path(path)

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.sequence = 0

    def emit(
        self,
        stage,
        status,
        details=None,
    ):

        self.sequence += 1

        record = {
            "schema":
                "accelclosure.orchestrator_event.v1",

            "sequence":
                self.sequence,

            "timestamp_utc":
                utc(),

            "stage":
                stage,

            "status":
                status,

            "details":
                details or {},
        }

        with self.path.open(
            "a",
            encoding="utf-8",
        ) as f:

            f.write(
                json.dumps(record)
                + "\n"
            )


def stream_command(
    cmd,
    stage,
    logs_dir,
    events,
    iteration=None,
    allowed_returncodes=None,
):

    if allowed_returncodes is None:
        allowed_returncodes = {
            0,
        }

    suffix = (
        ""
        if iteration is None
        else f"_iter{iteration}"
    )

    log_path = (
        logs_dir
        / f"{stage}{suffix}.log"
    )

    if log_path.exists():
        raise RuntimeError(
            "refusing overwrite: "
            + str(log_path)
        )

    display = " ".join(
        str(x)
        for x in cmd
    )

    print()
    print(
        "============================================================"
    )
    print(
        " ACCELCLOSURE STAGE: "
        + stage.upper()
    )
    print(
        "============================================================"
    )
    print(display)
    print()

    events.emit(
        stage,
        "STARTED",
        {
            "iteration":
                iteration,

            "command":
                [
                    str(x)
                    for x in cmd
                ],

            "log":
                relative(
                    log_path
                ),
        },
    )

    with log_path.open(
        "x",
        encoding="utf-8",
    ) as log:

        process = subprocess.Popen(
            [
                str(x)
                for x in cmd
            ],
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        assert (
            process.stdout
            is not None
        )

        for line in process.stdout:

            print(
                line,
                end="",
                flush=True,
            )

            log.write(line)
            log.flush()

        rc = process.wait()

    events.emit(
        stage,
        (
            "COMPLETED"
            if rc in allowed_returncodes
            else "FAILED"
        ),
        {
            "iteration":
                iteration,

            "returncode":
                rc,

            "log":
                relative(
                    log_path
                ),
        },
    )

    if rc not in allowed_returncodes:

        raise RuntimeError(
            f"{stage} failed with "
            f"return code {rc}"
        )

    return rc


def implementation_context_path(
    run_dir,
    iteration,
):

    if iteration == 0:

        return (
            run_dir
            / "implementation_context.json"
        )

    return (
        run_dir
        / "closure"
        / f"iter{iteration}"
        / "implementation_context.json"
    )


def sta_summary_path(
    run_dir,
    iteration,
):

    if iteration == 0:

        return (
            run_dir
            / "eda"
            / "sta"
            / "summary.json"
        )

    return (
        run_dir
        / "closure"
        / f"iter{iteration}"
        / "eda"
        / "sta"
        / "summary.json"
    )


def physical_summary_path(
    run_dir,
    iteration,
):

    if iteration == 0:

        return (
            run_dir
            / "eda"
            / "physical"
            / "summary_v2.json"
        )

    return (
        run_dir
        / "closure"
        / f"iter{iteration}"
        / "eda"
        / "physical"
        / "summary_v2.json"
    )


def timing_target_met(
    sta,
):

    schema = sta.get(
        "schema"
    )

    if schema == (
        "accelclosure.prelayout_sta_summary.v1"
    ):

        return bool(
            sta.get(
                "closure",
                {},
            ).get(
                "target_met"
            )
        )

    return bool(
        sta.get(
            "target_met"
        )
    )


def make_closure_policy_context(
    selection_path,
    output_path,
):

    base = load_json(
        PIPELINE_POLICY
    )

    selection = load_json(
        selection_path
    )

    # Keep the canonical pipeline-policy schema intact.
    # The closure agent already serializes the entire policy
    # into its prompt, so these retrieved references become
    # explicit agent context without changing its API.
    base[
        "retrieved_closure_references"
    ] = selection.get(
        "selection",
        [],
    )

    base[
        "retrieved_reference_policy"
    ] = {
        "purpose":
            "closure",

        "metric_reuse_allowed":
            False,

        "fresh_eda_required":
            True,

        "use_for":
            [
                "failure_pattern_reasoning",
                "pipeline_strategy_reasoning",
                "eda_recovery_reasoning",
            ],

        "do_not_use_for":
            [
                "reusing_PPA_as_fresh_measurement",
                "self_declaring_timing_closure",
            ],
    }

    write_json_exclusive(
        output_path,
        base,
    )


def checkpoint(
    stop_after,
    stage,
    run_id,
    run_context_path,
):

    if stop_after != stage:
        return False

    print()
    print(
        "ACCELCLOSURE_CHECKPOINT_REACHED"
    )
    print(
        "STAGE="
        + stage
    )
    print(
        "RUN_ID="
        + run_id
    )
    print(
        "RUN_CONTEXT="
        + relative(
            run_context_path
        )
    )

    return True


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Autonomous AccelClosure "
            "prompt-to-silicon orchestrator."
        )
    )

    parser.add_argument(
        "request",
        help=(
            "Natural-language accelerator "
            "design request"
        ),
    )

    parser.add_argument(
        "--stop-after",
        choices=[
            "context",
            "contract",
            "rtl",
            "verification",
            "sta",
            "physical",
        ],
        default=None,
        help=(
            "Optional development checkpoint. "
            "Default runs the complete flow."
        ),
    )

    parser.add_argument(
        "--open",
        action="store_true",
        help=(
            "Open the validated final GDS in KLayout "
            "after successful completion."
        ),
    )

    args = parser.parse_args()

    if args.open and args.stop_after is not None:
        parser.error(
            "--open requires the complete flow; "
            "omit --stop-after"
        )

    # ========================================================
    # Product-policy gate
    # ========================================================

    policy = load_json(
        AUTOMATION_POLICY
    )

    require(
        policy.get("schema")
        == "accelclosure.automation_policy.v1",
        "automation policy schema mismatch",
    )

    max_iterations = int(
        policy[
            "execution"
        ][
            "maximum_closure_iterations"
        ]
    )

    if policy[
        "design_constraints"
    ][
        "clock_relaxation_allowed"
    ]:
        raise RuntimeError(
            "product policy unexpectedly "
            "allows clock relaxation"
        )

    # ========================================================
    # Create canonical unique run
    # ========================================================

    print()
    print(
        "============================================================"
    )
    print(
        " ACCELCLOSURE AUTONOMOUS RUN"
    )
    print(
        "============================================================"
    )
    print(
        "REQUEST="
        + args.request
    )

    context = build_context(
        args.request
    )

    run_context_path = initialize_run(
        context
    ).resolve()

    run_id = context[
        "run_id"
    ]

    run_dir = (
        ROOT
        / "results"
        / "runs"
        / run_id
    )

    artifacts_dir = (
        run_dir
        / "artifacts"
    )

    logs_dir = (
        artifacts_dir
        / "orchestrator_logs"
    )

    logs_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    events = EventLog(
        artifacts_dir
        / "orchestrator_events.jsonl"
    )

    events.emit(
        "run_context",
        "COMPLETED",
        {
            "run_id":
                run_id,

            "path":
                relative(
                    run_context_path
                ),

            "request":
                context[
                    "request"
                ],
        },
    )

    print(
        "RUN_ID="
        + run_id
    )
    print(
        "RUN_CONTEXT="
        + relative(
            run_context_path
        )
    )

    if checkpoint(
        args.stop_after,
        "context",
        run_id,
        run_context_path,
    ):
        return 0

    # ========================================================
    # Architecture reference selection
    # ========================================================

    contract_dir = (
        run_dir
        / "contract"
    )

    contract_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    architecture_refs = (
        contract_dir
        / "architecture_references.json"
    )

    stream_command(
        [
            sys.executable,
            ROOT
            / "src"
            / "reference_registry.py",
            "--run-context",
            run_context_path,
            "--purpose",
            "architecture",
            "--output",
            architecture_refs,
        ],
        "architecture_reference_selection",
        logs_dir,
        events,
    )

    # ========================================================
    # Design contract
    # ========================================================

    contract_path = (
        contract_dir
        / "design_contract.json"
    )

    golden_context_path = (
        contract_dir
        / "golden_context.json"
    )

    contract_raw_path = (
        contract_dir
        / "design_contract_raw.txt"
    )

    stream_command(
        [
            sys.executable,
            ROOT
            / "agents"
            / "design_contract_agent.py",
            "--request",
            args.request,
            "--output",
            contract_path,
            "--context-output",
            golden_context_path,
            "--raw-output",
            contract_raw_path,
        ],
        "design_contract",
        logs_dir,
        events,
    )

    require(
        contract_path.exists(),
        "design contract missing",
    )

    require(
        golden_context_path.exists(),
        "golden context missing",
    )

    # ========================================================
    # Contract validation
    # ========================================================

    validation_path = (
        contract_dir
        / "validation_report.json"
    )

    stream_command(
        [
            sys.executable,
            ROOT
            / "src"
            / "contract_validator.py",
            "--contract",
            contract_path,
            "--context",
            golden_context_path,
            "--output",
            validation_path,
        ],
        "contract_validation",
        logs_dir,
        events,
    )

    validation = load_json(
        validation_path
    )

    require(
        validation.get("status")
        == "VALID",
        "contract validation failed",
    )

    require(
        validation.get(
            "ready_for_rtl_generation"
        )
        is True,
        (
            "contract validator did not "
            "authorize RTL"
        ),
    )

    if checkpoint(
        args.stop_after,
        "contract",
        run_id,
        run_context_path,
    ):
        return 0

    # ========================================================
    # Initial RTL generation
    # ========================================================

    rtl_meta_dir = (
        run_dir
        / "rtl_meta"
    )

    rtl_dir = (
        run_dir
        / "rtl"
    )

    stream_command(
        [
            sys.executable,
            ROOT
            / "agents"
            / "rtl_generator_agent.py",
            "--contract",
            contract_path,
            "--context",
            golden_context_path,
            "--validation",
            validation_path,
            "--pipeline-policy",
            PIPELINE_POLICY,
            "--results-dir",
            rtl_meta_dir,
            "--rtl-dir",
            rtl_dir,
        ],
        "rtl_generation",
        logs_dir,
        events,
        iteration=0,
    )

    require(
        (
            rtl_dir
            / "accelclosure_ws_pe.sv"
        ).exists(),
        "generated PE RTL missing",
    )

    require(
        (
            rtl_dir
            / "accelclosure_ws_array.sv"
        ).exists(),
        "generated array RTL missing",
    )

    if checkpoint(
        args.stop_after,
        "rtl",
        run_id,
        run_context_path,
    ):
        return 0

    # ========================================================
    # Verification / EDA closure loop
    # ========================================================

    iteration = 0

    closure_reference_paths = []

    while True:

        # ----------------------------------------------------
        # Lint + functional verification.
        # Any failure here is FUNCTIONAL_RTL and must NOT be
        # sent to the timing-closure agent.
        # ----------------------------------------------------

        verification_rc = stream_command(
            [
                sys.executable,
                ROOT
                / "src"
                / "verification_stage.py",
                "--run-context",
                run_context_path,
                "--iteration",
                str(iteration),
            ],
            "verification",
            logs_dir,
            events,
            iteration=iteration,
        )

        require(
            verification_rc == 0,
            "functional verification failed",
        )

        if (
            args.stop_after
            == "verification"
        ):

            print(
                "ACCELCLOSURE_CHECKPOINT_REACHED"
            )
            print(
                "STAGE=verification"
            )
            print(
                f"ITERATION={iteration}"
            )
            print(
                f"RUN_ID={run_id}"
            )

            return 0

        # ----------------------------------------------------
        # Freeze exact implementation identity.
        # ----------------------------------------------------

        stream_command(
            [
                sys.executable,
                ROOT
                / "src"
                / "implementation_context.py",
                "--run-context",
                run_context_path,
                "--iteration",
                str(iteration),
            ],
            "implementation_context",
            logs_dir,
            events,
            iteration=iteration,
        )

        impl_ctx = (
            implementation_context_path(
                run_dir,
                iteration,
            )
        )

        require(
            impl_ctx.exists(),
            "implementation context missing",
        )

        # ----------------------------------------------------
        # Implementation-specific EDA config.
        # ----------------------------------------------------

        stream_command(
            [
                sys.executable,
                ROOT
                / "src"
                / "generate_implementation_eda_config.py",
                "--implementation-context",
                impl_ctx,
            ],
            "eda_config",
            logs_dir,
            events,
            iteration=iteration,
        )

        # ----------------------------------------------------
        # Synthesis + measured pre-layout STA.
        #
        # Return code 10 has one precise meaning:
        # measured timing target failure.
        # ----------------------------------------------------

        sta_rc = stream_command(
            [
                ROOT
                / "scripts"
                / "run_implementation_synth_sta.sh",
                impl_ctx,
            ],
            "synthesis_sta",
            logs_dir,
            events,
            iteration=iteration,
            allowed_returncodes={
                0,
                10,
            },
        )

        sta_path = sta_summary_path(
            run_dir,
            iteration,
        )

        require(
            sta_path.exists(),
            "STA summary missing",
        )

        sta = load_json(
            sta_path
        )

        measured_pass = (
            timing_target_met(
                sta
            )
        )

        if sta_rc == 0:

            require(
                measured_pass,
                (
                    "STA process returned PASS "
                    "but evidence says target failed"
                ),
            )

            events.emit(
                "timing_decision",
                "TARGET_MET",
                {
                    "iteration":
                        iteration,

                    "sta_summary":
                        relative(
                            sta_path
                        ),
                },
            )

            break

        # ----------------------------------------------------
        # rc=10: measured timing failure.
        # ----------------------------------------------------

        require(
            sta_rc == 10,
            "unexpected STA return code",
        )

        require(
            not measured_pass,
            (
                "STA returned timing failure "
                "but evidence says target met"
            ),
        )

        if (
            iteration
            >= max_iterations
        ):

            events.emit(
                "timing_closure",
                "MAX_ITERATIONS_REACHED",
                {
                    "iteration":
                        iteration,

                    "maximum":
                        max_iterations,
                },
            )

            print(
                "ACCELCLOSURE_CLOSURE_FAILED"
            )
            print(
                "REASON=MAX_CLOSURE_ITERATIONS"
            )

            return 10

        next_iteration = (
            iteration + 1
        )

        next_root = (
            run_dir
            / "closure"
            / f"iter{next_iteration}"
        )

        next_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        # ----------------------------------------------------
        # Retrieve CLOSED AccelClosure examples only.
        # ----------------------------------------------------

        closure_refs = (
            next_root
            / "reference_selection.json"
        )

        stream_command(
            [
                sys.executable,
                ROOT
                / "src"
                / "reference_registry.py",
                "--implementation-context",
                impl_ctx,
                "--purpose",
                "closure",
                "--output",
                closure_refs,
            ],
            "closure_reference_selection",
            logs_dir,
            events,
            iteration=next_iteration,
        )

        closure_reference_paths.append(
            relative(
                closure_refs
            )
        )

        # ----------------------------------------------------
        # Inject those references into the existing generic
        # timing-closure agent through its pipeline-policy
        # context. No PPA reuse is allowed.
        # ----------------------------------------------------

        closure_policy_context = (
            next_root
            / "closure_agent_policy_context.json"
        )

        make_closure_policy_context(
            closure_refs,
            closure_policy_context,
        )

        # ----------------------------------------------------
        # Timing-architecture redesign.
        # ----------------------------------------------------

        stream_command(
            [
                sys.executable,
                ROOT
                / "agents"
                / "timing_closure_agent.py",
                "--run-context",
                run_context_path,
                "--iteration",
                str(
                    next_iteration
                ),
                "--pipeline-policy",
                closure_policy_context,
            ],
            "timing_closure_agent",
            logs_dir,
            events,
            iteration=next_iteration,
        )

        events.emit(
            "timing_closure_agent",
            "REDESIGNED_UNVERIFIED",
            {
                "iteration":
                    next_iteration,

                "parent_iteration":
                    iteration,

                "target_clock_relaxed":
                    False,

                "closure_references":
                    relative(
                        closure_refs
                    ),
            },
        )

        iteration = (
            next_iteration
        )

    if (
        args.stop_after
        == "sta"
    ):

        print(
            "ACCELCLOSURE_CHECKPOINT_REACHED"
        )
        print(
            "STAGE=sta"
        )
        print(
            f"ITERATION={iteration}"
        )
        print(
            f"RUN_ID={run_id}"
        )

        return 0

    # ========================================================
    # Full physical design for the timing-closed implementation
    # ========================================================

    final_impl_ctx = (
        implementation_context_path(
            run_dir,
            iteration,
        )
    )

    physical_rc = stream_command(
        [
            ROOT
            / "scripts"
            / "run_implementation_physical.sh",
            final_impl_ctx,
        ],
        "physical_design",
        logs_dir,
        events,
        iteration=iteration,
        allowed_returncodes={
            0,
            20,
        },
    )

    physical_path = (
        physical_summary_path(
            run_dir,
            iteration,
        )
    )

    require(
        physical_path.exists(),
        "post-route physical summary missing",
    )

    physical = load_json(
        physical_path
    )

    if physical_rc != 0:

        events.emit(
            "physical_closure",
            "FAILED",
            {
                "returncode":
                    physical_rc,

                "summary":
                    relative(
                        physical_path
                    ),

                "status":
                    physical.get(
                        "status"
                    ),
            },
        )

        print(
            "ACCELCLOSURE_POST_ROUTE_FAILED"
        )
        print(
            "STATUS="
            + str(
                physical.get(
                    "status"
                )
            )
        )

        return physical_rc

    require(
        physical.get("status")
        == "POST_ROUTE_PHYSICALLY_CLOSED",
        (
            "physical runner returned success "
            "without closed evidence"
        ),
    )

    # ========================================================
    # Final product result
    # ========================================================

    final_result_path = (
        artifacts_dir
        / "product_result.json"
    )

    architecture_selection = (
        load_json(
            architecture_refs
        )
    )

    result = {
        "schema":
            "accelclosure.product_result.v1",

        "status":
            "EVIDENCE_COMPLETE",

        "run_id":
            run_id,

        "request":
            context["request"],

        "final_iteration":
            iteration,

        "final_implementation_context":
            relative(
                final_impl_ctx
            ),

        "architecture_reference_selection":
            relative(
                architecture_refs
            ),

        "architecture_references":
            [
                item[
                    "reference"
                ]["id"]

                for item in (
                    architecture_selection.get(
                        "selection",
                        [],
                    )
                )
            ],

        "closure_reference_selections":
            closure_reference_paths,

        "post_route_summary":
            relative(
                physical_path
            ),

        "post_route_status":
            physical[
                "status"
            ],

        "target": {
            "frequency_mhz":
                context[
                    "parameters"
                ][
                    "target_frequency_mhz"
                ],

            "period_ns":
                context[
                    "parameters"
                ][
                    "target_period_ns"
                ],

            "clock_relaxed":
                False,
        },

        "final_metrics": {
            "worst_setup_slack_ns":
                physical[
                    "timing"
                ][
                    "worst_setup_slack_ns"
                ],

            "fmax_estimate_mhz":
                physical[
                    "timing"
                ][
                    "fmax_estimate_mhz"
                ],

            "routed_cell_area_mm2":
                physical[
                    "area"
                ][
                    "routed_cell_area_mm2"
                ],

            "vectorless_power_w":
                (
                    physical.get(
                        "power"
                    )
                    or {}
                ).get(
                    "total_w"
                ),

            "route_drc_violations":
                physical[
                    "physical_checks"
                ][
                    "openroad_route_drc_violations"
                ],

            "antenna_net_violations":
                physical[
                    "physical_checks"
                ][
                    "antenna_net_violations"
                ],

            "antenna_pin_violations":
                physical[
                    "physical_checks"
                ][
                    "antenna_pin_violations"
                ],
        },

        "gds":
            physical[
                "artifacts"
            ][
                "gds"
            ],

        "claim_discipline": {
            "fmax_is_sta_estimate":
                True,

            "power_is_vectorless_estimate":
                (
                    physical.get(
                        "power"
                    )
                    is not None
                ),

            "openroad_route_drc_is_not_foundry_signoff":
                True,

            "gds_is_not_tapeout_signoff":
                True,

            "fresh_request_used_fresh_eda":
                True,

            "cross_configuration_ppa_reused":
                False,
        },

        "orchestrator_events":
            relative(
                events.path
            ),
    }

    write_json_exclusive(
        final_result_path,
        result,
    )

    events.emit(
        "run",
        "EVIDENCE_COMPLETE",
        {
            "final_iteration":
                iteration,

            "product_result":
                relative(
                    final_result_path
                ),

            "gds_sha256":
                physical[
                    "artifacts"
                ][
                    "gds"
                ][
                    "sha256"
                ],
        },
    )

    print()
    print(
        "============================================================"
    )
    print(
        " ACCELCLOSURE AUTONOMOUS RUN COMPLETE"
    )
    print(
        "============================================================"
    )
    print(
        "STATUS=EVIDENCE_COMPLETE"
    )
    print(
        "RUN_ID="
        + run_id
    )
    print(
        "FINAL_ITERATION="
        + str(iteration)
    )
    print(
        "POST_ROUTE_STATUS="
        + physical[
            "status"
        ]
    )
    print(
        "GDS_SHA256="
        + physical[
            "artifacts"
        ][
            "gds"
        ][
            "sha256"
        ]
    )
    print(
        "PRODUCT_RESULT="
        + relative(
            final_result_path
        )
    )

    if args.open:
        viewer = ROOT / "src" / "layout_viewer.py"

        viewer_result = subprocess.run(
            [
                sys.executable,
                str(viewer),
                "--product-result",
                str(final_result_path),
            ]
        )

        require(
            viewer_result.returncode == 0,
            "final layout viewer failed",
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )

    except KeyboardInterrupt:
        print(
            "\nACCELCLOSURE_INTERRUPTED"
        )
        raise SystemExit(130)

    except Exception as exc:
        print()
        print(
            "ACCELCLOSURE_AUTOMATION_STOPPED"
        )
        print(
            "REASON="
            + str(exc)
        )
        raise SystemExit(1)
