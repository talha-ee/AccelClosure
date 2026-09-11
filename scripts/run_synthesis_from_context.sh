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
# Read canonical run metadata.
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

CONFIG_REL="$(
python - "$RUN_CTX" <<'PY'
import json
import sys

ctx = json.load(open(sys.argv[1]))
print(ctx["paths"]["config_dir"] + "/config.mk")
PY
)"

RTL_DIR_REL="$(
python - "$RUN_CTX" <<'PY'
import json
import sys

ctx = json.load(open(sys.argv[1]))
print(ctx["paths"]["rtl_dir"])
PY
)"


if [ "$TECH" != "sky130hd" ]; then
    echo "[AccelClosure] ERROR:"
    echo "Current ORFS backend supports sky130hd only."
    exit 1
fi


RUN_DIR="$ROOT/results/runs/$RUN_ID"

CONFIG_HOST="$ROOT/$CONFIG_REL"
CONFIG_CONTAINER="/workspace/AccelClosure/$CONFIG_REL"

RTL_DIR="$ROOT/$RTL_DIR_REL"

VERIFICATION_SUMMARY="$RUN_DIR/verification/summary.json"

HOST_RESULT="$ROOT/orfs_runs/results/$TECH/accelclosure_ws_array/$RUN_ID"

NETLIST="$HOST_RESULT/1_2_yosys.v"
ODB="$HOST_RESULT/1_synth.odb"

EDA_DIR="$RUN_DIR/eda"
ADAPTER_DIR="$EDA_DIR/netlist_adapter"

ADAPTED="$ADAPTER_DIR/1_2_yosys_openroad_compatible.v"
BACKUP="$ADAPTER_DIR/1_2_yosys_original.v"
ADAPTER_REPORT="$ADAPTER_DIR/adapter_report.json"

mkdir -p \
    "$EDA_DIR" \
    "$ADAPTER_DIR"


# ------------------------------------------------------------
# Preflight checks.
# ------------------------------------------------------------

if [ ! -f "$CONFIG_HOST" ]; then
    echo "[AccelClosure] ERROR: generated config missing:"
    echo "$CONFIG_HOST"
    exit 1
fi

if [ ! -f "$RTL_DIR/accelclosure_ws_pe.sv" ]; then
    echo "[AccelClosure] ERROR: PE RTL missing."
    exit 1
fi

if [ ! -f "$RTL_DIR/accelclosure_ws_array.sv" ]; then
    echo "[AccelClosure] ERROR: array RTL missing."
    exit 1
fi

if [ ! -f "$VERIFICATION_SUMMARY" ]; then
    echo "[AccelClosure] ERROR:"
    echo "Functional verification summary missing."
    echo "EDA execution blocked."
    exit 1
fi


# ------------------------------------------------------------
# Critical provenance gate:
# synthesize exactly the functionally verified RTL.
# ------------------------------------------------------------

python - \
    "$VERIFICATION_SUMMARY" \
    "$RTL_DIR/accelclosure_ws_pe.sv" \
    "$RTL_DIR/accelclosure_ws_array.sv" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
pe = Path(sys.argv[2])
array = Path(sys.argv[3])

summary = json.loads(
    summary_path.read_text()
)

if summary.get("status") != "FUNCTIONALLY_VERIFIED":
    raise SystemExit(
        "EDA_BLOCKED: design is not FUNCTIONALLY_VERIFIED"
    )


def sha(path):
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


actual_pe = sha(pe)
actual_array = sha(array)

expected_pe = summary["rtl"]["pe_sha256"]
expected_array = summary["rtl"]["array_sha256"]

if actual_pe != expected_pe:
    raise SystemExit(
        "EDA_BLOCKED: PE RTL changed after verification"
    )

if actual_array != expected_array:
    raise SystemExit(
        "EDA_BLOCKED: array RTL changed after verification"
    )

print("VERIFIED_RTL_HASH_GATE=PASS")
print("PE_SHA256=" + actual_pe)
print("ARRAY_SHA256=" + actual_array)
PY


echo
echo "============================================================"
echo " ACCELCLOSURE RUN-LOCAL SYNTHESIS"
echo "============================================================"
echo " Run ID      : $RUN_ID"
echo " Technology  : $TECH"
echo " Array       : ${N}x${N}"
echo " Target      : ${FREQ_MHZ} MHz"
echo " Period      : ${PERIOD_NS} ns"
echo " Variant     : $RUN_ID"
echo " Config      : $CONFIG_REL"
echo "============================================================"


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
          FLOW_VARIANT=$RUN_ID \
          synth
      "
}


echo
echo "[AccelClosure] Running Sky130 synthesis..."

set +e
run_synth
SYNTH_RC=$?
set -e


# ------------------------------------------------------------
# Handle known Yosys -> OpenROAD structural syntax issue.
# This is EDA interoperability, not an RTL repair.
# ------------------------------------------------------------

if [ "$SYNTH_RC" -ne 0 ]; then

    if [ ! -f "$NETLIST" ]; then

        echo
        echo "[AccelClosure] ERROR:"
        echo "Synthesis failed before mapped netlist generation."

        exit "$SYNTH_RC"
    fi

    echo
    echo "[AccelClosure] Mapped netlist exists."
    echo "[AccelClosure] Checking known structural-netlist"
    echo "               interoperability condition..."

    SIGNED_COUNT="$(
        grep -cE \
        '^[[:space:]]*(input|output|wire)[[:space:]]+signed[[:space:]]' \
        "$NETLIST" \
        || true
    )"

    echo "[AccelClosure] signed structural declarations = $SIGNED_COUNT"

    if [ "$SIGNED_COUNT" -gt 0 ]; then

        echo
        echo "[AccelClosure] Failure class:"
        echo "EDA_INTEROPERABILITY"

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
              /workspace/AccelClosure/results/runs/$RUN_ID/eda/netlist_adapter/1_2_yosys_openroad_compatible.v \
              /workspace/AccelClosure/orfs_runs/results/$TECH/accelclosure_ws_array/$RUN_ID/1_2_yosys.v
          "

        echo
        echo "[AccelClosure] Adapted mapped netlist installed."
        echo "[AccelClosure] Resuming synthesis database generation..."

        run_synth

    else

        echo
        echo "[AccelClosure] ERROR:"
        echo "Synthesis failed for a reason not covered by"
        echo "the known netlist interoperability adapter."

        exit "$SYNTH_RC"
    fi
fi


# ------------------------------------------------------------
# Require real synthesis database.
# ------------------------------------------------------------

if [ ! -f "$ODB" ]; then

    echo
    echo "[AccelClosure] ERROR:"
    echo "1_synth.odb was not produced."

    exit 1
fi


# ------------------------------------------------------------
# Record synthesis provenance.
# ------------------------------------------------------------

python - \
    "$RUN_CTX" \
    "$VERIFICATION_SUMMARY" \
    "$CONFIG_HOST" \
    "$ODB" \
    "$ORFS_IMAGE" \
    "$EDA_DIR/synthesis_provenance.json" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ctx_path = Path(sys.argv[1])
verification_path = Path(sys.argv[2])
config_path = Path(sys.argv[3])
odb_path = Path(sys.argv[4])
image = sys.argv[5]
out = Path(sys.argv[6])

ctx = json.loads(
    ctx_path.read_text()
)

verification = json.loads(
    verification_path.read_text()
)


def sha(path):
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


record = {
    "schema":
        "accelclosure.synthesis_provenance.v1",

    "timestamp_utc":
        datetime.now(
            timezone.utc
        ).isoformat(),

    "run_id":
        ctx["run_id"],

    "technology":
        ctx["parameters"]["technology"],

    "array_n":
        ctx["parameters"]["n"],

    "target_frequency_mhz":
        ctx["parameters"]["target_frequency_mhz"],

    "target_period_ns":
        ctx["parameters"]["target_period_ns"],

    "orfs_image":
        image,

    "verified_rtl": {
        "pe_sha256":
            verification["rtl"]["pe_sha256"],

        "array_sha256":
            verification["rtl"]["array_sha256"]
    },

    "config": {
        "path":
            str(config_path),

        "sha256":
            sha(config_path)
    },

    "synthesis_database": {
        "path":
            str(odb_path),

        "sha256":
            sha(odb_path)
    },

    "status":
        "SYNTHESIS_DATABASE_GENERATED"
}

out.parent.mkdir(
    parents=True,
    exist_ok=True
)

out.write_text(
    json.dumps(
        record,
        indent=2
    )
    + "\n"
)

print("SYNTHESIS_PROVENANCE_RECORDED")
PY


echo
echo "============================================================"
echo " ACCELCLOSURE SYNTHESIS PASS"
echo "============================================================"

ls -lh "$ODB"

echo
echo "[AccelClosure] ODB:"
echo "$ODB"

echo
echo "[AccelClosure] Provenance:"
echo "$EDA_DIR/synthesis_provenance.json"
