// Exercise the real synthesizable pack through Verilator, including stage order.
#include "Vt09_ila_probe_pack.h"
#include "verilated.h"
#include <iostream>
#include <stdexcept>

static uint32_t bits(const Vt09_ila_probe_pack &p,unsigned low,unsigned width) {
    uint32_t value=0;
    for(unsigned b=0;b<width;b++)value|=((p.probe[(low+b)/32]>>((low+b)%32))&1u)<<b;
    return value;
}
static void check(bool pass){if(!pass)throw std::runtime_error("probe bit contract mismatch");}
int main(int argc,char **argv) {
    Verilated::commandArgs(argc,argv);
    Vt09_ila_probe_pack p;
    p.fetch_response_pc=0x10203040;p.decode_pc=0x50607080;p.execute_pc=0x90a0b0c0;
    p.memory_pc=0xd0e0f001;p.writeback_pc=0x23456789;p.retire_instruction=0xabcdef01;
    p.valid_mask=0;p.stuck_mask=0;p.fire_mask=0;p.remove_mask=0;p.fetch_flush=0;
    p.retire=0;p.execute_stall=0;p.conditional_branch=0;p.mispredict=0;
    p.pending_writes=0;p.data_bus_hazard=0;p.data_refilling=0;
    p.execute_memory_enable=0;p.execute_memory_write=0;
    p.axi_fire_mask=0;p.axi_backpressure_mask=0;
    p.i_r_valid=0;p.d_r_valid=0;p.d_b_valid=0;p.reset=0;
    p.i_r_last=0;p.d_r_last=0;p.rom_enable=0;p.eval();
    check(bits(p,0,32)==0x10203040&&bits(p,32,32)==0x50607080&&bits(p,64,32)==0x90a0b0c0);
    check(bits(p,96,32)==0xd0e0f001&&bits(p,128,32)==0x23456789&&bits(p,160,32)==0xabcdef01);
    check(bits(p,192,32)==0&&bits(p,224,32)==0);
    for(unsigned stage=0;stage<5;stage++) {
        p.valid_mask=p.stuck_mask=p.fire_mask=1u<<stage;p.eval();
        check(bits(p,192,5)==(1u<<stage)&&bits(p,197,5)==(1u<<stage)&&bits(p,202,5)==(1u<<stage));
    }
    p.valid_mask=0x15;p.stuck_mask=4;p.fire_mask=0x11;p.remove_mask=0xa;
    p.fetch_flush=p.retire=p.execute_stall=p.conditional_branch=p.mispredict=1;
    p.pending_writes=5;p.data_bus_hazard=p.data_refilling=1;
    p.execute_memory_enable=p.execute_memory_write=1;
    p.axi_fire_mask=0x55;p.axi_backpressure_mask=0x2a;
    p.i_r_valid=p.d_r_valid=p.d_b_valid=p.reset=p.i_r_last=p.d_r_last=p.rom_enable=1;
    p.eval();
    check(bits(p,192,5)==0x15&&bits(p,197,5)==4&&bits(p,202,5)==0x11&&bits(p,207,4)==0xa);
    check(bits(p,211,5)==31&&bits(p,216,3)==5&&bits(p,219,4)==15);
    check(bits(p,223,7)==0x55&&bits(p,230,7)==0x2a&&bits(p,237,7)==127&&bits(p,244,12)==0);
    p.final();
    std::cout<<"PASS passive ILA pack: six PC/instruction words, all five stage flag positions, control/AXI boundaries and reserved zeros\n";
}
