# PDS2024.2 Fabric Debugger; future authorized capture configuration only.
# First import the FIC matched to this exact bitstream. No connect, scan, program or Run here.
dbg_fla_set_trig_cond -device 0 -fla 0 -select TriggerCondition0 -set {TU2} -active TriggerCondition0
dbg_fla_set_capture -device 0 -fla 0 -type W -windows 1 -position 256
dbg_fla_set_stor_cond -device 0 -fla 0 -storage {TU4}
