#!/usr/bin/env python3

import json
import hashlib
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "results/benchmarks/real_models/final_benchmark_report.json"
OUT = ROOT / "results/submission/figures"
OUT.mkdir(parents=True, exist_ok=True)

data = json.loads(REPORT.read_text())

if data.get("status") != "PASS":
    raise SystemExit("Final benchmark report is not PASS")

hw = data["hardware_designs"]
arrays = [x["array"] for x in hw]
target = [x["target_frequency_mhz"] for x in hw]
fmax = [x["postroute_fmax_estimate_mhz"] for x in hw]
area = [x["routed_area_mm2"] for x in hw]
power = [x["vectorless_power_w"] for x in hw]

def finish(name):
    plt.tight_layout()
    plt.savefig(OUT / f"{name}.png", dpi=240, bbox_inches="tight")
    plt.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    plt.close()

# Figure 1: requested clock versus achieved post-route Fmax
plt.figure(figsize=(7.2, 4.6))
x = range(len(arrays))
plt.plot(x, target, marker="o", linewidth=2, label="Requested clock")
plt.plot(x, fmax, marker="o", linewidth=2, label="Post-route Fmax estimate")
plt.xticks(x, arrays)
plt.xlabel("Systolic-array geometry")
plt.ylabel("Frequency (MHz)")
plt.title("Timing Closure Across Physically Validated Accelerators")
plt.grid(axis="y", alpha=0.25)
plt.legend()
finish("fig01_postroute_frequency")

# Figure 2: routed area
plt.figure(figsize=(7.2, 4.6))
bars = plt.bar(arrays, area)
plt.xlabel("Systolic-array geometry")
plt.ylabel("Routed area (mm$^2$)")
plt.title("Post-Route Area Scaling")
plt.grid(axis="y", alpha=0.25)
for bar, value in zip(bars, area):
    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
             f"{value:.3f}", ha="center", va="bottom")
finish("fig02_routed_area")

# Figure 3: vectorless power
plt.figure(figsize=(7.2, 4.6))
bars = plt.bar(arrays, power)
plt.xlabel("Systolic-array geometry")
plt.ylabel("Vectorless power estimate (W)")
plt.title("Post-Route Vectorless Power Scaling")
plt.grid(axis="y", alpha=0.25)
for bar, value in zip(bars, power):
    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
             f"{value:.3f}", ha="center", va="bottom")
finish("fig03_vectorless_power")

# Figure 4: token-by-token decode utilization
decode = next(
    x for x in data["workload_projection"]
    if x["model"] == "TinyLlama-1.1B"
    and x["scenario"] == "decode_1_ctx128"
)

decode_util = [
    100.0 * decode["array_utilization"][a]
    for a in arrays
]

plt.figure(figsize=(7.2, 4.6))
bars = plt.bar(arrays, decode_util)
plt.xlabel("Systolic-array geometry")
plt.ylabel("Array utilization (%)")
plt.title("LLM Token Decode: Spatial Utilization Collapse")
plt.ylim(0, max(decode_util) * 1.25)
plt.grid(axis="y", alpha=0.25)
for bar, value in zip(bars, decode_util):
    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
             f"{value:.2f}%", ha="center", va="bottom")
finish("fig04_decode_utilization")

# Figure 5: real-model tensor cosine similarity
tensor = data["real_tensor_validation"]
models = [x["model"] for x in tensor]
cosine = [x["cosine_similarity"] for x in tensor]

plt.figure(figsize=(7.8, 4.8))
bars = plt.bar(models, cosine)
plt.ylabel("Cosine similarity")
plt.title("Real Transformer Tensor Validation After INT8 Quantization")
plt.ylim(0.97, 1.002)
plt.grid(axis="y", alpha=0.25)
for bar, value in zip(bars, cosine):
    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
             f"{value:.6f}", ha="center", va="bottom")
finish("fig05_real_tensor_similarity")

# Figure 6: workload-aware accelerator selection
workloads = data["workload_projection"]

labels = []
fastest = []
area_best = []
energy_best = []

for w in workloads:
    model = w["model"].replace("-1.1B", "").replace("-1.5B", "")
    scenario = w["scenario"]
    if scenario == "encoder_seq128":
        scenario = "Encoder"
    elif scenario == "prefill_128":
        scenario = "Prefill"
    elif scenario == "decode_1_ctx128":
        scenario = "Decode"
    labels.append(f"{model}\\n{scenario}")
    fastest.append(w["fastest_at_closed_clock"])
    area_best.append(w["best_area_normalized"])
    energy_best.append(w["lowest_vectorless_energy_proxy"])

array_to_num = {"4x4": 4, "8x8": 8, "16x16": 16}

plt.figure(figsize=(10.0, 5.2))
x = range(len(labels))
plt.plot(x, [array_to_num[v] for v in fastest],
         marker="o", linewidth=2, label="Lowest projected latency")
plt.plot(x, [array_to_num[v] for v in area_best],
         marker="s", linewidth=2, label="Best area-normalized")
plt.plot(x, [array_to_num[v] for v in energy_best],
         marker="^", linewidth=2, label="Lowest energy proxy")
plt.xticks(x, labels)
plt.yticks([4, 8, 16], ["4x4", "8x8", "16x16"])
plt.ylabel("Selected accelerator")
plt.title("AccelClosure Workload-Aware Hardware Selection")
plt.grid(axis="y", alpha=0.25)
plt.legend(loc="best")
finish("fig06_workload_hardware_selection")

# Freeze provenance for the generated submission figures
report_sha = hashlib.sha256(REPORT.read_bytes()).hexdigest()

manifest = {
    "source_report": str(REPORT.relative_to(ROOT)),
    "source_report_sha256": report_sha,
    "source_report_status": data["status"],
    "figure_count": 6,
    "claim_boundary": (
        "Figures are derived from the frozen final benchmark report. "
        "Workload values remain analytical compute-core projections and "
        "power remains a vectorless ORFS estimate."
    )
}

(OUT / "figure_provenance.json").write_text(
    json.dumps(manifest, indent=2) + "\\n"
)

print("SUBMISSION_FIGURES=PASS")
print(f"FIGURE_COUNT={manifest['figure_count']}")
print(f"SOURCE_REPORT_SHA256={report_sha}")
print(f"OUTPUT_DIRECTORY={OUT}")
