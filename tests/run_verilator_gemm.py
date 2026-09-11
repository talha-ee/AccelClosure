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

#include <cstdint>
#include <iostream>


static void clear_inputs(Vaccelclosure_ws_array *dut) {
    dut->weight_load_valid = 0;
    dut->weight_load_row = 0;
    dut->weight_load_data = 0;

    dut->act_valid_in = 0;
    dut->act_data_in = 0;

    dut->psum_valid_in = 0;
    dut->psum_data_in = 0;
}


static void tick(Vaccelclosure_ws_array *dut) {
    dut->clk = 0;
    dut->eval();

    dut->clk = 1;
    dut->eval();

    dut->clk = 0;
    dut->eval();
}


static uint16_t pack_i8(int lane0, int lane1) {
    uint16_t x = 0;

    x |= static_cast<uint8_t>(lane0);
    x |= static_cast<uint16_t>(
        static_cast<uint8_t>(lane1)
    ) << 8;

    return x;
}


static int32_t get_i32_lane(
    uint64_t packed,
    int lane
) {
    uint32_t raw =
        static_cast<uint32_t>(
            (packed >> (32 * lane))
            & 0xffffffffULL
        );

    return static_cast<int32_t>(raw);
}


static bool check_result(
    Vaccelclosure_ws_array *dut,
    int compute_cycle
) {
    bool ok = true;

    uint32_t valid = dut->result_valid_out;
    uint64_t data = dut->result_data_out;

    std::cout
        << "CYCLE "
        << compute_cycle
        << " VALID=0x"
        << std::hex
        << valid
        << std::dec;

    if (valid & 0x1) {
        std::cout
            << " COL0="
            << get_i32_lane(data, 0);
    }

    if (valid & 0x2) {
        std::cout
            << " COL1="
            << get_i32_lane(data, 1);
    }

    std::cout << std::endl;

    // Expected wavefront:
    //
    // cycle 1:
    //   C[0][0] = 19
    //
    // cycle 2:
    //   C[1][0] = 13
    //   C[0][1] = 10
    //
    // cycle 3:
    //   C[1][1] = 50

    if (compute_cycle == 0) {
        if (valid != 0) {
            std::cerr
                << "FAIL: unexpected result at cycle 0"
                << std::endl;
            ok = false;
        }
    }

    if (compute_cycle == 1) {
        if ((valid & 0x1) == 0) {
            std::cerr
                << "FAIL: C[0][0] valid missing"
                << std::endl;
            ok = false;
        } else if (
            get_i32_lane(data, 0) != 19
        ) {
            std::cerr
                << "FAIL: C[0][0] expected 19, got "
                << get_i32_lane(data, 0)
                << std::endl;
            ok = false;
        }

        if (valid & 0x2) {
            std::cerr
                << "FAIL: unexpected column-1 result"
                << std::endl;
            ok = false;
        }
    }

    if (compute_cycle == 2) {
        if ((valid & 0x3) != 0x3) {
            std::cerr
                << "FAIL: expected both result columns valid"
                << std::endl;
            ok = false;
        }

        if (
            (valid & 0x1)
            && get_i32_lane(data, 0) != 13
        ) {
            std::cerr
                << "FAIL: C[1][0] expected 13, got "
                << get_i32_lane(data, 0)
                << std::endl;
            ok = false;
        }

        if (
            (valid & 0x2)
            && get_i32_lane(data, 1) != 10
        ) {
            std::cerr
                << "FAIL: C[0][1] expected 10, got "
                << get_i32_lane(data, 1)
                << std::endl;
            ok = false;
        }
    }

    if (compute_cycle == 3) {
        if ((valid & 0x2) == 0) {
            std::cerr
                << "FAIL: C[1][1] valid missing"
                << std::endl;
            ok = false;
        } else if (
            get_i32_lane(data, 1) != 50
        ) {
            std::cerr
                << "FAIL: C[1][1] expected 50, got "
                << get_i32_lane(data, 1)
                << std::endl;
            ok = false;
        }

        if (valid & 0x1) {
            std::cerr
                << "FAIL: unexpected column-0 result"
                << std::endl;
            ok = false;
        }
    }

    return ok;
}


int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);

    Vaccelclosure_ws_array *dut =
        new Vaccelclosure_ws_array;

    clear_inputs(dut);

    // Reset.
    dut->rst_n = 0;
    tick(dut);
    tick(dut);

    dut->rst_n = 1;

    // -------------------------------------------------
    // Load stationary matrix B:
    //
    // B = [ 5  -6 ]
    //     [ 7   8 ]
    //
    // weight_load_row = k
    // -------------------------------------------------

    dut->weight_load_valid = 1;

    dut->weight_load_row = 0;
    dut->weight_load_data =
        pack_i8(5, -6);
    tick(dut);

    dut->weight_load_row = 1;
    dut->weight_load_data =
        pack_i8(7, 8);
    tick(dut);

    dut->weight_load_valid = 0;
    dut->weight_load_data = 0;

    bool pass = true;

    // -------------------------------------------------
    // A = [  1  2 ]
    //     [ -3  4 ]
    //
    // Systolic schedule:
    //
    // cycle 0:
    //   row0 <- A00 = 1
    //   col0 <- psum 0
    //
    // cycle 1:
    //   row1 <- A01 = 2
    //   row0 <- A10 = -3
    //   col1 <- psum 0 for output row 0
    //   col0 <- psum 0 for output row 1
    //
    // cycle 2:
    //   row1 <- A11 = 4
    //   col1 <- psum 0 for output row 1
    //
    // -------------------------------------------------

    // Compute cycle 0.
    clear_inputs(dut);

    dut->act_valid_in = 0x1;
    dut->act_data_in =
        pack_i8(1, 0);

    dut->psum_valid_in = 0x1;
    dut->psum_data_in = 0;

    tick(dut);

    pass &= check_result(
        dut,
        0
    );

    // Compute cycle 1.
    clear_inputs(dut);

    dut->act_valid_in = 0x3;
    dut->act_data_in =
        pack_i8(-3, 2);

    dut->psum_valid_in = 0x3;
    dut->psum_data_in = 0;

    tick(dut);

    pass &= check_result(
        dut,
        1
    );

    // Compute cycle 2.
    clear_inputs(dut);

    dut->act_valid_in = 0x2;
    dut->act_data_in =
        pack_i8(0, 4);

    dut->psum_valid_in = 0x2;
    dut->psum_data_in = 0;

    tick(dut);

    pass &= check_result(
        dut,
        2
    );

    // Compute cycle 3: drain.
    clear_inputs(dut);
    tick(dut);

    pass &= check_result(
        dut,
        3
    );

    // One final idle cycle must produce no valid result.
    clear_inputs(dut);
    tick(dut);

    if (dut->result_valid_out != 0) {
        std::cerr
            << "FAIL: result_valid_out did not drain"
            << std::endl;
        pass = false;
    }

    if (pass) {
        std::cout
            << "ACCELCLOSURE_GEMM_PASS"
            << std::endl;
    } else {
        std::cout
            << "ACCELCLOSURE_GEMM_FAIL"
            << std::endl;
    }

    dut->final();
    delete dut;

    return pass ? 0 : 1;
}
'''


@ChiaFunction(resources={"verilator_run": 1})
def verilator_gemm_test(
    pe_rtl: str,
    array_rtl: str,
) -> dict:

    verilator = shutil.which("verilator")

    if verilator is None:
        return {
            "status": "TOOL_NOT_FOUND",
            "returncode": -1,
            "build_stdout": "",
            "build_stderr": "verilator not found",
            "simulation_stdout": "",
            "simulation_stderr": "",
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
            "-GN=2",
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
                "returncode": build.returncode,
                "build_stdout": build.stdout,
                "build_stderr": build.stderr,
                "simulation_stdout": "",
                "simulation_stderr": "",
                "command": build_cmd,
            }

        binary = (
            obj_dir
            / "Vaccelclosure_ws_array"
        )

        simulation = subprocess.run(
            [str(binary)],
            capture_output=True,
            text=True,
        )

        return {
            "status": (
                "PASS"
                if simulation.returncode == 0
                else "FAIL"
            ),
            "returncode":
                simulation.returncode,
            "build_stdout":
                build.stdout,
            "build_stderr":
                build.stderr,
            "simulation_stdout":
                simulation.stdout,
            "simulation_stderr":
                simulation.stderr,
            "verilator_path":
                verilator,
            "parameter_N": 2,
            "data_width": 8,
            "acc_width": 32,
            "matrix_A": [
                [1, 2],
                [-3, 4],
            ],
            "matrix_B": [
                [5, -6],
                [7, 8],
            ],
            "expected_C": [
                [19, 10],
                [13, 50],
            ],
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
        "functional GEMM verification..."
    )

    report = get(
        verilator_gemm_test.chia_remote(
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
        / "verilator_gemm_report.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
        )
    )

    print(
        "[AccelClosure] FUNCTIONAL_STATUS:",
        report["status"],
    )

    if report.get("build_stderr"):
        print(
            "\n========== BUILD STDERR =========="
        )
        print(
            report["build_stderr"]
        )

    if report.get("simulation_stdout"):
        print(
            "\n========== SIMULATION STDOUT =========="
        )
        print(
            report["simulation_stdout"]
        )

    if report.get("simulation_stderr"):
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
