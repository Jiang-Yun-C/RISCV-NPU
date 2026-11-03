# Demo V6 machine state and application interrupt contract

This independent candidate extends Demo V5. `t27/cpu/T09Cpu.v` is the selected
generated CPU; `cpu_gen/generated/` is retained historical comparison output.
Rebuild with `scripts/build_cpu_variants.py --variant lru_btb --output NEW_DIR`.
The pinned VexRiscv archive, patches 001–003 and GenT09 are the complete inputs.
The configuration remains RV32IMF, M only, IALIGN=32, 16KiB two-way I/D caches,
32-byte lines, per-set LRU and the existing BTB. No U/S, A, C, MMU, PMP or NMI
extension is claimed. Directed verification is not RISC-V certification.

The normative reference is the RISC-V privileged architecture, machine chapter,
version 1.13: https://docs.riscv.org/reference/isa/priv/machine.html and the
CSR allocation chapter https://docs.riscv.org/reference/isa/priv/priv-csrs.html.
The implemented profile covers instruction misalignment/access faults, illegal
instructions and CSR accesses, EBREAK, load/store misalignment/access faults,
M ECALL, MRET and machine external/software/timer input interrupts.

Stores are serialized in WriteBack through their own AXI B handshake. They
cannot retire, update a cache hit, or allow a younger store before completion.
BRESP errors raise cause 7 with the store PC and effective address. Misaligned
stores never issue a bus command. A rejected local LED register operation has
no side effect. AXI itself does not guarantee rollback of an arbitrary failing
slave; this CPU never retries a failed store or claims to undo external effects.
Successful stores gain the response wait; the delivery records the measured
short-test cost separately from the retained physical CoreMark score.

MSTATUS implements MIE/MPIE, fixed MPP=3 in this M-only profile and existing F
state. MRET restores MIE and sets MPIE, retaining MPP=3. MEPC low two bits are
zero, MTVEC is direct and aligned. MCAUSE and MTVAL are writable; interrupt
MTVAL and M ECALL MTVAL become zero, EBREAK MTVAL is its PC. Illegal-instruction
MTVAL contains the encoding. MIE has bits 3/7/11; MIP bits come from device
inputs, and CSR writes do not change those inputs. External > software > timer
is the CPU interrupt priority; synchronous exceptions take precedence.
Mvendorid/Marchid/Mhartid are zero, Mimpid is 0x20261102, Mconfigptr is zero.
MCYCLE[H]/MINSTRET[H] are writable; MCOUNTINHIBIT has CY/IR, other bits zero.
MSTATUSH is WARL zero. Existing FCSR/FRM/FFLAGS behavior is retained.

The authenticated loader starts with MIE and MIE-source masks disabled. Only
the initialized application calls `nx_irq_start`. UART and CE share MEIP;
the existing local mtime/mtimecmp now drives MTIP instead of a synthetic pulse.
UART RX mask is 0x100000c4, and 0x100000c8 clears framing/overflow status (bits
2/3). Data remains at 0x100000c0; status at 0x10000004. Hardware errors win
simultaneous clear. The ISR drains at most 64 bytes into an 8192-byte SPSC ring.
Overflow/error poisons and discards the affected input; no suffix becomes an
LED command. Parsing and cancellation remain in the production main loop.

CE IRQ pending/mask remain 0x1000010c/0x10000114. A new backend edge wins a
simultaneous clear. ISR masks the notification and records an event; it does
not clear the completion, ACK a generation, release owner, or reuse storage.
The production driver arms before its doorbell, consumes the event after a
verified acquire, and retains all epoch/session/native1024/ACK boundaries.
WFI checks the event under global MIE masking; individual enabled pending bits
still wake WFI, and the 1ms timer bounds fault/timeout inspection.

`:blink MASK PERIOD_MS EDGES` starts board scheduling (EDGES=0 means continuous,
PERIOD_MS 10..60000, MASK subset 0x2d). `:blinkstop` turns off the active blink
mask and leaves it owned. A valid new direct/model LED write cancels the old
schedule before read/modify/commit, so an old tick cannot overwrite a new off.
The timer ISR performs bounded integer scheduling and at most one LED MMIO
commit. It never transmits UART, waits for DMA or calls the model. Missed ticks
coalesce by absolute deadline, with wrap-safe 32-bit millisecond differences.
Ordinary questions never enter the LED action parser.

The trap frame is 80 bytes plus the measured C/libgcc stack. All caller-saved
integer registers are preserved; callees preserve the ABI's remaining GPRs.
FS is Off during the ISR and restored before MRET. The ISR's disassembly must
contain no floating instruction. Interrupt nesting is disabled. Software event
observation is at 0x10000420; probes are passive and add one sample-register cycle.

LED bank addresses, channels 0/2/3/5 (A20/C19/E18/A18), active-high display mux,
125MHz clocks, DDR contract and physical pins remain those of Demo V5. Digital
readback proves the CPU register/output chain, not optical polarity or waveform.
