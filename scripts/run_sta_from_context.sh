#!/usr/bin/env bash

set -euo pipefail

ROOT="${ACCELCLOSURE_ROOT:-$HOME/CHIA_Hackathon/AccelClosure}"

ORFS_IMAGE="openroad/orfs@sha256:4886dd9c9723ea5539c2bfc1d6ceaf556f71f5827908c569523e430656ecec5c"

if [ "$#" -ne 1 ]; then
    echo "Usage:"
    echo "  $0 <run_context.json>"
    exit 2
fi

RUN_CTX_INPUT="$1"

if [[ "$RUN_CTX_INPUT" = /* ]]; then
    RUN_CTX="$RUN_CTX_INPUT"
else
    RUN_CTX="$ROOT/$RUN_CTX_INPUT"
fi

if [ ! -f "$RUN_CTX" ]; then
    echo "[AccelClosure] ERROR: run context not found:"
    echo "$RUN_CTX"
    exit 1
fi


# ------------------------------------------------------------
# Canonical run metadata
# ------------------------------------------------------------

RUN_ID="$(
python - "$RUN_CTX" <<'PY'
import json
import sys

ctx = json.load(open(sys.argv[1]))
print(ctx["run_id"])
PY
)"

TECH="$(
python - "$RUN_CTX" <<'PY'
import json
import sys

ctx = json.load(open(sys.argv[1]))
print(ctx["parameters"]["technology"])
PY
)"

N="$(
python - "$RUN_CTX" <<'PY'
import json
import sys

ctx = json.load(open(sys.argv[1]))
print(ctx["parameters"]["n"])
PY
)"

FREQ_MHZ="$(
python - "$RUN_CTX" <<'PY'
import json
import sys

ctx = json.load(open(sys.argv[1]))
print(ctx["parameters"]["target_frequency_mhz"])
PY
)"

PERIOD_NS="$(
python - "$RUN_CTX" <<'PY'
import json
import sys

ctx = json.load(open(sys.argv[1]))
print(ctx["parameters"]["target_period_ns"])
PY
)"


if [ "$TECH" != "sky130hd" ]; then
    echo "[AccelClosure] ERROR:"
    echo "STA backend currently supports sky130hd only."
    exit 1
fi


# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------

RUN_DIR="$ROOT/results/runs/$RUN_ID"

SYNTH_HOST="$ROOT/orfs_runs/results/$TECH/accelclosure_ws_array/$RUN_ID"

ODB_HOST="$SYNTH_HOST/1_synth.odb"
SDC_HOST="$SYNTH_HOST/1_synth.sdc"

ODB_CONTAINER="/workspace/AccelClosure/orfs_runs/results/$TECH/accelclosure_ws_array/$RUN_ID/1_synth.odb"
SDC_CONTAINER="/workspace/AccelClosure/orfs_runs/results/$TECH/accelclosure_ws_array/$RUN_ID/1_synth.sdc"

STA_DIR="$RUN_DIR/eda/sta"

TCL_HOST="$STA_DIR/prelayout_sta.tcl"
LOG_HOST="$STA_DIR/prelayout_sta.log"

mkdir -p "$STA_DIR"


# ------------------------------------------------------------
# Preconditions
# ------------------------------------------------------------

if [ ! -f "$ODB_HOST" ]; then
    echo "[AccelClosure] ERROR: synthesis ODB missing."
    exit 1
fi

if [ ! -f "$SDC_HOST" ]; then
    echo "[AccelClosure] ERROR: synthesis SDC missing."
    exit 1
fi


echo "============================================================"
echo " ACCELCLOSURE RUN-LOCAL PRE-LAYOUT STA"
echo "============================================================"
echo " Run ID      : $RUN_ID"
echo " Technology  : $TECH"
echo " Array       : ${N}x${N}"
echo " Target      : ${FREQ_MHZ} MHz"
echo " Period      : ${PERIOD_NS} ns"
echo " Corner      : sky130hd_tt_025C_1v80"
echo "============================================================"


# ------------------------------------------------------------
# Generate STA Tcl using same methodology as reference run
# ------------------------------------------------------------

cat > "$TCL_HOST" <<TCL
set design_name accelclosure_ws_array

set odb_file \
  $ODB_CONTAINER

set sdc_file \
  $SDC_CONTAINER

set liberty_file \
  /OpenROAD-flow-scripts/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

puts "============================================================"
puts " ACCELCLOSURE RUN-LOCAL PRE-LAYOUT STA"
puts "============================================================"

puts "DESIGN_NAME=\$design_name"
puts "RUN_ID=$RUN_ID"
puts "ARRAY_N=$N"
puts "TARGET_PERIOD_NS=$PERIOD_NS"
puts "TARGET_FREQUENCY_MHZ=$FREQ_MHZ"
puts "CORNER=sky130hd_tt_025C_1v80"

read_liberty \$liberty_file
read_db \$odb_file
read_sdc \$sdc_file

source /OpenROAD-flow-scripts/flow/platforms/sky130hd/setRC.tcl

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
puts "ACCELCLOSURE_RUNLOCAL_STA_COMPLETE"
TCL


echo
echo "[AccelClosure] STA Tcl:"
echo "$TCL_HOST"

echo
echo "[AccelClosure] Starting OpenROAD STA..."

set +e

docker run --rm \
  -v "$ROOT:/workspace/AccelClosure" \
  "$ORFS_IMAGE" \
  bash -lc "
    cd /OpenROAD-flow-scripts
    source ./env.sh

    openroad \
      -exit \
      /workspace/AccelClosure/results/runs/$RUN_ID/eda/sta/prelayout_sta.tcl
  " \
  2>&1 | tee "$LOG_HOST"

STA_RC=${PIPESTATUS[0]}

set -e


if [ "$STA_RC" -ne 0 ]; then
    echo
    echo "[AccelClosure] STA execution FAILED."
    echo "[AccelClosure] Log:"
    echo "$LOG_HOST"
    exit "$STA_RC"
fi


if ! grep -q \
  "ACCELCLOSURE_RUNLOCAL_STA_COMPLETE" \
  "$LOG_HOST"; then

    echo
    echo "[AccelClosure] ERROR:"
    echo "STA completion marker missing."

    exit 1
fi


echo
echo "============================================================"
echo " ACCELCLOSURE STA EXECUTION PASS"
echo "============================================================"

echo
echo "[AccelClosure] STA log:"
echo "$LOG_HOST"
