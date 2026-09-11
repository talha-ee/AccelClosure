set design_name accelclosure_ws_array

set odb_file \
  /workspace/AccelClosure/orfs_runs/results/sky130hd/accelclosure_ws_array/fmax_iter1_p7p827/1_synth.odb

set sdc_file \
  /workspace/AccelClosure/orfs_runs/results/sky130hd/accelclosure_ws_array/fmax_iter1_p7p827/1_synth.sdc

set liberty_file \
  /OpenROAD-flow-scripts/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

puts "============================================================"
puts " ACCELCLOSURE FMAX SEARCH ITERATION 1"
puts "============================================================"

puts "DESIGN_NAME=$design_name"
puts "SEARCH_PERIOD_NS=7.827"
puts "SEARCH_FREQUENCY_MHZ=127.763"
puts "CORNER=sky130hd_tt_025C_1v80"

read_liberty $liberty_file
read_db $odb_file
read_sdc $sdc_file

source /OpenROAD-flow-scripts/flow/platforms/sky130hd/setRC.tcl

puts ""
puts "================ DESIGN AREA ================="
report_design_area

puts ""
puts "================ DATABASE INSTANCE COUNT ================="
set block [ord::get_db_block]
set inst_count [llength [$block getInsts]]
puts "ACCELCLOSURE_INSTANCE_COUNT=$inst_count"

puts ""
puts "================ CLOCK ================="
report_clock_properties

puts ""
puts "================ WORST SETUP SLACK ================="
report_worst_slack -max

puts ""
puts "================ WNS ================="
report_wns -max

puts ""
puts "================ TNS ================="
report_tns -max

puts ""
puts "================ WORST SETUP PATH ================="
report_checks \
  -path_delay max \
  -group_path_count 1 \
  -endpoint_path_count 1 \
  -sort_by_slack \
  -fields {slew capacitance input_pin net} \
  -digits 4

puts ""
puts "================ MINIMUM CLOCK PERIOD ================="
report_clock_min_period

puts ""
puts "ACCELCLOSURE_FMAX_ITER1_COMPLETE"
