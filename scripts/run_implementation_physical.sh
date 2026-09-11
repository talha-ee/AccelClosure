#!/usr/bin/env bash

set -euo pipefail


ROOT="${ACCELCLOSURE_ROOT:-$HOME/CHIA_Hackathon/AccelClosure}"

ORFS_IMAGE="openroad/orfs@sha256:4886dd9c9723ea5539c2bfc1d6ceaf556f71f5827908c569523e430656ecec5c"


usage() {
    echo "Usage:"
    echo "  $0 <implementation_context.json> [--preflight-only|--adopt-existing]"
}


if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    usage
    exit 2
fi


IMPL_INPUT="$1"
MODE="${2:-}"


if \
  [ "$MODE" != "" ] \
  && [ "$MODE" != "--preflight-only" ] \
  && [ "$MODE" != "--adopt-existing" ]; then

    usage
    exit 2
fi


if [[ "$IMPL_INPUT" = /* ]]; then
    IMPL_CTX="$IMPL_INPUT"
else
    IMPL_CTX="$ROOT/$IMPL_INPUT"
fi


if [ ! -f "$IMPL_CTX" ]; then

    echo "PHYSICAL_ERROR: implementation context missing:"
    echo "$IMPL_CTX"

    exit 1
fi


eval "$(
python - "$IMPL_CTX" <<'PY'
import json
import shlex
import sys

d = json.load(open(sys.argv[1]))

r = d["request"]
e = d["eda"]

values = {
    "RUN_ID":
        d["run_id"],

    "IMPL_ID":
        d["implementation_id"],

    "ITERATION":
        str(d["iteration"]),

    "TECH":
        r["technology"],

    "N":
        str(r["n"]),

    "FREQ_MHZ":
        str(
            r["target_frequency_mhz"]
        ),

    "PERIOD_NS":
        str(
            r["target_period_ns"]
        ),

    "VARIANT":
        e["variant"],

    "CONFIG_DIR_REL":
        e["config_dir"],

    "EDA_DIR_REL":
        e["eda_dir"],

    "RESULTS_REL":
        e["results_dir"],

    "REPORTS_REL":
        e["reports_dir"],
}

for k, v in values.items():
    print(
        f"{k}={shlex.quote(v)}"
    )
PY
)"


EDA_DIR="$ROOT/$EDA_DIR_REL"

RESULT_DIR="$ROOT/$RESULTS_REL"

REPORT_DIR="$ROOT/$REPORTS_REL"

LOGS_REL="${REPORTS_REL/orfs_runs\/reports/orfs_runs\/logs}"
LOG_DIR="$ROOT/$LOGS_REL"

CONFIG_HOST="$ROOT/$CONFIG_DIR_REL/config.mk"

CONFIG_CONTAINER="/workspace/AccelClosure/$CONFIG_DIR_REL/config.mk"

STA_SUMMARY="$EDA_DIR/sta/summary.json"

PHYSICAL_DIR="$EDA_DIR/physical"

FINAL_DIR="$EDA_DIR/final"

mkdir -p \
  "$PHYSICAL_DIR" \
  "$FINAL_DIR"


FINAL_ODB="$RESULT_DIR/6_final.odb"
FINAL_GDS="$RESULT_DIR/6_final.gds"
FINAL_SDC="$RESULT_DIR/6_final.sdc"

FINISH_REPORT="$REPORT_DIR/6_finish.rpt"

# Final detailed-routing log is authoritative for
# detailed-route DRC and post-repair antenna status.
#
# Earlier routing iterations may legitimately contain
# violations; the final occurrence is the closure evidence.

DETAILED_ROUTE_LOG="$LOG_DIR/5_2_route.log"

ROUTE_COMBINED="$DETAILED_ROUTE_LOG"
ANTENNA_LOG="$DETAILED_ROUTE_LOG"

POWER_TCL="$FINAL_DIR/final_power.tcl"
POWER_LOG="$FINAL_DIR/final_power.log"

POSTROUTE_SUMMARY="$PHYSICAL_DIR/summary_v2.json"


echo
echo "============================================================"
echo " ACCELCLOSURE PHYSICAL-DESIGN PREFLIGHT"
echo "============================================================"
echo " Run ID         : $RUN_ID"
echo " Implementation : $IMPL_ID"
echo " Iteration      : $ITERATION"
echo " Array          : ${N}x${N}"
echo " Technology     : $TECH"
echo " Target         : ${FREQ_MHZ} MHz"
echo " Period         : ${PERIOD_NS} ns"
echo " Variant        : $VARIANT"
echo "============================================================"


cd "$ROOT"

python src/validate_automation_policy.py


if [ "$TECH" != "sky130hd" ]; then

    echo "PHYSICAL_BLOCKED:"
    echo "backend supports sky130hd only"

    exit 1
fi


if [ ! -f "$STA_SUMMARY" ]; then

    echo "PHYSICAL_BLOCKED:"
    echo "pre-layout STA summary missing"

    exit 1
fi


python "$ROOT/src/sta_evidence_gate.py" \
  --summary "$STA_SUMMARY" \
  --implementation-context "$IMPL_CTX" \
  --require-pass

echo "PRELAYOUT_TIMING_GATE=PASS"


if [ ! -f "$CONFIG_HOST" ]; then

    echo "PHYSICAL_BLOCKED:"
    echo "implementation config missing"

    exit 1
fi


echo "IMPLEMENTATION_CONFIG_GATE=PASS"


if [ "$MODE" = "--preflight-only" ]; then

    echo
    echo "============================================================"
    echo " PHYSICAL-DESIGN PREFLIGHT PASS"
    echo "============================================================"

    exit 0
fi


run_flow() {

    local config="$1"
    local log="$2"

    docker run --rm \
      -v "$ROOT:/workspace/AccelClosure" \
      "$ORFS_IMAGE" \
      bash -lc "
        cd /OpenROAD-flow-scripts
        source ./env.sh
        cd flow

        make \
          DESIGN_CONFIG=$config \
          WORK_HOME=/workspace/AccelClosure/orfs_runs \
          FLOW_VARIANT=$VARIANT
      " \
      2>&1 \
      | tee "$log"

    return "${PIPESTATUS[0]}"
}


known_cts_crash() {

    local log="$1"

    grep -q \
      'Error: cts.tcl.*child killed: illegal instruction' \
      "$log" \
    && \
    grep -q \
      'Created .* clock buffers' \
      "$log" \
    && \
    grep -q \
      'No setup violations found' \
      "$log" \
    && \
    grep -q \
      'No hold violations found' \
      "$log"
}


FINAL_EXISTS=false

if \
  [ -f "$FINAL_ODB" ] \
  && [ -f "$FINAL_GDS" ] \
  && [ -f "$FINAL_SDC" ] \
  && [ -f "$FINISH_REPORT" ]; then

    FINAL_EXISTS=true
fi


if [ "$MODE" = "--adopt-existing" ]; then

    if [ "$FINAL_EXISTS" != "true" ]; then

        echo "PHYSICAL_ADOPTION_ERROR:"
        echo "complete final artifacts are not present"

        exit 1
    fi

    echo
    echo "PHYSICAL_ACTION=ADOPT_EXISTING_FINAL_ARTIFACTS"

elif [ "$FINAL_EXISTS" = "true" ]; then

    echo
    echo "PHYSICAL_ACTION=REUSE_EXISTING_FINAL_ARTIFACTS"

else

    echo
    echo "============================================================"
    echo " ACCELCLOSURE FULL PHYSICAL IMPLEMENTATION"
    echo "============================================================"

    ATTEMPT1="$PHYSICAL_DIR/flow_attempt1.log"

    set +e

    run_flow \
      "$CONFIG_CONTAINER" \
      "$ATTEMPT1"

    RC1=$?

    set -e


    if [ "$RC1" -ne 0 ]; then

        if ! known_cts_crash "$ATTEMPT1"; then

            echo
            echo "FAILURE_CLASS=UNKNOWN_EDA_RUNTIME"
            echo "Automatic RTL modification forbidden."
            echo "Automation stopped."

            exit "$RC1"
        fi


        echo
        echo "FAILURE_CLASS=EDA_RUNTIME"
        echo "KNOWN_SIGNATURE=CTS_ILLEGAL_INSTRUCTION"
        echo "ACTION=RETRY_ORIGINAL_FLOW_ONCE"


        ATTEMPT2="$PHYSICAL_DIR/flow_attempt2.log"

        set +e

        run_flow \
          "$CONFIG_CONTAINER" \
          "$ATTEMPT2"

        RC2=$?

        set -e


        if [ "$RC2" -ne 0 ]; then

            if ! known_cts_crash "$ATTEMPT2"; then

                echo
                echo "FAILURE_CLASS=UNKNOWN_EDA_RUNTIME"
                echo "Second failure does not match known CTS signature."
                echo "Automation stopped."

                exit "$RC2"
            fi


            echo
            echo "KNOWN_CTS_RUNTIME_FAILURE_REPEATED=true"
            echo "ACTION=APPLY_RECORDED_CTS_RUNTIME_WORKAROUND"


            RECOVERY_CONFIG_HOST="$CONFIG_DIR_REL/runtime_cts_recovery.mk"

            RECOVERY_CONFIG="$ROOT/$RECOVERY_CONFIG_HOST"

            RECOVERY_CONFIG_CONTAINER="/workspace/AccelClosure/$RECOVERY_CONFIG_HOST"


            EXPECTED_RECOVERY="$(
cat <<EOF
include /workspace/AccelClosure/$CONFIG_DIR_REL/config.mk

# AccelClosure recorded EDA runtime recovery.
# Does not relax requested clock.
export SKIP_CTS_REPAIR_TIMING = 1
EOF
)"


            if [ -f "$RECOVERY_CONFIG" ]; then

                ACTUAL="$(
                    cat "$RECOVERY_CONFIG"
                )"

                if [ "$ACTUAL" != "$EXPECTED_RECOVERY" ]; then

                    echo "CTS_RECOVERY_ERROR:"
                    echo "existing recovery config differs"

                    exit 1
                fi

            else

                printf '%s\n' \
                  "$EXPECTED_RECOVERY" \
                  > "$RECOVERY_CONFIG"
            fi


            python - \
              "$RUN_ID" \
              "$IMPL_ID" \
              "$FREQ_MHZ" \
              "$PERIOD_NS" \
              "$PHYSICAL_DIR/cts_runtime_recovery.json" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[5])

if out.exists():
    raise SystemExit(
        "CTS_RECOVERY_ERROR: "
        "provenance already exists"
    )

record = {
    "schema":
        "accelclosure.cts_runtime_recovery.v1",

    "timestamp_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "run_id":
        sys.argv[1],

    "implementation_id":
        sys.argv[2],

    "target_frequency_mhz":
        float(sys.argv[3]),

    "target_period_ns":
        float(sys.argv[4]),

    "failure_class":
        "EDA_RUNTIME",

    "signature":
        "cts.tcl child killed: illegal instruction",

    "original_retry_count":
        1,

    "workaround":
        "SKIP_CTS_REPAIR_TIMING=1",

    "clock_target_relaxed":
        False,

    "source_rtl_modified":
        False,

    "post_route_setup_revalidation_required":
        True,

    "post_route_hold_revalidation_required":
        True,
}

out.write_text(
    json.dumps(
        record,
        indent=2
    )
    + "\n"
)

print(
    "CTS_RUNTIME_RECOVERY_PROVENANCE_RECORDED"
)
PY


            ATTEMPT3="$PHYSICAL_DIR/flow_attempt3_recovery.log"

            set +e

            run_flow \
              "$RECOVERY_CONFIG_CONTAINER" \
              "$ATTEMPT3"

            RC3=$?

            set -e


            if [ "$RC3" -ne 0 ]; then

                echo
                echo "FAILURE_CLASS=EDA_RUNTIME_OR_UNKNOWN"
                echo "Physical flow failed after CTS recovery."
                echo "Automation stopped."

                exit "$RC3"
            fi
        fi
    fi
fi


# ------------------------------------------------------------
# Final artifact gate.
# ------------------------------------------------------------

for file in \
  "$FINAL_ODB" \
  "$FINAL_GDS" \
  "$FINAL_SDC" \
  "$FINISH_REPORT"
do

    if [ ! -f "$file" ]; then

        echo "PHYSICAL_ERROR:"
        echo "required final artifact missing:"
        echo "$file"

        exit 1
    fi
done


echo
echo "FINAL_PHYSICAL_ARTIFACT_GATE=PASS"


# ------------------------------------------------------------
# Authoritative final detailed-route evidence.
#
# The route log contains several optimization iterations.
# Only the last reported DRT and antenna values represent the
# final repaired routed database.
# ------------------------------------------------------------

if [ ! -s "$DETAILED_ROUTE_LOG" ]; then

    echo "PHYSICAL_ERROR:"
    echo "final detailed-route log unavailable:"
    echo "$DETAILED_ROUTE_LOG"

    exit 1
fi


if ! grep -q   'Number of violations'   "$DETAILED_ROUTE_LOG"; then

    echo "PHYSICAL_ERROR:"
    echo "detailed-route DRC evidence missing"

    exit 1
fi


if ! grep -q   'net violations'   "$DETAILED_ROUTE_LOG"; then

    echo "PHYSICAL_ERROR:"
    echo "final antenna net evidence missing"

    exit 1
fi


if ! grep -q   'pin violations'   "$DETAILED_ROUTE_LOG"; then

    echo "PHYSICAL_ERROR:"
    echo "final antenna pin evidence missing"

    exit 1
fi


echo "FINAL_DETAILED_ROUTE_EVIDENCE_GATE=PASS"


# ------------------------------------------------------------
# Vectorless final power analysis.
# Official timing still comes from ORFS 6_finish.rpt.
# ------------------------------------------------------------

if [ ! -f "$POWER_LOG" ]; then

cat > "$POWER_TCL" <<TCL
set odb_file \
  /workspace/AccelClosure/$RESULTS_REL/6_final.odb

set sdc_file \
  /workspace/AccelClosure/$RESULTS_REL/6_final.sdc

set liberty_file \
  /OpenROAD-flow-scripts/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

read_liberty \$liberty_file
read_db \$odb_file
read_sdc \$sdc_file

source \
  /OpenROAD-flow-scripts/flow/platforms/sky130hd/setRC.tcl

puts ""
puts "================ FINAL AREA ================="
report_design_area

puts ""
puts "================ FINAL POWER ================="
report_power

puts ""
puts "ACCELCLOSURE_FINAL_POWER_COMPLETE"
TCL


    docker run --rm \
      -v "$ROOT:/workspace/AccelClosure" \
      "$ORFS_IMAGE" \
      bash -lc "
        cd /OpenROAD-flow-scripts
        source ./env.sh

        openroad \
          -exit \
          /workspace/AccelClosure/$EDA_DIR_REL/final/final_power.tcl
      " \
      2>&1 \
      | tee "$POWER_LOG"


    if ! grep -q \
      "ACCELCLOSURE_FINAL_POWER_COMPLETE" \
      "$POWER_LOG"; then

        echo "POWER_ANALYSIS_ERROR:"
        echo "completion marker missing"

        exit 1
    fi
fi


echo "FINAL_VECTORLESS_POWER_ANALYSIS=PASS"


# ------------------------------------------------------------
# Parse immutable final physical evidence.
# ------------------------------------------------------------

if [ ! -f "$POSTROUTE_SUMMARY" ]; then

    python src/parse_postroute_results.py \
      --implementation-context "$IMPL_CTX" \
      --finish-report "$FINISH_REPORT" \
      --route-evidence "$ROUTE_COMBINED" \
      --antenna-log "$ANTENNA_LOG" \
      --gds "$FINAL_GDS" \
      --odb "$FINAL_ODB" \
      --sdc "$FINAL_SDC" \
      --power-log "$POWER_LOG" \
      --output "$POSTROUTE_SUMMARY"

else

    echo "POSTROUTE_SUMMARY_ACTION=REUSE_FROZEN_EVIDENCE"
fi


python - "$POSTROUTE_SUMMARY" <<'PY'
import json
import sys

d = json.load(open(sys.argv[1]))

print()
print("============================================================")
print(" ACCELCLOSURE FINAL PHYSICAL RESULT")
print("============================================================")
print("STATUS=" + d["status"])

t = d["timing"]

print(
    "TARGET_MET="
    + str(
        t["target_met"]
    ).lower()
)

print(
    "WORST_SETUP_SLACK_NS="
    + str(
        t["worst_setup_slack_ns"]
    )
)

print(
    "FMAX_ESTIMATE_MHZ="
    + str(
        t["fmax_estimate_mhz"]
    )
)

print(
    "SETUP_VIOLATIONS="
    + str(
        t["setup_violation_count"]
    )
)

print(
    "HOLD_VIOLATIONS="
    + str(
        t["hold_violation_count"]
    )
)

print(
    "ROUTED_AREA_MM2="
    + str(
        d["area"][
            "routed_cell_area_mm2"
        ]
    )
)

p = d.get("power")

if p:

    print(
        "VECTORLESS_POWER_W="
        + str(
            p["total_w"]
        )
    )

print(
    "ROUTE_DRC_VIOLATIONS="
    + str(
        d["physical_checks"][
            "openroad_route_drc_violations"
        ]
    )
)

print(
    "ANTENNA_NET_VIOLATIONS="
    + str(
        d["physical_checks"][
            "antenna_net_violations"
        ]
    )
)

print(
    "ANTENNA_PIN_VIOLATIONS="
    + str(
        d["physical_checks"][
            "antenna_pin_violations"
        ]
    )
)

print(
    "GDS_SHA256="
    + d["artifacts"]["gds"]["sha256"]
)

print("============================================================")

if d["status"] != "POST_ROUTE_PHYSICALLY_CLOSED":
    raise SystemExit(20)
PY
