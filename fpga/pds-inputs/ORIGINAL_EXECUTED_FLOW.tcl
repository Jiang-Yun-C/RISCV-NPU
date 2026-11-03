set_arch -input_db_file {/home/Jiang/RISCV+NPU/evidence/DEMO_V6_IRQ/20261102-v1/pds-debug-r10/work/synthesize/test_ddr_syn.adf}
add_constraint {/home/Jiang/RISCV+NPU/evidence/DEMO_V6_IRQ/20261102-v1/pds-debug-r10/work/native110.fdc}
add_constraint {/home/Jiang/RISCV+NPU/evidence/DEMO_V6_IRQ/20261102-v1/pds-debug-r10/work/native-hierarchy.fdc}
puts V6_SYNTH_READY
while {![file exists {/home/Jiang/RISCV+NPU/evidence/DEMO_V6_IRQ/20261102-v1/pds-debug-r10/FABRIC_READY.txt}]} {after 1000}
add_fic {/home/Jiang/RISCV+NPU/evidence/DEMO_V6_IRQ/20261102-v1/pds-debug-r10/irq-debug.fic}
dev_map -force_to_run -input_db_file {/home/Jiang/RISCV+NPU/evidence/DEMO_V6_IRQ/20261102-v1/pds-debug-r10/work/synthesize/test_ddr_syn.adf}
puts V6_DEBUG_MAP_READY
pnr -fix_hold_violation_in_route TRUE -logic_optimize_enable TRUE -logic_optimize_lut6d_combing_strategy 0 -mode performance -gplace_seed 12 -groute_seed 2 -gplace_times 8 -seed_step 1 -saved_outcome 8 -parallel 4 -generate_bitstream FALSE -sort setup -pick_first_timing_convergence_seed TRUE
report_timing
puts V6_ROUTE_COMPLETE
exit
