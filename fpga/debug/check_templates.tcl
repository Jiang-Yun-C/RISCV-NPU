proc dbg_fla_set_trig_cond {args} {if {[llength $args]!=10} {error "condition arguments"}}
proc dbg_fla_set_capture {args} {if {[llength $args]!=10} {error "capture arguments"}}
proc dbg_fla_set_stor_cond {args} {if {[llength $args]!=6} {error "storage arguments"}}
source {/home/Jiang/RISCV+NPU/evidence/DEMO_V6_IRQ/20261102-v1/debug-delivery/led_commit.tcl}
source {/home/Jiang/RISCV+NPU/evidence/DEMO_V6_IRQ/20261102-v1/debug-delivery/npu_irq.tcl}
source {/home/Jiang/RISCV+NPU/evidence/DEMO_V6_IRQ/20261102-v1/debug-delivery/uart_cancel.tcl}
source {/home/Jiang/RISCV+NPU/evidence/DEMO_V6_IRQ/20261102-v1/debug-delivery/store_fault.tcl}
puts TEMPLATE_SYNTAX_PASS
