.text
.macro fault_fn name, instruction
.globl \name
.type \name,@function
\name:
    \instruction
    ret
.endm
.globl f_store_slv,f_store_dec,f_store_cached
f_store_slv:
    li t0,0xbc000100
    li t1,0xdeadbeef
.globl site_store_slv
site_store_slv: sw t1,0(t0)
    ret
f_store_dec:
    li t0,0xbc000104
    li t1,0x12345678
.globl site_store_dec
site_store_dec: sw t1,0(t0)
    ret
f_store_cached:
    li t0,0xb4102000
    lw t1,0(t0)
    li t1,0x87654321
.globl site_store_cached
site_store_cached: sw t1,0(t0)
    ret
.globl f_load_slv,f_load_dec,f_load_cached,f_load_misaligned,f_store_misaligned
f_load_slv:
    li t0,0xbc000200
.globl site_load_slv
site_load_slv: lw t1,0(t0)
    ret
f_load_dec:
    li t0,0xbc000204
.globl site_load_dec
site_load_dec: lw t1,0(t0)
    ret
f_load_cached:
    li t0,0xb4104000
.globl site_load_cached
site_load_cached: lw t1,0(t0)
    ret
f_load_misaligned:
    li t0,0xb4100001
.globl site_load_misaligned
site_load_misaligned: lw t1,0(t0)
    ret
f_store_misaligned:
    li t0,0xb4100001
.globl site_store_misaligned
site_store_misaligned: sw t1,0(t0)
    ret
.globl f_illegal,f_csr,f_readonly,f_ecall,f_ebreak,f_fetch,f_i_misaligned
f_illegal:
.globl site_illegal
site_illegal: .word 0xffffffff
    ret
f_csr:
.globl site_csr
site_csr: csrr t0,0x7ff
    ret
f_readonly:
.globl site_readonly
site_readonly: csrw mvendorid,zero
    ret
f_ecall:
.globl site_ecall
site_ecall: ecall
    ret
f_ebreak:
.globl site_ebreak
site_ebreak: ebreak
    ret
f_fetch:
    li t0,0xbc000000
.globl site_fetch
site_fetch: jr t0
.globl fetch_resume
fetch_resume: ret
f_i_misaligned:
    li t0,0xb4100002
.globl site_i_misaligned
site_i_misaligned: jr t0
    ret

.globl f_store_fp,f_load_fp_misaligned
f_store_fp:
    li t0,0xbc000108
    li t1,0x3f800000
    fmv.w.x f0,t1
.globl site_store_fp
site_store_fp: fsw f0,0(t0)
    ret
f_load_fp_misaligned:
    li t0,0xb4100001
.globl site_load_fp_misaligned
site_load_fp_misaligned: flw f1,0(t0)
    ret
