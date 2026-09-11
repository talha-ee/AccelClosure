#!/usr/bin/env bash

set -euo pipefail


ROOT="${ACCELCLOSURE_ROOT:-$HOME/CHIA_Hackathon/AccelClosure}"

ORFS_IMAGE="openroad/orfs@sha256:4886dd9c9723ea5539c2bfc1d6ceaf556f71f5827908c569523e430656ecec5c"


usage() {
    echo "Usage:"
    echo "  $0 <implementation_context.json> [--preflight-only]"
}


if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    usage
    exit 2
fi


IMPL_INPUT="$1"
MODE="${2:-}"


if [ "$MODE" != "" ] && [ "$MODE" != "--preflight-only" ]; then
    usage
    exit 2
fi


if [[ "$IMPL_INPUT" = /* ]]; then
    IMPL_CTX="$IMPL_INPUT"
else
    IMPL_CTX="$ROOT/$IMPL_INPUT"
fi


if [ ! -f "$IMPL_CTX" ]; then
    echo "[AccelClosure] ERROR: implementation context missing:"
    echo "$IMPL_CTX"
    exit 1
fi


# ------------------------------------------------------------
# Load canonical implementation metadata exactly once.
# ------------------------------------------------------------

eval "$(
python - "$IMPL_CTX" <<'PY'
import json
import shlex
import sys

d = json.load(open(sys.argv[1]))
r = d["request"]
e = d["eda"]
v = d["implementation"]["verification"]

values = {
    "RUN_ID": d["run_id"],
    "IMPL_ID": d["implementation_id"],
    "ITERATION": str(d["iteration"]),
    "TECH": r["technology"],
    "N": str(r["n"]),
    "FREQ_MHZ": str(r["target_frequency_mhz"]),
    "PERIOD_NS": str(r["target_period_ns"]),
    "VARIANT": e["variant"],
    "CONFIG_DIR_REL": e["config_dir"],
    "EDA_DIR_REL": e["eda_dir"],
    "RESULTS_REL": e["results_dir"],
    "REPORTS_REL": e["reports_dir"],
    "PE_REL": d["implementation"]["rtl"]["pe"]["path"],
    "ARRAY_REL": d["implementation"]["rtl"]["array"]["path"],
    "PE_SHA": d["implementation"]["rtl"]["pe"]["sha256"],
    "ARRAY_SHA": d["implementation"]["rtl"]["array"]["sha256"],
}

for k, v in values.items():
    print(
        f"{k}={shlex.quote(v)}"
    )
PY
)"


CONFIG_HOST="$ROOT/$CONFIG_DIR_REL/config.mk"

EDA_DIR="$ROOT/$EDA_DIR_REL"
RESULT_DIR="$ROOT/$RESULTS_REL"

PE_HOST="$ROOT/$PE_REL"
ARRAY_HOST="$ROOT/$ARRAY_REL"

SYNTH_LOG="$EDA_DIR/synthesis.log"

NETLIST="$RESULT_DIR/1_2_yosys.v"
ODB="$RESULT_DIR/1_synth.odb"
SDC="$RESULT_DIR/1_synth.sdc"

ADAPTER_DIR="$EDA_DIR/netlist_adapter"

ADAPTED="$ADAPTER_DIR/1_2_yosys_openroad_compatible.v"
BACKUP="$ADAPTER_DIR/1_2_yosys_original.v"
ADAPTER_REPORT="$ADAPTER_DIR/adapter_report.json"

STA_DIR="$EDA_DIR/sta"

STA_TCL="$STA_DIR/prelayout_sta.tcl"
STA_LOG="$STA_DIR/prelayout_sta.log"
STA_SUMMARY="$STA_DIR/summary.json"

mkdir -p \
  "$EDA_DIR" \
  "$ADAPTER_DIR" \
  "$STA_DIR"


echo
echo "============================================================"
echo " ACCELCLOSURE IMPLEMENTATION EDA PREFLIGHT"
echo "============================================================"
echo " Run ID         : $RUN_ID"
echo " Implementation : $IMPL_ID"
echo " Iteration      : $ITERATION"
echo " Technology     : $TECH"
echo " Array          : ${N}x${N}"
echo " Target         : ${FREQ_MHZ} MHz"
echo " Period         : ${PERIOD_NS} ns"
echo " Variant        : $VARIANT"
echo "============================================================"


# ------------------------------------------------------------
# Product policy must itself be valid.
# ------------------------------------------------------------

cd "$ROOT"

python src/validate_automation_policy.py


# ------------------------------------------------------------
# Technology gate.
# ------------------------------------------------------------

if [ "$TECH" != "sky130hd" ]; then

    echo "[AccelClosure] ERROR:"
    echo "Current backend supports sky130hd only."

    exit 1
fi


# ------------------------------------------------------------
# Re-check exact RTL hashes NOW, not only when context was made.
# ------------------------------------------------------------

python - \
  "$PE_HOST" \
  "$ARRAY_HOST" \
  "$PE_SHA" \
  "$ARRAY_SHA" <<'PY'
import hashlib
import sys
from pathlib import Path


def sha(path):
    return hashlib.sha256(
        Path(path).read_bytes()
    ).hexdigest()


pe = sys.argv[1]
array = sys.argv[2]

expected_pe = sys.argv[3]
expected_array = sys.argv[4]

actual_pe = sha(pe)
actual_array = sha(array)

if actual_pe != expected_pe:
    raise SystemExit(
        "EDA_BLOCKED: PE RTL hash mismatch"
    )

if actual_array != expected_array:
    raise SystemExit(
        "EDA_BLOCKED: array RTL hash mismatch"
    )

print("VERIFIED_RTL_HASH_GATE=PASS")
print("PE_SHA256=" + actual_pe)
print("ARRAY_SHA256=" + actual_array)
PY


# ------------------------------------------------------------
# Strict lint evidence gate.
# ------------------------------------------------------------

python src/lint_evidence_gate.py \
  --implementation-context "$IMPL_CTX"


# ------------------------------------------------------------
# Ensure implementation-aware config exists.
#
# New implementations get generated automatically.
# Existing configurations are preserved.
# ------------------------------------------------------------

if [ ! -f "$CONFIG_HOST" ]; then

    echo
    echo "[AccelClosure] Generating implementation EDA config..."

    python src/generate_implementation_eda_config.py \
      --implementation-context "$IMPL_CTX"
fi


if [ ! -f "$CONFIG_HOST" ]; then
    echo "EDA_BLOCKED: implementation config missing."
    exit 1
fi


echo
echo "IMPLEMENTATION_EDA_CONFIG_GATE=PASS"
echo "CONFIG=$CONFIG_HOST"


if [ "$MODE" = "--preflight-only" ]; then

    echo
    echo "============================================================"
    echo " IMPLEMENTATION EDA PREFLIGHT PASS"
    echo "============================================================"

    exit 0
fi


CONFIG_CONTAINER="/workspace/AccelClosure/$CONFIG_DIR_REL/config.mk"


# ------------------------------------------------------------
# Synthesis helper
# ------------------------------------------------------------

run_synth() {

    docker run --rm \
      -v "$ROOT:/workspace/AccelClosure" \
      "$ORFS_IMAGE" \
      bash -lc "
        cd /OpenROAD-flow-scripts
        source ./env.sh
        cd flow

        make \
          DESIGN_CONFIG=$CONFIG_CONTAINER \
          WORK_HOME=/workspace/AccelClosure/orfs_runs \
          FLOW_VARIANT=$VARIANT \
          synth
      "
}


# ------------------------------------------------------------
# Run synthesis only when a valid synth DB does not yet exist.
# ------------------------------------------------------------

if [ ! -f "$ODB" ]; then

    echo
    echo "============================================================"
    echo " ACCELCLOSURE GENERIC SYNTHESIS"
    echo "============================================================"

    set +e

    run_synth \
      2>&1 \
      | tee "$SYNTH_LOG"

    SYNTH_RC=${PIPESTATUS[0]}

    set -e


    # --------------------------------------------------------
    # Known Yosys -> OpenROAD interoperability signature.
    #
    # Adapter requires BOTH:
    #   1. STA-0171 in execution log
    #   2. signed structural declarations
    #
    # It never modifies source RTL.
    # --------------------------------------------------------

    if [ "$SYNTH_RC" -ne 0 ]; then

        if [ ! -f "$NETLIST" ]; then

            echo
            echo "FAILURE_CLASS=UNKNOWN_EDA_SYNTHESIS"
            echo "Mapped netlist was not generated."

            exit "$SYNTH_RC"
        fi


        SIGNED_COUNT="$(
            grep -cE \
              '^[[:space:]]*(input|output|wire)[[:space:]]+signed[[:space:]]' \
              "$NETLIST" \
              || true
        )"


        if \
          grep -q "STA-0171" "$SYNTH_LOG" \
          && [ "$SIGNED_COUNT" -gt 0 ]; then

            echo
            echo "FAILURE_CLASS=EDA_INTEROPERABILITY"
            echo "KNOWN_SIGNATURE=YOSYS_SIGNED_STRUCTURAL_DECLARATIONS"
            echo "SIGNED_DECLARATIONS=$SIGNED_COUNT"




        if [ -f "$ADAPTED" ] || [ -f "$ADAPTER_REPORT" ] || [ -f "$BACKUP" ]; then

            echo
            echo "[AccelClosure] Existing adapter evidence detected."
            echo "[AccelClosure] Validating immutable adapter artifacts..."

            if [ ! -f "$ADAPTED" ]; then
                echo "EDA_ADAPTER_REUSE_GATE=FAIL"
                echo "REASON=adapted netlist missing"
                exit 1
            fi

            if [ ! -f "$ADAPTER_REPORT" ]; then
                echo "EDA_ADAPTER_REUSE_GATE=FAIL"
                echo "REASON=adapter report missing"
                exit 1
            fi

            CURRENT_SOURCE_SHA="$(
                sha256sum "$NETLIST" |
                awk '{print $1}'
            )"

            CURRENT_OUTPUT_SHA="$(
                sha256sum "$ADAPTED" |
                awk '{print $1}'
            )"

            RECORDED_SOURCE_SHA="$(
                python -c \
                  'import json,sys; print(json.load(open(sys.argv[1])).get("source_sha256",""))' \
                  "$ADAPTER_REPORT"
            )"

            RECORDED_OUTPUT_SHA="$(
                python -c \
                  'import json,sys; print(json.load(open(sys.argv[1])).get("output_sha256",""))' \
                  "$ADAPTER_REPORT"
            )"

            echo "CURRENT_SOURCE_SHA=$CURRENT_SOURCE_SHA"
            echo "RECORDED_SOURCE_SHA=$RECORDED_SOURCE_SHA"
            echo "CURRENT_OUTPUT_SHA=$CURRENT_OUTPUT_SHA"
            echo "RECORDED_OUTPUT_SHA=$RECORDED_OUTPUT_SHA"

            if [ "$CURRENT_SOURCE_SHA" != "$RECORDED_SOURCE_SHA" ]; then
                echo "EDA_ADAPTER_REUSE_GATE=FAIL"
                echo "REASON=current mapped netlist differs from recorded adapter source"
                exit 1
            fi

            if [ "$CURRENT_OUTPUT_SHA" != "$RECORDED_OUTPUT_SHA" ]; then
                echo "EDA_ADAPTER_REUSE_GATE=FAIL"
                echo "REASON=adapted netlist differs from recorded adapter output"
                exit 1
            fi

            echo "EDA_ADAPTER_REUSE_GATE=PASS"

        else

            python "$ROOT/src/eda_artifact_adapter.py" \
              --source "$NETLIST" \
              --output "$ADAPTED" \
              --backup "$BACKUP" \
              --report "$ADAPTER_REPORT"

            echo "EDA_ADAPTER_CREATED=PASS"

        fi


            docker run --rm \
              --user 0:0 \
              -v "$ROOT:/workspace/AccelClosure" \
              "$ORFS_IMAGE" \
              bash -lc "
                cp \
                  /workspace/AccelClosure/results/runs/$RUN_ID/eda/netlist_adapter/1_2_yosys_openroad_compatible.v \
                  /workspace/AccelClosure/orfs_runs/results/$TECH/accelclosure_ws_array/$RUN_ID/1_2_yosys.v
              "

            echo "EDA_ADAPTER_INSTALL=PASS"


            REMAINING="$(
                grep -cE \
                  '^[[:space:]]*(input|output|wire)[[:space:]]+signed[[:space:]]' \
                  "$NETLIST" \
                  || true
            )"


            if [ "$REMAINING" -ne 0 ]; then

                echo "EDA_ADAPTER_ERROR:"
                echo "signed declarations remain"

                exit 1
            fi


            echo "MAPPED_NETLIST_ADAPTER=PASS"
            echo "SOURCE_RTL_MODIFIED=false"


            echo
            echo "[AccelClosure] Resuming synthesis..."

            set +e

            run_synth \
              2>&1 \
              | tee -a "$SYNTH_LOG"

            SYNTH_RC=${PIPESTATUS[0]}

            set -e


            if [ "$SYNTH_RC" -ne 0 ]; then

                echo
                echo "FAILURE_CLASS=EDA_RUNTIME_OR_UNKNOWN"
                echo "Synthesis still failed after known adapter."

                exit "$SYNTH_RC"
            fi

        else

            echo
            echo "FAILURE_CLASS=UNKNOWN"
            echo "Automatic RTL modification is forbidden."
            echo "Automation stopped."

            exit "$SYNTH_RC"
        fi
    fi

else

    echo
    echo "SYNTHESIS_DATABASE_EXISTS=true"
    echo "SYNTHESIS_ACTION=REUSE_EXISTING_ARTIFACT"
fi


if [ ! -f "$ODB" ]; then

    echo "EDA_ERROR: 1_synth.odb not generated."

    exit 1
fi


if [ ! -f "$SDC" ]; then

    echo "EDA_ERROR: 1_synth.sdc not generated."

    exit 1
fi


echo
echo "SYNTHESIS_DATABASE=PASS"
ls -lh "$ODB"


# ------------------------------------------------------------
# Generate generic pre-layout STA script exactly once.
# ------------------------------------------------------------

if [ ! -f "$STA_TCL" ]; then

cat > "$STA_TCL" <<TCL
set design_name accelclosure_ws_array

set odb_file \
  /workspace/AccelClosure/$RESULTS_REL/1_synth.odb

set sdc_file \
  /workspace/AccelClosure/$RESULTS_REL/1_synth.sdc

set liberty_file \
  /OpenROAD-flow-scripts/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

puts "============================================================"
puts " ACCELCLOSURE IMPLEMENTATION PRE-LAYOUT STA"
puts "============================================================"

puts "RUN_ID=$RUN_ID"
puts "IMPLEMENTATION_ID=$IMPL_ID"
puts "ITERATION=$ITERATION"
puts "ARRAY_N=$N"
puts "TARGET_PERIOD_NS=$PERIOD_NS"
puts "TARGET_FREQUENCY_MHZ=$FREQ_MHZ"
puts "CORNER=sky130hd_tt_025C_1v80"

read_liberty \$liberty_file
read_db \$odb_file
read_sdc \$sdc_file

source \
  /OpenROAD-flow-scripts/flow/platforms/sky130hd/setRC.tcl

puts ""
puts "================ DESIGN AREA ================="
report_design_area

puts ""
puts "================ DATABASE INSTANCE COUNT ================="

set block [ord::get_db_block]
set inst_count [llength [\$block getInsts]]

puts "ACCELCLOSURE_INSTANCE_COUNT=\$inst_count"

puts ""
puts "================ CLOCK ================="
report_clock_properties

puts ""
puts "================ WORST SETUP SLACK ================="
report_worst_slack -max

puts ""
puts "================ WNS ================="
report_wns -max

puts ""
puts "================ TNS ================="
report_tns -max

puts ""
puts "================ WORST SETUP PATH ================="

report_checks \
  -path_delay max \
  -group_path_count 1 \
  -endpoint_path_count 1 \
  -sort_by_slack \
  -fields {slew capacitance input_pin net} \
  -digits 4

puts ""
puts "================ MINIMUM CLOCK PERIOD ================="
report_clock_min_period

puts ""
puts "ACCELCLOSURE_IMPLEMENTATION_STA_COMPLETE"
TCL

fi


# ------------------------------------------------------------
# Run STA unless a frozen summary already exists.
# ------------------------------------------------------------

if [ ! -f "$STA_SUMMARY" ]; then

    echo
    echo "============================================================"
    echo " ACCELCLOSURE GENERIC PRE-LAYOUT STA"
    echo "============================================================"

    set +e

    docker run --rm \
      -v "$ROOT:/workspace/AccelClosure" \
      "$ORFS_IMAGE" \
      bash -lc "
        cd /OpenROAD-flow-scripts
        source ./env.sh

        openroad \
          -exit \
          /workspace/AccelClosure/$EDA_DIR_REL/sta/prelayout_sta.tcl
      " \
      2>&1 \
      | tee "$STA_LOG"

    STA_RC=${PIPESTATUS[0]}

    set -e


    if [ "$STA_RC" -ne 0 ]; then

        echo
        echo "FAILURE_CLASS=EDA_RUNTIME"
        echo "Pre-layout STA execution failed."

        exit "$STA_RC"
    fi


    if ! grep -q \
      "ACCELCLOSURE_IMPLEMENTATION_STA_COMPLETE" \
      "$STA_LOG"; then

        echo
        echo "FAILURE_CLASS=EDA_RUNTIME"
        echo "STA completion marker missing."

        exit 1
    fi


    python "$ROOT/src/parse_prelayout_sta.py" \
      --implementation-context "$IMPL_CTX" \
      --log "$STA_LOG" \
      --output "$STA_SUMMARY"

else

    echo
    echo "PRELAYOUT_STA_SUMMARY_EXISTS=true"
    echo "STA_ACTION=REUSE_FROZEN_EVIDENCE"
fi


# ------------------------------------------------------------
# Final machine-readable branch result.
# Historical v1 and canonical v2 evidence both pass through
# the compatibility and measurement-consistency gate.
# ------------------------------------------------------------

set +e

python "$ROOT/src/sta_evidence_gate.py" \
  --summary "$STA_SUMMARY" \
  --implementation-context "$IMPL_CTX"

STA_EVIDENCE_RC=$?

set -e


if [ "$STA_EVIDENCE_RC" -eq 0 ]; then

    echo
    echo "============================================================"
    echo " ACCELCLOSURE SYNTHESIS + STA RESULT"
    echo "============================================================"
    echo "STATUS=POST_SYNTH_TIMING_CLOSED"
    echo "TARGET_MET=true"
    echo "NEXT_ACTION=PHYSICAL_DESIGN"
    echo "============================================================"

    exit 0
fi


if [ "$STA_EVIDENCE_RC" -eq 10 ]; then

    echo
    echo "============================================================"
    echo " ACCELCLOSURE SYNTHESIS + STA RESULT"
    echo "============================================================"
    echo "STATUS=TIMING_FAILED"
    echo "TARGET_MET=false"
    echo "NEXT_ACTION=TIMING_CLOSURE_AGENT"
    echo "============================================================"

    exit 10
fi


echo
echo "FAILURE_CLASS=EVIDENCE_ERROR"
echo "Automation stopped."

exit "$STA_EVIDENCE_RC"
