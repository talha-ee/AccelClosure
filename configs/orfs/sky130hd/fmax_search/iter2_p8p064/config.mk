export PLATFORM        = sky130hd

export DESIGN_NAME     = accelclosure_ws_array
export DESIGN_NICKNAME = accelclosure_ws_array

export VERILOG_FILES = \
  /workspace/AccelClosure/rtl/accelclosure_ws_pe.sv \
  /workspace/AccelClosure/rtl/accelclosure_ws_array.sv

export SDC_FILE = \
  /workspace/AccelClosure/configs/orfs/sky130hd/fmax_search/iter2_p8p064/constraint.sdc

export CORE_UTILIZATION = 35
export PLACE_DENSITY    = 0.55

export TNS_END_PERCENT = 100
