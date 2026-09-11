#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo
echo "============================================================"
echo " ACCELCLOSURE - FINAL HACKATHON DEMO"
echo " Designed and developed by Talha Alam"
echo "============================================================"

echo
echo "STEP 1/4 - PRODUCT AND PHYSICAL EVIDENCE"
./bin/accelclosure status

echo
echo "STEP 2/4 - GENERAL ACCELERATOR DESIGN SPACE"
./bin/accelclosure plan \
  --rows 64 \
  --columns 64 \
  --dataflow os \
  --arithmetic int8 \
  --frequency 180 \
  --objective latency

echo
echo "STEP 3/4 - LLM DECODE: AREA-EFFICIENT HARDWARE"
./bin/accelclosure demo \
  --model tinyllama \
  --scenario decode \
  --objective area

echo
echo "STEP 4/4 - LLM PREFILL: LOW-LATENCY HARDWARE"
./bin/accelclosure explain \
  --model qwen \
  --scenario prefill \
  --objective latency

echo
echo "============================================================"
echo " ACCELCLOSURE FINAL DEMO COMPLETE"
echo "============================================================"
