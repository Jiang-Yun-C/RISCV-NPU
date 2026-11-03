"""Create an explicit test-only SRAM router around the unchanged CPU ports."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[2]
def generate(cpu_path=None):
    cpu=Path(cpu_path or ROOT/'t27/cpu/T09Cpu.v').read_text();head=cpu[cpu.index('module T09Cpu ('):cpu.index(');')+2]
    ports=re.findall(r'(input|output)\s+wire\s*(\[[^]]+\])?\s*(\w+)\s*(?:,|\n)',head)
    if not ports or len(ports)<50:raise ValueError('CPU port parse failed')
    head=head.replace('module T09Cpu (','module T09CpuLocal #(parameter bit LOCAL_READ_PIPELINE=1) (').replace('  input  wire          reset\n','  input  wire          reset,\n  output wire local_i_r_fire,local_d_r_fire,local_d_w_fire\n')
    lines=[head]
    for direction,width,name in ports:
        if name.startswith(('iAxi_','dAxi_')):lines.append(f'  wire {width or ""} c_{name};')
    lines.append('  T09Cpu cpu('+','.join(f'.{name}('+('c_' if name.startswith(('iAxi_','dAxi_')) else '')+name+')' for _,_,name in ports)+');')
    lines.append('  axi4_if #(.DATA_W(32),.ID_W(1)) ci(clk),cd(clk),ei(clk),ed(clk),li(clk),ld(clk);')
    lines.append('  axi4_if #(.DATA_W(128),.ID_W(6)) ln(clk);')
    field={'addr':'addr','len':'len','size':'size','burst':'burst','data':'data','strb':'strb','resp':'resp','last':'last'}
    for port,cp,ep in [('i','ci','ei'),('d','cd','ed')]:
        prefix=port+'Axi_'
        for direction,width,name in ports:
            if not name.startswith(prefix):continue
            if name.endswith(('payload_cache','payload_prot')):
                lines.append(f'  assign {name}=c_{name};');continue
            suffix=name[len(prefix):];channel,signal=suffix.split('_',1)
            signal=signal.removeprefix('payload_');bus_signal=channel+signal
            if direction=='output':lines.extend([f'  assign {cp}.{bus_signal}=c_{name};',f'  assign {name}={ep}.{bus_signal};'])
            else:lines.extend([f'  assign c_{name}={cp}.{bus_signal};',f'  assign {ep}.{bus_signal}={name};'])
        if port=='i':
            for bus in [cp]:
                for sig,val in [('awvalid',0),('awaddr',0),('awlen',0),('awsize',2),('awburst',1),('wvalid',0),('wdata',0),('wstrb',0),('wlast',1),('bready',1),('arid',0),('awid',0),('arsize',2)]:lines.append(f'  assign {bus}.{sig}={val};')
            for sig,val in [('awready',0),('wready',0),('bvalid',0),('bresp',0),('bid',0),('rid',0)]:lines.append(f'  assign {ep}.{sig}={val};')
        else:
            for sig,val in [('arid',0),('awid',0),('arburst',1),('awburst',1)]:lines.append(f'  assign {cp}.{sig}={val};')
            for sig,val in [('rid',0),('bid',0)]:lines.append(f'  assign {ep}.{sig}={val};')
        lines.append(f"  nx_test_sram_route #(.MMIO_BASE(32'h20000)) {port}route(.clk,.reset,.cpu_bus({cp}),.memory_bus({ep}),.uart_bus({'li' if port=='i' else 'ld'}));")
    lines.append('  wire tx,sealed,platform_reset,exited;wire [31:0] unused_rom,profile,exit_code,report;')
    lines.append("  nx_ce64_local #(.LOCAL_READ_PIPELINE(LOCAL_READ_PIPELINE),.REQUEST_PMU(0)) local_memory(.clk,.reset_n(!reset),.ddr_init_done(1'b1),.uart_rx(1'b1),.platform_ready(1'b1),.platform_status(32'b0),.telemetry(4096'b0),.uart_tx(tx),.rom_enable(1'b0),.rom_address(32'b0),.rom_data(unused_rom),.model_sealed(sealed),.selected_profile(profile),.platform_reset_request(platform_reset),.exit_code,.report_tag(report),.exited,.local_i(li),.local_d(ld),.local_n(ln));")
    for sig,val in [('awvalid',0),('awaddr',0),('awlen',0),('awsize',4),('awburst',1),('awid',0),('wvalid',0),('wdata',0),('wstrb',0),('wlast',1),('bready',1),('arvalid',0),('araddr',0),('arid',0),('arlen',0),('arsize',4),('arburst',1),('rready',1)]:lines.append(f'  assign ln.{sig}={val};')
    lines.extend(['  assign local_i_r_fire=li.rvalid&&li.rready;','  assign local_d_r_fire=ld.rvalid&&ld.rready;','  assign local_d_w_fire=ld.wvalid&&ld.wready;','endmodule'])
    router=(ROOT/'rtl/soc/t17_uart_router.sv').read_text().replace('module t17_uart_router','module nx_test_sram_route').replace('MMIO_BASE+256','MMIO_BASE+65536')
    return '\n'.join(lines)+'\n'+router
if __name__=='__main__':print(generate())
