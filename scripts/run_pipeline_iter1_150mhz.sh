#!/usr/bin/env bash

set -u

ROOT="${ACCELCLOSURE_ROOT:-$HOME/CHIA_Hackathon/AccelClosure}"

ORFS_IMAGE="openroad/orfs@sha256:4886dd9c9723ea5539c2bfc1d6ceaf556f71f5827908c569523e430656ecec5c"

CONFIG="/workspace/AccelClosure/configs/orfs/sky130hd/iter0_150mhz/config.mk"

VARIANT="pipeline_iter1_150mhz"

HOST_RESULT="$ROOT/orfs_runs/results/sky130hd/accelclosure_ws_array/$VARIANT"

NETLIST="$HOST_RESULT/1_2_yosys.v"

ADAPTED="$ROOT/results/closure/pipeline_iter1/netlist_adapter/1_2_yosys_openroad_compatible.v"

BACKUP="$ROOT/results/closure/pipeline_iter1/netlist_adapter/1_2_yosys_original.v"

ADAPTER_REPORT="$ROOT/results/closure/pipeline_iter1/netlist_adapter/adapter_report.json"

echo "============================================================"
echo " ACCELCLOSURE PIPELINE ITERATION 1"
echo " Target: 150 MHz / 6.667 ns"
echo "============================================================"

cd "$ROOT"

run_synth() {
    docker run --rm \
      -v "$ROOT:/workspace/AccelClosure" \
      "$ORFS_IMAGE" \
      bash -lc "
        cd /OpenROAD-flow-scripts
        source ./env.sh
        cd flow

        make \
          DESIGN_CONFIG=$CONFIG \
          WORK_HOME=/workspace/AccelClosure/orfs_runs \
          FLOW_VARIANT=$VARIANT \
          synth
      "
}

echo
echo "[AccelClosure] Running Sky130 synthesis..."

set +e
run_synth
SYNTH_RC=$?
set -e

if [ "$SYNTH_RC" -ne 0 ]; then

    if [ ! -f "$NETLIST" ]; then
        echo "[AccelClosure] ERROR: synthesis failed before mapped netlist generation."
        exit "$SYNTH_RC"
    fi

    echo
    echo "[AccelClosure] Synthesized mapped netlist exists."
    echo "[AccelClosure] Checking known Yosys -> OpenROAD interoperability issue..."

    SIGNED_COUNT=$(
        grep -cE \
        '^[[:space:]]*(input|output|wire)[[:space:]]+signed[[:space:]]' \
        "$NETLIST" || true
    )

    echo "[AccelClosure] signed structural declarations = $SIGNED_COUNT"

    if [ "$SIGNED_COUNT" -gt 0 ]; then

        echo "[AccelClosure] Failure class: EDA_INTEROPERABILITY"
        echo "[AccelClosure] Applying artifact adapter automatically..."

        python "$ROOT/src/eda_artifact_adapter.py" \
          --source "$NETLIST" \
          --output "$ADAPTED" \
          --backup "$BACKUP" \
          --report "$ADAPTER_REPORT"

        docker run --rm \
          -v "$ROOT:/workspace/AccelClosure" \
          "$ORFS_IMAGE" \
          bash -lc "
            cp \
              /workspace/AccelClosure/results/closure/pipeline_iter1/netlist_adapter/1_2_yosys_openroad_compatible.v \
              /workspace/AccelClosure/orfs_runs/results/sky130hd/accelclosure_ws_array/$VARIANT/1_2_yosys.v
          "

        echo "[AccelClosure] Adapted netlist installed."
        echo "[AccelClosure] Resuming synthesis database generation..."

        run_synth

    else
        echo "[AccelClosure] ERROR: synthesis failed for an unknown reason."
        exit "$SYNTH_RC"
    fi
fi

ODB="$HOST_RESULT/1_synth.odb"

if [ ! -f "$ODB" ]; then
    echo "[AccelClosure] ERROR: 1_synth.odb was not produced."
    exit 1
fi

echo
echo "[AccelClosure] SYNTHESIS_ODB_PASS"
ls -lh "$ODB"

echo
echo "[AccelClosure] Pipeline Iteration 1 synthesis complete."
