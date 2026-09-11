#!/usr/bin/env python3

import argparse
import gc
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch

from transformers import (
    AutoModel,
    AutoTokenizer,
)


ROOT = Path(__file__).resolve().parents[2]

OUT_DIR = (
    ROOT
    / "results"
    / "benchmarks"
    / "real_models"
    / "tensor_probes"
)

OUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


MODEL_SPECS = {
    "tinybert": {
        "name":
            "TinyBERT-4L-312D",

        "model_id":
            "huawei-noah/TinyBERT_General_4L_312D",

        "tokenizer_id":
            "huawei-noah/TinyBERT_General_4L_312D",

        "tokenizer_fallback":
            "bert-base-uncased",

        "module_suffixes": [
            "encoder.layer.0.attention.self.query",
        ],

        "family":
            "bert",
    },

    "tinyllama": {
        "name":
            "TinyLlama-1.1B",

        "model_id":
            "TinyLlama/TinyLlama-1.1B-Chat-v1.0",

        "tokenizer_id":
            "TinyLlama/TinyLlama-1.1B-Chat-v1.0",

        "tokenizer_fallback":
            None,

        "module_suffixes": [
            "layers.0.self_attn.q_proj",
            "model.layers.0.self_attn.q_proj",
        ],

        "family":
            "decoder",
    },

    "qwen": {
        "name":
            "Qwen2.5-1.5B",

        "model_id":
            "Qwen/Qwen2.5-1.5B",

        "tokenizer_id":
            "Qwen/Qwen2.5-1.5B",

        "tokenizer_fallback":
            None,

        "module_suffixes": [
            "layers.0.self_attn.q_proj",
            "model.layers.0.self_attn.q_proj",
        ],

        "family":
            "decoder",
    },
}


TEXT = (
    "Hardware accelerators execute transformer matrix "
    "multiplications efficiently while preserving numerical "
    "correctness across tiled systolic arrays."
)


ARRAY_SIZES = [
    4,
    8,
    16,
]


class ProbeCaptured(Exception):
    pass


def sha256_bytes(data):
    return hashlib.sha256(
        data
    ).hexdigest()


def array_sha256(array):
    contiguous = np.ascontiguousarray(
        array
    )

    return sha256_bytes(
        contiguous.tobytes()
    )


def symmetric_int8_quantize(array):
    array = np.asarray(
        array,
        dtype=np.float32,
    )

    maximum = float(
        np.max(
            np.abs(array)
        )
    )

    if maximum == 0.0:
        scale = 1.0
    else:
        scale = (
            maximum
            / 127.0
        )

    quantized = np.clip(
        np.rint(
            array
            / scale
        ),
        -127,
        127,
    ).astype(
        np.int8
    )

    return (
        quantized,
        float(scale),
    )


def find_probe_module(
    model,
    suffixes,
):
    candidates = []

    for name, module in model.named_modules():

        for suffix in suffixes:

            if (
                name == suffix
                or name.endswith(
                    "." + suffix
                )
            ):
                candidates.append(
                    (
                        name,
                        module,
                    )
                )

    if not candidates:
        available = [
            name
            for name, _module
            in model.named_modules()
            if (
                "q_proj" in name
                or name.endswith(
                    ".query"
                )
            )
        ]

        raise RuntimeError(
            "Q-projection module not found. "
            + "Candidates seen: "
            + ", ".join(
                available[:40]
            )
        )

    candidates.sort(
        key=lambda item:
            len(item[0])
    )

    return candidates[0]


def capture_real_tensor(
    spec,
):
    tokenizer_source = (
        spec["tokenizer_id"]
    )

    try:
        tokenizer = (
            AutoTokenizer
            .from_pretrained(
                tokenizer_source,
                trust_remote_code=False,
            )
        )

    except Exception:

        fallback = spec[
            "tokenizer_fallback"
        ]

        if fallback is None:
            raise

        tokenizer_source = fallback

        tokenizer = (
            AutoTokenizer
            .from_pretrained(
                fallback,
                trust_remote_code=False,
            )
        )

    print(
        "TOKENIZER="
        + tokenizer_source
    )

    print(
        "LOADING_MODEL="
        + spec["model_id"]
    )

    model = (
        AutoModel
        .from_pretrained(
            spec["model_id"],
            trust_remote_code=False,
            torch_dtype="auto",
        )
    )

    model.eval()

    module_name, module = (
        find_probe_module(
            model,
            spec[
                "module_suffixes"
            ],
        )
    )

    if not hasattr(
        module,
        "weight",
    ):
        raise RuntimeError(
            "Selected module has no weight tensor"
        )

    print(
        "PROBE_MODULE="
        + module_name
    )

    captured = {}

    def hook(
        _module,
        inputs,
        _output,
    ):
        if not inputs:
            raise RuntimeError(
                "Probe module received no input"
            )

        captured["activation"] = (
            inputs[0]
            .detach()
            .cpu()
            .float()
        )

        captured["weight"] = (
            _module.weight
            .detach()
            .cpu()
            .float()
        )

        if getattr(
            _module,
            "bias",
            None,
        ) is not None:
            captured["bias_present"] = True
        else:
            captured["bias_present"] = False

        raise ProbeCaptured()

    handle = (
        module
        .register_forward_hook(
            hook
        )
    )

    if (
        spec["family"]
        == "bert"
    ):
        encoded = tokenizer(
            TEXT,
            return_tensors="pt",
            truncation=True,
            max_length=16,
            padding="max_length",
        )

    else:
        encoded = tokenizer(
            TEXT,
            return_tensors="pt",
            truncation=True,
            max_length=16,
        )

    token_count = int(
        encoded[
            "input_ids"
        ].shape[-1]
    )

    print(
        "TOKEN_COUNT="
        + str(token_count)
    )

    try:

        with torch.inference_mode():

            model(
                **encoded
            )

    except ProbeCaptured:
        pass

    finally:
        handle.remove()

    if (
        "activation"
        not in captured
    ):
        raise RuntimeError(
            "Activation capture failed"
        )

    activation = (
        captured[
            "activation"
        ]
        .numpy()
    )

    weight = (
        captured[
            "weight"
        ]
        .numpy()
    )

    commit_hash = getattr(
        model.config,
        "_commit_hash",
        None,
    )

    del model
    del tokenizer

    gc.collect()

    return {
        "activation":
            activation,

        "weight":
            weight,

        "bias_present":
            captured[
                "bias_present"
            ],

        "module_name":
            module_name,

        "tokenizer_source":
            tokenizer_source,

        "model_commit_hash":
            commit_hash,

        "token_count":
            token_count,
    }


def padded_tiled_gemm(
    a,
    b,
    tile,
):
    if (
        a.ndim != 2
        or b.ndim != 2
    ):
        raise ValueError(
            "Matrices must be rank 2"
        )

    m, k = a.shape

    kb, nout = b.shape

    if k != kb:
        raise ValueError(
            "K dimension mismatch"
        )

    output = np.zeros(
        (
            m,
            nout,
        ),
        dtype=np.int64,
    )

    tile_m_count = math.ceil(
        m
        / tile
    )

    tile_k_count = math.ceil(
        k
        / tile
    )

    tile_n_count = math.ceil(
        nout
        / tile
    )

    physical_macs = 0

    tile_operations = 0

    for mi in range(
        tile_m_count
    ):

        m0 = (
            mi
            * tile
        )

        m1 = min(
            m0 + tile,
            m,
        )

        rows = (
            m1
            - m0
        )

        for ni in range(
            tile_n_count
        ):

            n0 = (
                ni
                * tile
            )

            n1 = min(
                n0 + tile,
                nout,
            )

            cols = (
                n1
                - n0
            )

            acc = np.zeros(
                (
                    tile,
                    tile,
                ),
                dtype=np.int64,
            )

            for ki in range(
                tile_k_count
            ):

                k0 = (
                    ki
                    * tile
                )

                k1 = min(
                    k0 + tile,
                    k,
                )

                depth = (
                    k1
                    - k0
                )

                a_pad = np.zeros(
                    (
                        tile,
                        tile,
                    ),
                    dtype=np.int64,
                )

                b_pad = np.zeros(
                    (
                        tile,
                        tile,
                    ),
                    dtype=np.int64,
                )

                a_pad[
                    :rows,
                    :depth
                ] = (
                    a[
                        m0:m1,
                        k0:k1
                    ]
                    .astype(
                        np.int64
                    )
                )

                b_pad[
                    :depth,
                    :cols
                ] = (
                    b[
                        k0:k1,
                        n0:n1
                    ]
                    .astype(
                        np.int64
                    )
                )

                acc += (
                    a_pad
                    @ b_pad
                )

                physical_macs += (
                    tile
                    * tile
                    * tile
                )

                tile_operations += 1

            output[
                m0:m1,
                n0:n1
            ] = (
                acc[
                    :rows,
                    :cols
                ]
            )

    return (
        output,
        {
            "tile_m_count":
                tile_m_count,

            "tile_k_count":
                tile_k_count,

            "tile_n_count":
                tile_n_count,

            "physical_macs":
                physical_macs,

            "tile_operations":
                tile_operations,
        },
    )


def numeric_metrics(
    fp_reference,
    dequantized,
):
    error = (
        dequantized
        - fp_reference
    )

    mse = float(
        np.mean(
            error
            * error
        )
    )

    rmse = float(
        np.sqrt(mse)
    )

    mae = float(
        np.mean(
            np.abs(error)
        )
    )

    reference_rms = float(
        np.sqrt(
            np.mean(
                fp_reference
                * fp_reference
            )
        )
    )

    relative_rmse = (
        rmse
        / reference_rms
        if reference_rms != 0.0
        else 0.0
    )

    lhs = (
        fp_reference
        .reshape(-1)
        .astype(
            np.float64
        )
    )

    rhs = (
        dequantized
        .reshape(-1)
        .astype(
            np.float64
        )
    )

    denominator = (
        np.linalg.norm(lhs)
        * np.linalg.norm(rhs)
    )

    cosine = (
        float(
            np.dot(
                lhs,
                rhs,
            )
            / denominator
        )
        if denominator != 0.0
        else 1.0
    )

    return {
        "rmse":
            rmse,

        "mae":
            mae,

        "relative_rmse":
            relative_rmse,

        "cosine_similarity":
            cosine,

        "max_abs_error":
            float(
                np.max(
                    np.abs(error)
                )
            ),
    }


def run_one(
    key,
):
    spec = MODEL_SPECS[
        key
    ]

    report_path = (
        OUT_DIR
        / (
            key
            + "_qproj_tensor_probe.json"
        )
    )

    if report_path.exists():

        existing = json.loads(
            report_path.read_text()
        )

        if (
            existing.get("status")
            == "PASS"
        ):
            print()
            print(
                "REUSING_FROZEN_REPORT="
                + report_path
                .relative_to(ROOT)
                .as_posix()
            )

            return existing

        raise RuntimeError(
            "Existing non-PASS report "
            "will not be overwritten"
        )

    print()
    print(
        "=" * 80
    )

    print(
        "MODEL="
        + spec["name"]
    )

    print(
        "HF_ID="
        + spec["model_id"]
    )

    print(
        "=" * 80
    )

    probe = capture_real_tensor(
        spec
    )

    activation = probe[
        "activation"
    ]

    weight = probe[
        "weight"
    ]

    if activation.ndim < 2:
        raise RuntimeError(
            "Unexpected activation rank"
        )

    hidden = int(
        activation.shape[-1]
    )

    activation_2d = (
        activation
        .reshape(
            -1,
            hidden,
        )
        .astype(
            np.float32
        )
    )

    if weight.ndim != 2:
        raise RuntimeError(
            "Unexpected weight rank"
        )

    if (
        weight.shape[1]
        != hidden
    ):
        raise RuntimeError(
            "Activation/weight hidden "
            "dimension mismatch"
        )

    selected_rows = min(
        16,
        activation_2d.shape[0],
    )

    selected_outputs = min(
        64,
        weight.shape[0],
    )

    activation_q_all, activation_scale = (
        symmetric_int8_quantize(
            activation_2d
        )
    )

    weight_q_all, weight_scale = (
        symmetric_int8_quantize(
            weight
        )
    )

    a_fp = (
        activation_2d[
            :selected_rows,
            :
        ]
    )

    w_fp = (
        weight[
            :selected_outputs,
            :
        ]
    )

    a_q = (
        activation_q_all[
            :selected_rows,
            :
        ]
    )

    b_q = (
        weight_q_all[
            :selected_outputs,
            :
        ]
        .T
        .copy()
    )

    fp_reference = (
        a_fp
        @ w_fp.T
    ).astype(
        np.float32
    )

    int_reference = (
        a_q.astype(
            np.int64
        )
        @ b_q.astype(
            np.int64
        )
    )

    dequantized = (
        int_reference
        .astype(
            np.float32
        )
        * activation_scale
        * weight_scale
    )

    metrics = numeric_metrics(
        fp_reference,
        dequantized,
    )

    useful_macs = (
        int(
            a_q.shape[0]
        )
        * int(
            a_q.shape[1]
        )
        * int(
            b_q.shape[1]
        )
    )

    array_results = {}

    for tile in ARRAY_SIZES:

        tiled, stats = (
            padded_tiled_gemm(
                a_q,
                b_q,
                tile,
            )
        )

        exact = bool(
            np.array_equal(
                tiled,
                int_reference,
            )
        )

        utilization = (
            useful_macs
            / stats[
                "physical_macs"
            ]
        )

        array_results[
            f"{tile}x{tile}"
        ] = {
            "exact_int32_match":
                exact,

            "tile_m_count":
                stats[
                    "tile_m_count"
                ],

            "tile_k_count":
                stats[
                    "tile_k_count"
                ],

            "tile_n_count":
                stats[
                    "tile_n_count"
                ],

            "tile_operations":
                stats[
                    "tile_operations"
                ],

            "useful_macs":
                useful_macs,

            "physical_macs":
                stats[
                    "physical_macs"
                ],

            "compute_utilization":
                utilization,
        }

        print(
            f"ARRAY={tile}x{tile} "
            + "EXACT_INT32="
            + (
                "PASS"
                if exact
                else "FAIL"
            )
            + " UTIL="
            + (
                f"{100.0 * utilization:.4f}%"
            )
        )

    all_exact = all(
        item[
            "exact_int32_match"
        ]
        for item
        in array_results.values()
    )

    report = {
        "schema":
            "accelclosure.real_tensor_probe.v1",

        "status":
            (
                "PASS"
                if all_exact
                else "FAIL"
            ),

        "model": {
            "name":
                spec["name"],

            "huggingface_id":
                spec["model_id"],

            "commit_hash":
                probe[
                    "model_commit_hash"
                ],

            "tokenizer_source":
                probe[
                    "tokenizer_source"
                ],
        },

        "probe": {
            "operation":
                "first_layer_q_projection",

            "module":
                probe[
                    "module_name"
                ],

            "bias_present":
                probe[
                    "bias_present"
                ],

            "bias_included":
                False,

            "activation_shape":
                list(
                    activation.shape
                ),

            "weight_shape":
                list(
                    weight.shape
                ),

            "selected_gemm": {
                "m":
                    int(
                        a_q.shape[0]
                    ),

                "k":
                    int(
                        a_q.shape[1]
                    ),

                "n":
                    int(
                        b_q.shape[1]
                    ),
            },
        },

        "quantization": {
            "scheme":
                "symmetric_per_tensor_int8",

            "range":
                [
                    -127,
                    127,
                ],

            "activation_scale":
                activation_scale,

            "weight_scale":
                weight_scale,

            "accumulator":
                "INT32-compatible",

            "activation_int8_sha256":
                array_sha256(
                    a_q
                ),

            "weight_int8_sha256":
                array_sha256(
                    b_q
                ),

            "int_reference_sha256":
                array_sha256(
                    int_reference
                ),
        },

        "numeric_quality":
            metrics,

        "arrays":
            array_results,

        "claim_discipline": {
            "real_model_weights":
                True,

            "real_model_activation":
                True,

            "full_model_inference":
                False,

            "operation_scope":
                "selected first-layer Q projection",

            "integer_execution":
                "software tiled INT8/INT32 reference",

            "rtl_executed":
                False,
        },
    }

    if report["status"] != "PASS":
        raise RuntimeError(
            "Array integer results "
            "do not match reference"
        )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
        )
        + "\n"
    )

    print(
        "MODEL_TENSOR_PROBE=PASS"
    )

    print(
        "SELECTED_GEMM="
        + str(
            a_q.shape[0]
        )
        + "x"
        + str(
            a_q.shape[1]
        )
        + "x"
        + str(
            b_q.shape[1]
        )
    )

    print(
        "QUANT_RMSE="
        + str(
            metrics["rmse"]
        )
    )

    print(
        "RELATIVE_RMSE="
        + str(
            metrics[
                "relative_rmse"
            ]
        )
    )

    print(
        "COSINE_SIMILARITY="
        + str(
            metrics[
                "cosine_similarity"
            ]
        )
    )

    print(
        "REPORT="
        + report_path
        .relative_to(ROOT)
        .as_posix()
    )

    return report


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        choices=[
            "tinybert",
            "tinyllama",
            "qwen",
            "all",
        ],
        default="all",
    )

    args = parser.parse_args()

    if args.model == "all":
        keys = [
            "tinybert",
            "tinyllama",
            "qwen",
        ]
    else:
        keys = [
            args.model
        ]

    reports = []

    for key in keys:
        reports.append(
            run_one(
                key
            )
        )

    failures = [
        item
        for item in reports
        if item[
            "status"
        ]
        != "PASS"
    ]

    if failures:
        raise SystemExit(
            "REAL_TENSOR_SUITE=FAIL"
        )

    print()
    print(
        "=" * 80
    )
    print(
        "REAL_TENSOR_SUITE=PASS"
    )
    print(
        "MODELS_PASSED="
        + str(
            len(reports)
        )
    )
    print(
        "=" * 80
    )


if __name__ == "__main__":
    main()
