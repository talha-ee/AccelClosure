export PLATFORM        = sky130hd

export DESIGN_NAME     = accelclosure_ws_array
export DESIGN_NICKNAME = accelclosure_ws_array

export VERILOG_FILES = \
  /workspace/AccelClosure/rtl/accelclosure_ws_pe.sv \
  /workspace/AccelClosure/rtl/accelclosure_ws_array.sv

export SDC_FILE = \
  /workspace/AccelClosure/configs/orfs/sky130hd/iter0_150mhz/constraint.sdc

# Conservative starting point for a regular 16x16 compute fabric.
# These are implementation knobs, not measured results.
export CORE_UTILIZATION = 35
export PLACE_DENSITY    = 0.55

export TNS_END_PERCENT = 100
