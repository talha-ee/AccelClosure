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

RTL_DIR = PROJECT_ROOT / "rtl"
RESULTS_DIR = PROJECT_ROOT / "results"


CPP_TEST = r'''
#include "Vaccelclosure_ws_array.h"
#include "verilated.h"

#include <array>
#include <cstdint>
#include <iostream>
#include <random>


static constexpr int N = 4;
static constexpr int NUM_RANDOM_TESTS = 25;


static void zero_psum_input(
    Vaccelclosure_ws_array *dut
) {
    for (int i = 0; i < 4; ++i) {
        dut->psum_data_in[i] = 0;
    }
}


static void clear_inputs(
    Vaccelclosure_ws_array *dut
) {
    dut->weight_load_valid = 0;
    dut->weight_load_row = 0;
    dut->weight_load_data = 0;

    dut->act_valid_in = 0;
    dut->act_data_in = 0;

    dut->psum_valid_in = 0;

    zero_psum_input(dut);
}


static void tick(
    Vaccelclosure_ws_array *dut
) {
    dut->clk = 0;
    dut->eval();

    dut->clk = 1;
    dut->eval();

    dut->clk = 0;
    dut->eval();
}


static uint32_t pack_i8x4(
    const std::array<int, N>& lanes
) {
    uint32_t packed = 0;

    for (int lane = 0; lane < N; ++lane) {
        packed |= (
            static_cast<uint32_t>(
                static_cast<uint8_t>(
                    lanes[lane]
                )
            )
            << (8 * lane)
        );
    }

    return packed;
}


static int32_t result_lane(
    Vaccelclosure_ws_array *dut,
    int lane
) {
    uint32_t raw =
        dut->result_data_out[lane];

    return static_cast<int32_t>(raw);
}


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


static Matrix32 reference_gemm(
    const Matrix& A,
    const Matrix& B
) {
    Matrix32 C{};

    for (int i = 0; i < N; ++i) {
        for (int j = 0; j < N; ++j) {

            int32_t sum = 0;

            for (int k = 0; k < N; ++k) {
                sum +=
                    static_cast<int32_t>(A[i][k])
                    *
                    static_cast<int32_t>(B[k][j]);
            }

            C[i][j] = sum;
        }
    }

    return C;
}


static void reset_dut(
    Vaccelclosure_ws_array *dut
) {
    clear_inputs(dut);

    dut->rst_n = 0;

    tick(dut);
    tick(dut);

    dut->rst_n = 1;
}


static void load_weights(
    Vaccelclosure_ws_array *dut,
    const Matrix& B
) {
    clear_inputs(dut);

    dut->weight_load_valid = 1;

    for (int k = 0; k < N; ++k) {

        std::array<int, N> row{};

        for (int j = 0; j < N; ++j) {
            row[j] = B[k][j];
        }

        dut->weight_load_row = k;

        dut->weight_load_data =
            pack_i8x4(row);

        tick(dut);
    }

    // One drain cycle is required because weight loading
    // now passes through the synchronous array boundary.
    clear_inputs(dut);
    tick(dut);
}


static bool run_case(
    Vaccelclosure_ws_array *dut,
    const Matrix& A,
    const Matrix& B,
    int case_index
) {
    reset_dut(dut);
    load_weights(dut, B);

    Matrix32 expected =
        reference_gemm(A, B);

    bool pass = true;

    /*
       Pipeline-aware input schedule:

         PE_HOP_LATENCY = 2
         BOUNDARY_LATENCY = 1

         activation row k:
             i = cycle - 2*k

         initial psum column j:
             i = cycle - 2*j

       The boundary latency is common to both streams,
       so it does not alter their relative skew.

       Output schedule:

             output i,j appears at

             cycle = i + 2*j + 2*N
    */

    static constexpr int PE_HOP_LATENCY = 2;

    const int last_cycle =
        (N - 1)
        + PE_HOP_LATENCY * (N - 1)
        + PE_HOP_LATENCY * N;

    for (
        int cycle = 0;
        cycle <= last_cycle;
        ++cycle
    ) {
        clear_inputs(dut);

        uint32_t act_valid = 0;
        uint32_t act_packed = 0;

        for (int k = 0; k < N; ++k) {

            int i =
                cycle
                - PE_HOP_LATENCY * k;

            if (i >= 0 && i < N) {

                act_valid |= (1u << k);

                act_packed |= (
                    static_cast<uint32_t>(
                        static_cast<uint8_t>(
                            A[i][k]
                        )
                    )
                    << (8 * k)
                );
            }
        }

        dut->act_valid_in = act_valid;
        dut->act_data_in = act_packed;

        uint32_t psum_valid = 0;

        for (int j = 0; j < N; ++j) {

            int i =
                cycle
                - PE_HOP_LATENCY * j;

            if (i >= 0 && i < N) {
                psum_valid |= (1u << j);
            }
        }

        dut->psum_valid_in = psum_valid;

        // All injected starting partial sums are zero.
        zero_psum_input(dut);

        tick(dut);

        uint32_t expected_valid = 0;

        for (int j = 0; j < N; ++j) {

            int i =
                cycle
                - PE_HOP_LATENCY * N
                - PE_HOP_LATENCY * j;

            if (i >= 0 && i < N) {

                expected_valid |=
                    (1u << j);

                int32_t got =
                    result_lane(
                        dut,
                        j
                    );

                int32_t exp =
                    expected[i][j];

                if (got != exp) {

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
                }
            }
        }

        uint32_t actual_valid =
            static_cast<uint32_t>(
                dut->result_valid_out
            );

        if (
            actual_valid
            != expected_valid
        ) {
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
        }
    }

    clear_inputs(dut);
    tick(dut);

    if (dut->result_valid_out != 0) {

        std::cerr
            << "FAIL case="
            << case_index
            << ": pipeline did not drain"
            << std::endl;

        pass = false;
    }

    return pass;
}


int main(
    int argc,
    char **argv
) {
    Verilated::commandArgs(
        argc,
        argv
    );

    auto *dut =
        new Vaccelclosure_ws_array;

    bool all_pass = true;
    int passed = 0;

    // -------------------------------------------------
    // Directed signed test.
    // -------------------------------------------------

    Matrix directed_A = {{
        {{  1,   2,  -3,   4}},
        {{ -5,   6,   7,  -8}},
        {{  9, -10,  11,  12}},
        {{-13,  14, -15,  16}}
    }};

    Matrix directed_B = {{
        {{  5,  -6,   7,   8}},
        {{ -9,  10, -11,  12}},
        {{ 13,  14, -15, -16}},
        {{ 17, -18,  19,  20}}
    }};

    if (
        run_case(
            dut,
            directed_A,
            directed_B,
            0
        )
    ) {
        ++passed;
    } else {
        all_pass = false;
    }

    // -------------------------------------------------
    // Deterministic random signed INT8 regression.
    // -------------------------------------------------

    std::mt19937 rng(
        0xACCE1
    );

    std::uniform_int_distribution<int>
        dist(-128, 127);

    for (
        int test = 1;
        test <= NUM_RANDOM_TESTS;
        ++test
    ) {
        Matrix A{};
        Matrix B{};

        for (int i = 0; i < N; ++i) {
            for (int j = 0; j < N; ++j) {

                A[i][j] =
                    dist(rng);

                B[i][j] =
                    dist(rng);
            }
        }

        if (
            run_case(
                dut,
                A,
                B,
                test
            )
        ) {
            ++passed;
        } else {
            all_pass = false;
        }
    }

    std::cout
        << "REGRESSION_CASES_PASSED="
        << passed
        << "/"
        << (NUM_RANDOM_TESTS + 1)
        << std::endl;

    if (all_pass) {
        std::cout
            << "ACCELCLOSURE_RANDOM_GEMM_PASS"
            << std::endl;
    } else {
        std::cout
            << "ACCELCLOSURE_RANDOM_GEMM_FAIL"
            << std::endl;
    }

    dut->final();
    delete dut;

    return all_pass ? 0 : 1;
}
'''


@ChiaFunction(
    resources={"verilator_run": 1}
)
def verilator_regression(
    pe_rtl: str,
    array_rtl: str,
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
        cpp.write_text(CPP_TEST)

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
            "-GN=4",
            "-GDATA_W=8",
            "-GACC_W=32",
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
                "returncode":
                    build.returncode,
                "build_stdout":
                    build.stdout,
                "build_stderr":
                    build.stderr,
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
            "N": 4,
            "DATA_W": 8,
            "ACC_W": 32,
            "directed_cases": 1,
            "random_cases": 25,
            "random_seed":
                "0xACCE1",
            "functional_verified":
                sim.returncode == 0,
        }


def main():

    pe_path = (
        RTL_DIR
        / "accelclosure_ws_pe.sv"
    )

    array_path = (
        RTL_DIR
        / "accelclosure_ws_array.sv"
    )

    print(
        "[AccelClosure] Dispatching "
        "randomized signed GEMM regression..."
    )

    report = get(
        verilator_regression.chia_remote(
            pe_path.read_text(),
            array_path.read_text(),
        )
    )

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path = (
        RESULTS_DIR
        / "verilator_regression_report.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
        )
    )

    print(
        "[AccelClosure] REGRESSION_STATUS:",
        report["status"],
    )

    if report.get(
        "build_stderr"
    ):
        print(
            "\n========== BUILD STDERR =========="
        )
        print(
            report["build_stderr"]
        )

    if report.get(
        "simulation_stdout"
    ):
        print(
            "\n========== SIMULATION STDOUT =========="
        )
        print(
            report["simulation_stdout"]
        )

    if report.get(
        "simulation_stderr"
    ):
        print(
            "\n========== SIMULATION STDERR =========="
        )
        print(
            report["simulation_stderr"]
        )

    print(
        "[AccelClosure] REPORT:",
        report_path,
    )

    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
