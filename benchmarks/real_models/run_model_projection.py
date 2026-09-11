#!/usr/bin/env python3

import csv
import json
import math
from pathlib import Path

from transformers import AutoConfig


ROOT = Path(__file__).resolve().parents[2]

SUITE_PATH = (
    ROOT
    / "configs"
    / "benchmarks"
    / "real_model_suite.json"
)

CATALOG_PATH = (
    ROOT
    / "results"
    / "benchmarks"
    / "real_models"
    / "design_catalog.json"
)

RESULT_DIR = (
    ROOT
    / "results"
    / "benchmarks"
    / "real_models"
)

JSON_OUT = (
    RESULT_DIR
    / "projection_results.json"
)

CSV_OUT = (
    RESULT_DIR
    / "projection_summary.csv"
)


def ceil_div(a, b):
    return (
        a + b - 1
    ) // b


def gemm(
    name,
    m,
    k,
    n,
    repeat=1
):
    return {
        "name": name,
        "m": int(m),
        "k": int(k),
        "n": int(n),
        "repeat": int(repeat)
    }


def build_bert_ops(
    cfg,
    scenario
):
    s = int(
        scenario["sequence_length"]
    )

    h = int(
        cfg.hidden_size
    )

    inter = int(
        cfg.intermediate_size
    )

    heads = int(
        cfg.num_attention_heads
    )

    head_dim = (
        int(cfg.head_dim)
        if getattr(
            cfg,
            "head_dim",
            None
        )
        else h // heads
    )

    layers = int(
        cfg.num_hidden_layers
    )

    per_layer = [
        gemm(
            "q_projection",
            s,
            h,
            h
        ),
        gemm(
            "k_projection",
            s,
            h,
            h
        ),
        gemm(
            "v_projection",
            s,
            h,
            h
        ),
        gemm(
            "output_projection",
            s,
            h,
            h
        ),
        gemm(
            "attention_qk",
            s,
            head_dim,
            s,
            repeat=heads
        ),
        gemm(
            "attention_av",
            s,
            s,
            head_dim,
            repeat=heads
        ),
        gemm(
            "ffn_expand",
            s,
            h,
            inter
        ),
        gemm(
            "ffn_project",
            s,
            inter,
            h
        )
    ]

    operations = []

    for op in per_layer:
        item = dict(op)
        item["repeat"] *= layers
        operations.append(item)

    return {
        "layers": layers,
        "hidden_size": h,
        "intermediate_size": inter,
        "attention_heads": heads,
        "kv_heads": heads,
        "head_dim": head_dim,
        "operations": operations
    }


def build_decoder_ops(
    cfg,
    scenario
):
    hidden = int(
        cfg.hidden_size
    )

    inter = int(
        cfg.intermediate_size
    )

    q_heads = int(
        cfg.num_attention_heads
    )

    kv_heads = int(
        getattr(
            cfg,
            "num_key_value_heads",
            q_heads
        )
        or q_heads
    )

    head_dim = (
        int(cfg.head_dim)
        if getattr(
            cfg,
            "head_dim",
            None
        )
        else hidden // q_heads
    )

    kv_dim = (
        kv_heads
        * head_dim
    )

    layers = int(
        cfg.num_hidden_layers
    )

    tokens = int(
        scenario[
            "sequence_length"
        ]
    )

    context = int(
        scenario.get(
            "context_length",
            tokens
        )
    )

    per_layer = [
        gemm(
            "q_projection",
            tokens,
            hidden,
            hidden
        ),
        gemm(
            "k_projection",
            tokens,
            hidden,
            kv_dim
        ),
        gemm(
            "v_projection",
            tokens,
            hidden,
            kv_dim
        ),
        gemm(
            "output_projection",
            tokens,
            hidden,
            hidden
        ),
        gemm(
            "attention_qk",
            tokens,
            head_dim,
            context,
            repeat=q_heads
        ),
        gemm(
            "attention_av",
            tokens,
            context,
            head_dim,
            repeat=q_heads
        ),
        gemm(
            "mlp_gate",
            tokens,
            hidden,
            inter
        ),
        gemm(
            "mlp_up",
            tokens,
            hidden,
            inter
        ),
        gemm(
            "mlp_down",
            tokens,
            inter,
            hidden
        )
    ]

    operations = []

    for op in per_layer:
        item = dict(op)
        item["repeat"] *= layers
        operations.append(item)

    return {
        "layers": layers,
        "hidden_size": hidden,
        "intermediate_size": inter,
        "attention_heads": q_heads,
        "kv_heads": kv_heads,
        "head_dim": head_dim,
        "kv_dimension": kv_dim,
        "operations": operations
    }


def map_operation(
    op,
    array_n
):
    m = op["m"]
    k = op["k"]
    n = op["n"]
    repeat = op["repeat"]

    tm = ceil_div(
        m,
        array_n
    )

    tk = ceil_div(
        k,
        array_n
    )

    tn = ceil_div(
        n,
        array_n
    )

    tiles_per_repeat = (
        tm
        * tk
        * tn
    )

    tile_count = (
        tiles_per_repeat
        * repeat
    )

    useful_macs = (
        m
        * k
        * n
        * repeat
    )

    padded_macs = (
        tile_count
        * array_n
        * array_n
        * array_n
    )

    compute_cycles = (
        tile_count
        * array_n
    )

    utilization = (
        useful_macs
        / padded_macs
        if padded_macs
        else 0.0
    )

    return {
        "operation": op["name"],
        "m": m,
        "k": k,
        "n": n,
        "repeat": repeat,
        "tile_m": tm,
        "tile_k": tk,
        "tile_n": tn,
        "tile_count": tile_count,
        "useful_macs": useful_macs,
        "padded_macs": padded_macs,
        "steady_state_compute_cycles":
            compute_cycles,
        "compute_utilization":
            utilization
    }


def evaluate(
    model,
    scenario,
    workload,
    design
):
    array_n = int(
        design["array_n"]
    )

    mapped = [
        map_operation(
            op,
            array_n
        )
        for op
        in workload["operations"]
    ]

    useful_macs = sum(
        item["useful_macs"]
        for item in mapped
    )

    padded_macs = sum(
        item["padded_macs"]
        for item in mapped
    )

    cycles = sum(
        item[
            "steady_state_compute_cycles"
        ]
        for item in mapped
    )

    tile_count = sum(
        item["tile_count"]
        for item in mapped
    )

    utilization = (
        useful_macs
        / padded_macs
    )

    target_mhz = float(
        design[
            "target_frequency_mhz"
        ]
    )

    fmax_mhz = float(
        design[
            "postroute_fmax_estimate_mhz"
        ]
    )

    area = float(
        design[
            "routed_area_mm2"
        ]
    )

    power = float(
        design[
            "vectorless_power_w"
        ]
    )

    target_latency_us = (
        cycles
        / target_mhz
    )

    fmax_latency_us = (
        cycles
        / fmax_mhz
    )

    target_latency_s = (
        target_latency_us
        * 1.0e-6
    )

    effective_gmacs_target = (
        useful_macs
        / target_latency_s
        / 1.0e9
    )

    effective_gops_target = (
        2.0
        * effective_gmacs_target
    )

    peak_gmacs_target = (
        array_n
        * array_n
        * target_mhz
        / 1000.0
    )

    peak_gops_target = (
        2.0
        * peak_gmacs_target
    )

    vectorless_energy_proxy_mj = (
        power
        * target_latency_s
        * 1000.0
    )

    return {
        "model": model["name"],
        "huggingface_id":
            model["huggingface_id"],
        "scenario":
            scenario["name"],
        "array":
            design["array"],
        "array_n":
            array_n,
        "layers":
            workload["layers"],
        "useful_macs":
            useful_macs,
        "padded_macs":
            padded_macs,
        "tile_count":
            tile_count,
        "compute_utilization":
            utilization,
        "steady_state_compute_cycles":
            cycles,
        "target_frequency_mhz":
            target_mhz,
        "postroute_fmax_estimate_mhz":
            fmax_mhz,
        "projected_compute_latency_us_at_target":
            target_latency_us,
        "projected_compute_latency_us_at_fmax":
            fmax_latency_us,
        "peak_gmacs_at_target":
            peak_gmacs_target,
        "peak_gops_at_target":
            peak_gops_target,
        "effective_gmacs_at_target":
            effective_gmacs_target,
        "effective_gops_at_target":
            effective_gops_target,
        "routed_area_mm2":
            area,
        "effective_gops_per_mm2":
            effective_gops_target
            / area,
        "vectorless_power_w":
            power,
        "vectorless_energy_proxy_mj":
            vectorless_energy_proxy_mj,
        "operation_breakdown":
            mapped
    }


suite = json.loads(
    SUITE_PATH.read_text()
)

catalog = json.loads(
    CATALOG_PATH.read_text()
)

all_results = []

model_metadata = []


for model in suite["models"]:

    cfg = AutoConfig.from_pretrained(
        model["huggingface_id"],
        trust_remote_code=False
    )

    model_entry = {
        "name":
            model["name"],
        "huggingface_id":
            model["huggingface_id"],
        "model_type":
            cfg.model_type,
        "scenarios": []
    }

    for scenario in model["scenarios"]:

        if model["family"] == "bert":
            workload = build_bert_ops(
                cfg,
                scenario
            )

        elif model["family"] in (
            "llama",
            "qwen2"
        ):
            workload = build_decoder_ops(
                cfg,
                scenario
            )

        else:
            raise RuntimeError(
                "Unsupported model family: "
                + model["family"]
            )

        model_entry[
            "scenarios"
        ].append(
            {
                "scenario":
                    scenario,
                "workload":
                    workload
            }
        )

        for design in catalog["designs"]:

            result = evaluate(
                model,
                scenario,
                workload,
                design
            )

            all_results.append(
                result
            )

    model_metadata.append(
        model_entry
    )


for result in all_results:
    result[
        "operation_breakdown"
    ] = result[
        "operation_breakdown"
    ]


output = {
    "schema":
        "accelclosure.real_model_projection.v1",

    "methodology": {
        "mapping":
            "square GEMMs tiled across M, K, and N "
            "onto N x N INT8 systolic arrays",

        "cycle_model":
            "steady-state compute-core projection; "
            "one full N x N x N tile contributes N "
            "compute cycles",

        "attention_mapping":
            "attention heads mapped independently",

        "included":
            [
                "Q projection",
                "K projection",
                "V projection",
                "output projection",
                "attention QK^T",
                "attention x V",
                "Transformer MLP GEMMs"
            ],

        "excluded":
            [
                "embedding lookup",
                "LayerNorm or RMSNorm",
                "Softmax",
                "RoPE",
                "GELU or SiLU",
                "KV-cache memory traffic",
                "DMA",
                "weight-loading latency",
                "SRAM and DRAM latency",
                "LM head",
                "host software overhead"
            ],

        "latency_claim":
            "analytical compute-core projection, "
            "not measured end-to-end model latency",

        "power_claim":
            "energy values are vectorless-power "
            "proxies at each design's closed target clock, "
            "not workload-activity-qualified energy"
    },

    "model_metadata":
        model_metadata,

    "results":
        all_results
}


RESULT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

JSON_OUT.write_text(
    json.dumps(
        output,
        indent=2
    )
    + "\n"
)


csv_fields = [
    "model",
    "scenario",
    "array",
    "useful_macs",
    "padded_macs",
    "tile_count",
    "compute_utilization",
    "steady_state_compute_cycles",
    "target_frequency_mhz",
    "postroute_fmax_estimate_mhz",
    "projected_compute_latency_us_at_target",
    "projected_compute_latency_us_at_fmax",
    "effective_gmacs_at_target",
    "effective_gops_at_target",
    "routed_area_mm2",
    "effective_gops_per_mm2",
    "vectorless_power_w",
    "vectorless_energy_proxy_mj"
]


with CSV_OUT.open(
    "w",
    newline=""
) as handle:

    writer = csv.DictWriter(
        handle,
        fieldnames=csv_fields
    )

    writer.writeheader()

    for result in all_results:
        writer.writerow(
            {
                key: result[key]
                for key in csv_fields
            }
        )


print(
    "REAL_MODEL_PROJECTION=PASS"
)

print()
print(
    "NOTE: latency is compute-core projection only."
)

print(
    "NOTE: energy is a vectorless-power proxy."
)

print()


scenarios = []

for result in all_results:
    key = (
        result["model"],
        result["scenario"]
    )

    if key not in scenarios:
        scenarios.append(key)


for key in scenarios:

    group = [
        item
        for item in all_results
        if (
            item["model"],
            item["scenario"]
        )
        == key
    ]

    group.sort(
        key=lambda item:
            item[
                "projected_compute_latency_us_at_target"
            ]
    )

    print(
        "=" * 78
    )

    print(
        "MODEL="
        + key[0]
        + "  SCENARIO="
        + key[1]
    )

    print(
        "=" * 78
    )

    for item in group:
        print(
            f"{item['array']:>5}  "
            f"util="
            f"{100.0 * item['compute_utilization']:6.2f}%  "
            f"lat_target="
            f"{item['projected_compute_latency_us_at_target']:12.3f} us  "
            f"eff="
            f"{item['effective_gops_at_target']:8.3f} GOPS  "
            f"GOPS/mm2="
            f"{item['effective_gops_per_mm2']:8.3f}  "
            f"energy_proxy="
            f"{item['vectorless_energy_proxy_mj']:10.6f} mJ"
        )

    best = group[0]

    print()
    print(
        "FASTEST_AT_CLOSED_CLOCK="
        + best["array"]
    )

    efficient = max(
        group,
        key=lambda item:
            item[
                "effective_gops_per_mm2"
            ]
    )

    print(
        "BEST_AREA_NORMALIZED="
        + efficient["array"]
    )

    low_energy = min(
        group,
        key=lambda item:
            item[
                "vectorless_energy_proxy_mj"
            ]
    )

    print(
        "LOWEST_VECTORLESS_ENERGY_PROXY="
        + low_energy["array"]
    )

    print()


print(
    "JSON_RESULT="
    + JSON_OUT.relative_to(
        ROOT
    ).as_posix()
)

print(
    "CSV_RESULT="
    + CSV_OUT.relative_to(
        ROOT
    ).as_posix()
)
