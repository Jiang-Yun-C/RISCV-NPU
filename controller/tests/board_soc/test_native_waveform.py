"""Mutated native traces must fail without relying on simulator assertions."""
import tempfile,unittest
from pathlib import Path
from native_waveform import check_native_waveform

class NativeVCD(unittest.TestCase):
    def trace(self,identity=0,initialised=1,read_data=0x04030201):
        signals=['clk','reset','ddr_init_done','d_awvalid','d_awready','d_awaddr','d_awid','d_awlen','d_wready','d_wlast','d_wdata','d_wstrb','d_arvalid','d_arready','d_araddr','d_arid','d_arlen','d_rvalid','d_rid','d_rlast','d_rdata']
        ids={n:'s'+str(i) for i,n in enumerate(signals)}
        result='$scope module tb_cpu $end\n'+''.join(f'$var wire 256 {ids[n]} {n} $end\n' for n in signals)+'$upscope $end\n$enddefinitions $end\n'
        def at(time,values):return '#'+str(time)+'\n'+''.join(f'b{v:b} {ids[n]}\n' for n,v in values.items())
        result+=at(0,{n:0 for n in signals})
        result+=at(1000,dict(ddr_init_done=initialised,d_awvalid=1,d_awready=1,d_awid=identity))
        result+=at(5000,dict(clk=1))
        result+=at(10000,dict(clk=0,d_awvalid=0,d_wready=1,d_wlast=1,d_wdata=0x04030201,d_wstrb=15))
        result+=at(15000,dict(clk=1))
        result+=at(20000,dict(clk=0,d_wready=0,d_arvalid=1,d_arready=1))
        result+=at(25000,dict(clk=1))
        result+=at(30000,dict(clk=0,d_arvalid=0,d_rvalid=1,d_rlast=1,d_rdata=read_data))
        result+=at(35000,dict(clk=1))+at(40000,dict(clk=0,d_rvalid=0))
        return result
    def run_trace(self,**kw):
        with tempfile.TemporaryDirectory() as td:
            (Path(td)/'cpu.vcd').write_text(self.trace(**kw));return check_native_waveform(td)
    def test_masked_bytes_visible(self):self.assertEqual(self.run_trace()['visible_bytes'],4)
    def test_nonmasked_bytes_are_not_assumed(self):self.assertEqual(self.run_trace(read_data=0x123400000004030201)['visible_bytes'],4)
    def test_wrong_id(self):
        with self.assertRaisesRegex(ValueError,'ID must be zero'):self.run_trace(identity=2)
    def test_before_initialisation(self):
        with self.assertRaisesRegex(ValueError,'before init'):self.run_trace(initialised=0)
    def test_corrupt_readback(self):
        with self.assertRaisesRegex(ValueError,'masked write readback'):self.run_trace(read_data=0x04030200)

if __name__=='__main__':unittest.main()
