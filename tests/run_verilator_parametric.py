#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from chia.base.ChiaFunction import ChiaFunction, get


PROJECT_ROOT = Path(
    os.environ.get(
        "ACCELCLOSURE_ROOT",
        Path(__file__).resolve().parents[1],
    )
).expanduser().resolve()


def cpp_harness(
    n: int,
    data_w: int,
    acc_w: int,
    hop_latency: int,
    boundary_registers: bool,
    random_cases: int,
) -> str:

    if data_w != 8:
        raise ValueError(
            "Current parametric checker supports DATA_W=8"
        )

    if acc_w != 32:
        raise ValueError(
            "Current parametric checker supports ACC_W=32"
        )

    if n < 2:
        raise ValueError("N must be >= 2")

    packed_bits = n * data_w
    result_bits = n * acc_w

    # ---------------------------------------------------------
    # Activation / weight packed-bus helpers.
    # ---------------------------------------------------------

    if packed_bits <= 32:
        clear_act = "dut->act_data_in = 0;"
        clear_weight = "dut->weight_load_data = 0;"

        set_act = r'''
    dut->act_data_in |=
        (
            static_cast<uint32_t>(
                static_cast<uint8_t>(value)
            )
            << (8 * lane)
        );
'''

        set_weight = r'''
    dut->weight_load_data |=
        (
            static_cast<uint32_t>(
                static_cast<uint8_t>(value)
            )
            << (8 * lane)
        );
'''

    elif packed_bits <= 64:
        clear_act = "dut->act_data_in = 0;"
        clear_weight = "dut->weight_load_data = 0;"

        set_act = r'''
    dut->act_data_in |=
        (
            static_cast<uint64_t>(
                static_cast<uint8_t>(value)
            )
            << (8 * lane)
        );
'''

        set_weight = r'''
    dut->weight_load_data |=
        (
            static_cast<uint64_t>(
                static_cast<uint8_t>(value)
            )
            << (8 * lane)
        );
'''

    else:
        packed_words = (packed_bits + 31) // 32

        clear_act = f'''
    for (int w = 0; w < {packed_words}; ++w) {{
        dut->act_data_in[w] = 0;
    }}
'''

        clear_weight = f'''
    for (int w = 0; w < {packed_words}; ++w) {{
        dut->weight_load_data[w] = 0;
    }}
'''

        set_act = r'''
    {
        int bit = 8 * lane;
        int word = bit / 32;
        int shift = bit % 32;

        uint32_t v =
            static_cast<uint32_t>(
                static_cast<uint8_t>(value)
            );

        dut->act_data_in[word] |=
            (v << shift);

        if (shift > 24) {
            dut->act_data_in[word + 1] |=
                (v >> (32 - shift));
        }
    }
'''

        set_weight = r'''
    {
        int bit = 8 * lane;
        int word = bit / 32;
        int shift = bit % 32;

        uint32_t v =
            static_cast<uint32_t>(
                static_cast<uint8_t>(value)
            );

        dut->weight_load_data[word] |=
            (v << shift);

        if (shift > 24) {
            dut->weight_load_data[word + 1] |=
                (v >> (32 - shift));
        }
    }
'''

    # ---------------------------------------------------------
    # Partial sum / result helpers.
    #
    # ACC_W=32 means N>=4 naturally maps each output lane
    # onto one Verilator wide-array word.
    # ---------------------------------------------------------

    if result_bits <= 64:
        clear_psum = "dut->psum_data_in = 0;"

        result_lane = r'''
    uint64_t raw =
        static_cast<uint64_t>(
            dut->result_data_out
        );

    uint32_t lane_raw =
        static_cast<uint32_t>(
            raw >> (32 * lane)
        );

    return static_cast<int32_t>(
        lane_raw
    );
'''

    else:
        result_words = (result_bits + 31) // 32

        clear_psum = f'''
    for (int w = 0; w < {result_words}; ++w) {{
        dut->psum_data_in[w] = 0;
    }}
'''

        result_lane = r'''
    uint32_t raw =
        dut->result_data_out[lane];

    return static_cast<int32_t>(raw);
'''

    boundary_drain = 1 if boundary_registers else 0

    return f'''
#include "Vaccelclosure_ws_array.h"
#include "verilated.h"

#include <array>
#include <cstdint>
#include <iostream>
#include <random>


static constexpr int N = {n};
static constexpr int DATA_W = {data_w};
static constexpr int ACC_W = {acc_w};

static constexpr int PE_HOP_LATENCY =
    {hop_latency};

static constexpr int BOUNDARY_REGISTERS =
    {1 if boundary_registers else 0};

static constexpr int NUM_RANDOM_TESTS =
    {random_cases};


using Matrix =
    std::array<
        std::array<int, N>,
        N
    >;

using Matrix32 =
    std::array<
        std::array<int32_t, N>,
        N
    >;


static void clear_act_bus(
    Vaccelclosure_ws_array *dut
) {{
{clear_act}
}}


static void clear_weight_bus(
    Vaccelclosure_ws_array *dut
) {{
{clear_weight}
}}


static void zero_psum_input(
    Vaccelclosure_ws_array *dut
) {{
{clear_psum}
}}


static void set_act_lane(
    Vaccelclosure_ws_array *dut,
    int lane,
    int value
) {{
{set_act}
}}


static void set_weight_lane(
    Vaccelclosure_ws_array *dut,
    int lane,
    int value
) {{
{set_weight}
}}


static int32_t result_lane(
    Vaccelclosure_ws_array *dut,
    int lane
) {{
{result_lane}
}}


static void clear_inputs(
    Vaccelclosure_ws_array *dut
) {{
    dut->weight_load_valid = 0;
    dut->weight_load_row = 0;

    clear_weight_bus(dut);

    dut->act_valid_in = 0;
    clear_act_bus(dut);

    dut->psum_valid_in = 0;
    zero_psum_input(dut);
}}


static void tick(
    Vaccelclosure_ws_array *dut
) {{
    dut->clk = 0;
    dut->eval();

    dut->clk = 1;
    dut->eval();

    dut->clk = 0;
    dut->eval();
}}


static Matrix32 reference_gemm(
    const Matrix& A,
    const Matrix& B
) {{
    Matrix32 C{{}};

    for (int i = 0; i < N; ++i) {{
        for (int j = 0; j < N; ++j) {{

            int32_t sum = 0;

            for (int k = 0; k < N; ++k) {{
                sum +=
                    static_cast<int32_t>(
                        A[i][k]
                    )
                    *
                    static_cast<int32_t>(
                        B[k][j]
                    );
            }}

            C[i][j] = sum;
        }}
    }}

    return C;
}}


static void reset_dut(
    Vaccelclosure_ws_array *dut
) {{
    clear_inputs(dut);

    dut->rst_n = 0;

    tick(dut);
    tick(dut);

    dut->rst_n = 1;
}}


static void load_weights(
    Vaccelclosure_ws_array *dut,
    const Matrix& B
) {{
    clear_inputs(dut);

    dut->weight_load_valid = 1;

    for (int k = 0; k < N; ++k) {{

        dut->weight_load_row = k;

        clear_weight_bus(dut);

        for (int j = 0; j < N; ++j) {{
            set_weight_lane(
                dut,
                j,
                B[k][j]
            );
        }}

        tick(dut);
    }}

    clear_inputs(dut);

    for (
        int d = 0;
        d < {boundary_drain};
        ++d
    ) {{
        tick(dut);
    }}
}}


static bool run_case(
    Vaccelclosure_ws_array *dut,
    const Matrix& A,
    const Matrix& B,
    int case_index
) {{
    reset_dut(dut);
    load_weights(dut, B);

    Matrix32 expected =
        reference_gemm(A, B);

    bool pass = true;

    /*
       Generic systolic schedule:

         activation A[i][k]
           enters row k at
           cycle = i + H*k

         zero psum for output column j
           enters column j at
           cycle = i + H*j

       H = PE_HOP_LATENCY.

       Expected output:
           cycle =
               i
               + H*j
               + H*N
               - 1
               + BOUNDARY_REGISTERS

       Explanation:

       A sequential PE produces the first row result
       on the same numbered simulation cycle in which
       its input is clocked. Therefore an N-row chain
       contributes H*N - 1 cycles from the externally
       scheduled input cycle.

       A synchronous array-boundary register adds one
       common additional cycle.

       Verified cases:

         H=1, boundary=0:
             output offset = N-1

         H=2, boundary=1:
             output offset = 2*N
    */

    const int last_cycle =
        (N - 1)
        + PE_HOP_LATENCY * (N - 1)
        + PE_HOP_LATENCY * N
        - 1
        + BOUNDARY_REGISTERS;

    for (
        int cycle = 0;
        cycle <= last_cycle;
        ++cycle
    ) {{
        clear_inputs(dut);

        uint32_t act_valid = 0;

        for (int k = 0; k < N; ++k) {{

            int i =
                cycle
                - PE_HOP_LATENCY * k;

            if (i >= 0 && i < N) {{

                act_valid |=
                    (1u << k);

                set_act_lane(
                    dut,
                    k,
                    A[i][k]
                );
            }}
        }}

        dut->act_valid_in =
            act_valid;

        uint32_t psum_valid = 0;

        for (int j = 0; j < N; ++j) {{

            int i =
                cycle
                - PE_HOP_LATENCY * j;

            if (i >= 0 && i < N) {{
                psum_valid |=
                    (1u << j);
            }}
        }}

        dut->psum_valid_in =
            psum_valid;

        zero_psum_input(dut);

        tick(dut);

        uint32_t expected_valid = 0;

        for (int j = 0; j < N; ++j) {{

            int i =
                cycle
                - PE_HOP_LATENCY * N
                - PE_HOP_LATENCY * j
                + 1
                - BOUNDARY_REGISTERS;

            if (i >= 0 && i < N) {{

                expected_valid |=
                    (1u << j);

                int32_t got =
                    result_lane(
                        dut,
                        j
                    );

                int32_t exp =
                    expected[i][j];

                if (got != exp) {{

                    std::cerr
                        << "FAIL case="
                        << case_index
                        << " cycle="
                        << cycle
                        << " C["
                        << i
                        << "]["
                        << j
                        << "] expected="
                        << exp
                        << " got="
                        << got
                        << std::endl;

                    pass = false;
                }}
            }}
        }}

        uint32_t actual_valid =
            static_cast<uint32_t>(
                dut->result_valid_out
            );

        if (
            actual_valid
            != expected_valid
        ) {{
            std::cerr
                << "FAIL case="
                << case_index
                << " cycle="
                << cycle
                << " expected_valid=0x"
                << std::hex
                << expected_valid
                << " actual_valid=0x"
                << actual_valid
                << std::dec
                << std::endl;

            pass = false;
        }}
    }}

    clear_inputs(dut);
    tick(dut);

    if (dut->result_valid_out != 0) {{

        std::cerr
            << "FAIL case="
            << case_index
            << ": pipeline did not drain"
            << std::endl;

        pass = false;
    }}

    return pass;
}}


static Matrix directed_matrix_a()
{{
    Matrix A{{}};

    for (int i = 0; i < N; ++i) {{
        for (int j = 0; j < N; ++j) {{

            int value =
                (
                    (
                        i * 37
                        + j * 19
                        + 11
                    )
                    % 255
                )
                - 127;

            A[i][j] = value;
        }}
    }}

    return A;
}}


static Matrix directed_matrix_b()
{{
    Matrix B{{}};

    for (int i = 0; i < N; ++i) {{
        for (int j = 0; j < N; ++j) {{

            int value =
                (
                    (
                        i * 23
                        + j * 41
                        + 7
                    )
                    % 255
                )
                - 127;

            B[i][j] = value;
        }}
    }}

    return B;
}}


int main(
    int argc,
    char **argv
) {{
    Verilated::commandArgs(
        argc,
        argv
    );

    auto *dut =
        new Vaccelclosure_ws_array;

    bool all_pass = true;
    int passed = 0;

    Matrix directed_A =
        directed_matrix_a();

    Matrix directed_B =
        directed_matrix_b();

    if (
        run_case(
            dut,
            directed_A,
            directed_B,
            0
        )
    ) {{
        ++passed;
    }}
    else {{
        all_pass = false;
    }}

    std::mt19937 rng(
        0xACCE1
    );

    std::uniform_int_distribution<int>
        dist(-128, 127);

    for (
        int test = 1;
        test <= NUM_RANDOM_TESTS;
        ++test
    ) {{
        Matrix A{{}};
        Matrix B{{}};

        for (int i = 0; i < N; ++i) {{
            for (int j = 0; j < N; ++j) {{
                A[i][j] =
                    dist(rng);

                B[i][j] =
                    dist(rng);
            }}
        }}

        if (
            run_case(
                dut,
                A,
                B,
                test
            )
        ) {{
            ++passed;
        }}
        else {{
            all_pass = false;
        }}
    }}

    std::cout
        << "REGRESSION_CASES_PASSED="
        << passed
        << "/"
        << (NUM_RANDOM_TESTS + 1)
        << std::endl;

    std::cout
        << "CONFIG_N="
        << N
        << std::endl;

    std::cout
        << "PE_HOP_LATENCY="
        << PE_HOP_LATENCY
        << std::endl;

    if (all_pass) {{
        std::cout
            << "ACCELCLOSURE_PARAMETRIC_GEMM_PASS"
            << std::endl;
    }}
    else {{
        std::cout
            << "ACCELCLOSURE_PARAMETRIC_GEMM_FAIL"
            << std::endl;
    }}

    dut->final();
    delete dut;

    return all_pass ? 0 : 1;
}}
'''


@ChiaFunction(
    resources={"verilator_run": 1}
)
def verilator_parametric(
    pe_rtl: str,
    array_rtl: str,
    cpp_test: str,
    n: int,
    data_w: int,
    acc_w: int,
) -> dict:

    verilator = shutil.which("verilator")

    if verilator is None:
        return {
            "status": "TOOL_NOT_FOUND",
            "returncode": -1,
        }

    with tempfile.TemporaryDirectory() as td:

        work = Path(td)

        pe = work / "accelclosure_ws_pe.sv"
        array = work / "accelclosure_ws_array.sv"
        cpp = work / "sim_main.cpp"

        pe.write_text(pe_rtl)
        array.write_text(array_rtl)
        cpp.write_text(cpp_test)

        obj_dir = work / "obj_dir"

        build_cmd = [
            verilator,
            "--cc",
            "--exe",
            "--build",
            "--sv",
            "-Wall",
            "-Wno-fatal",
            "--top-module",
            "accelclosure_ws_array",
            f"-GN={n}",
            f"-GDATA_W={data_w}",
            f"-GACC_W={acc_w}",
            "--Mdir",
            str(obj_dir),
            str(pe),
            str(array),
            str(cpp),
        ]

        build = subprocess.run(
            build_cmd,
            capture_output=True,
            text=True,
        )

        if build.returncode != 0:
            return {
                "status": "BUILD_FAIL",
                "returncode": build.returncode,
                "build_stdout": build.stdout,
                "build_stderr": build.stderr,
            }

        binary = (
            obj_dir
            / "Vaccelclosure_ws_array"
        )

        sim = subprocess.run(
            [str(binary)],
            capture_output=True,
            text=True,
        )

        return {
            "status":
                "PASS"
                if sim.returncode == 0
                else "FAIL",

            "returncode":
                sim.returncode,

            "build_stdout":
                build.stdout,

            "build_stderr":
                build.stderr,

            "simulation_stdout":
                sim.stdout,

            "simulation_stderr":
                sim.stderr,

            "N":
                n,

            "DATA_W":
                data_w,

            "ACC_W":
                acc_w,

            "functional_verified":
                sim.returncode == 0,
        }


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--n",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--data-w",
        type=int,
        default=8,
    )

    parser.add_argument(
        "--acc-w",
        type=int,
        default=32,
    )

    parser.add_argument(
        "--hop-latency",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--boundary-registers",
        type=int,
        choices=[0, 1],
        default=0,
    )

    parser.add_argument(
        "--random-cases",
        type=int,
        default=25,
    )

    parser.add_argument(
        "--pe",
        default="rtl/accelclosure_ws_pe.sv",
    )

    parser.add_argument(
        "--array",
        default="rtl/accelclosure_ws_array.sv",
    )

    parser.add_argument(
        "--report",
        default=None,
    )

    args = parser.parse_args()

    if args.n > 32:
        raise RuntimeError(
            "Current valid-mask harness supports N <= 32"
        )

    pe_path = PROJECT_ROOT / args.pe
    array_path = PROJECT_ROOT / args.array

    cpp = cpp_harness(
        n=args.n,
        data_w=args.data_w,
        acc_w=args.acc_w,
        hop_latency=args.hop_latency,
        boundary_registers=bool(
            args.boundary_registers
        ),
        random_cases=args.random_cases,
    )

    print(
        "[AccelClosure] Dispatching "
        f"N={args.n} parametric signed GEMM regression..."
    )

    report = get(
        verilator_parametric.chia_remote(
            pe_path.read_text(),
            array_path.read_text(),
            cpp,
            args.n,
            args.data_w,
            args.acc_w,
        )
    )

    report.update(
        {
            "pe_hop_latency":
                args.hop_latency,

            "boundary_registers":
                bool(args.boundary_registers),

            "random_cases":
                args.random_cases,

            "random_seed":
                "0xACCE1",
        }
    )

    if args.report:
        report_path = (
            PROJECT_ROOT
            / args.report
        )
    else:
        report_path = (
            PROJECT_ROOT
            / "results"
            / (
                "verilator_parametric_"
                f"n{args.n}_report.json"
            )
        )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
        )
        + "\n"
    )

    print(
        "[AccelClosure] PARAMETRIC_REGRESSION_STATUS:",
        report["status"],
    )

    if report.get("simulation_stdout"):
        print()
        print("========== SIMULATION ==========")
        print(
            report["simulation_stdout"]
        )

    if report.get("build_stderr"):
        print()
        print("========== BUILD STDERR ==========")
        print(
            report["build_stderr"]
        )

    if report.get("simulation_stderr"):
        print()
        print("========== SIMULATION STDERR ==========")
        print(
            report["simulation_stderr"]
        )

    print(
        f"[AccelClosure] Report: {report_path}"
    )

    return (
        0
        if report["status"] == "PASS"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
