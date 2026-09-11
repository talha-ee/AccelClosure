#!/usr/bin/env python3

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def load_json(path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def artifact(path):
    if not path.exists():
        return {
            "path": str(path),
            "exists": False
        }

    return {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path)
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run-context",
        required=True
    )

    args = parser.parse_args()

    run_context_path = Path(args.run_context).resolve()

    if not run_context_path.exists():
        raise SystemExit(
            f"Run context not found: {run_context_path}"
        )

    run_dir = run_context_path.parent
    run_id = run_dir.name

    iter0_verification = (
        run_dir
        / "verification"
        / "summary.json"
    )

    iter0_sta = (
        run_dir
        / "eda"
        / "sta"
        / "summary.json"
    )

    iter1_verification = (
        run_dir
        / "closure"
        / "iter1"
        / "verification"
        / "summary.json"
    )

    iter1_sta = (
        run_dir
        / "closure"
        / "iter1"
        / "eda"
        / "sta"
        / "summary.json"
    )

    iter1_final = (
        run_dir
        / "closure"
        / "iter1"
        / "final"
        / "summary.json"
    )

    improvement = (
        run_dir
        / "closure"
        / "closure_improvement.json"
    )

    closure_report = (
        run_dir
        / "closure"
        / "iter1"
        / "report.json"
    )

    policy = (
        Path("configs/product/pipeline_policy.json")
        .resolve()
    )

    iter0_pe = run_dir / "rtl" / "accelclosure_ws_pe.sv"
    iter0_array = run_dir / "rtl" / "accelclosure_ws_array.sv"

    iter1_pe = (
        run_dir
        / "closure"
        / "iter1"
        / "rtl"
        / "accelclosure_ws_pe.sv"
    )

    iter1_array = (
        run_dir
        / "closure"
        / "iter1"
        / "rtl"
        / "accelclosure_ws_array.sv"
    )

    orfs_result_dir = (
        Path("orfs_runs")
        / "results"
        / "sky130hd"
        / "accelclosure_ws_array"
        / f"{run_id}_closure_iter1"
    ).resolve()

    final_odb = orfs_result_dir / "6_final.odb"
    final_gds = orfs_result_dir / "6_final.gds"
    final_sdc = orfs_result_dir / "6_final.sdc"

    required = [
        run_context_path,
        iter0_verification,
        iter0_sta,
        iter1_verification,
        iter1_sta,
        iter1_final,
        improvement,
        iter0_pe,
        iter0_array,
        iter1_pe,
        iter1_array,
        final_odb,
        final_gds,
        final_sdc
    ]

    missing = [
        str(p)
        for p in required
        if not p.exists()
    ]

    final_summary = load_json(iter1_final)
    comparison = load_json(improvement)

    record = {
        "schema": "accelclosure.run_record.v1",

        "generated_utc":
            datetime.now(timezone.utc).isoformat(),

        "run_id": run_id,

        "status": (
            "EVIDENCE_COMPLETE"
            if not missing
            else "EVIDENCE_INCOMPLETE"
        ),

        "run_context":
            load_json(run_context_path),

        "closure": {
            "iteration_0_verification":
                load_json(iter0_verification),

            "iteration_0_sta":
                load_json(iter0_sta),

            "iteration_1_agent_report":
                load_json(closure_report),

            "iteration_1_verification":
                load_json(iter1_verification),

            "iteration_1_sta":
                load_json(iter1_sta),

            "final":
                final_summary,

            "improvement":
                comparison
        },

        "provenance": {
            "pipeline_policy":
                artifact(policy),

            "iteration_0_rtl": {
                "pe": artifact(iter0_pe),
                "array": artifact(iter0_array)
            },

            "iteration_1_rtl": {
                "pe": artifact(iter1_pe),
                "array": artifact(iter1_array)
            },

            "final_physical_artifacts": {
                "odb": artifact(final_odb),
                "gds": artifact(final_gds),
                "sdc": artifact(final_sdc)
            },

            "orfs_image":
                "openroad/orfs@sha256:"
                "4886dd9c9723ea5539c2bfc1d6ceaf556f71f5827908c569523e430656ecec5c"
        },

        "evidence_integrity": {
            "required_artifact_count":
                len(required),

            "missing_artifact_count":
                len(missing),

            "missing_artifacts":
                missing
        },

        "claim_status": {
            "functional_verified":
                bool(
                    final_summary
                    and final_summary["closure"][
                        "functional_verified"
                    ]
                ),

            "post_route_timing_closed":
                bool(
                    final_summary
                    and final_summary["closure"][
                        "post_route_timing_closed"
                    ]
                ),

            "gds_generated":
                bool(
                    final_summary
                    and final_summary["closure"][
                        "gds_generated"
                    ]
                ),

            "clock_target_relaxed":
                (
                    comparison["closure_result"][
                        "clock_target_relaxed"
                    ]
                    if comparison
                    else None
                ),

            "foundry_signoff_completed":
                False
        }
    }

    out_dir = run_dir / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)

    out = out_dir / "run_record.json"

    out.write_text(
        json.dumps(record, indent=2) + "\n"
    )

    print("ACCELCLOSURE_RUN_RECORD_BUILT")
    print("RUN_ID=" + run_id)
    print("STATUS=" + record["status"])
    print(
        "MISSING_ARTIFACTS="
        + str(len(missing))
    )

    if missing:
        for item in missing:
            print("MISSING:", item)
        raise SystemExit(1)

    print(
        "POST_ROUTE_TIMING_CLOSED="
        + str(
            record["claim_status"][
                "post_route_timing_closed"
            ]
        ).lower()
    )

    print(
        "GDS_GENERATED="
        + str(
            record["claim_status"][
                "gds_generated"
            ]
        ).lower()
    )


if __name__ == "__main__":
    main()
