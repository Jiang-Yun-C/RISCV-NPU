"""Captured CPU readback must be checked even after the backend has halted."""
import json,tempfile,unittest
from pathlib import Path
from waveform import check_waveform

class ReadbackWaveform(unittest.TestCase):
    def capture(self,path):
        header='''$scope module tb_cpu $end
$var wire 1 ! clk $end
$var wire 1 " reset $end
$var wire 2 # owner $end
$scope module cpu_bus $end
$var wire 1 a arvalid $end
$var wire 1 b arready $end
$var wire 32 c araddr $end
$var wire 8 d arlen $end
$var wire 3 e arsize $end
$var wire 1 f rvalid $end
$var wire 1 g rready $end
$var wire 32 h rdata $end
$var wire 2 i rresp $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0"
b00 #
0a
1b
b10101100000100000000000000000000 c
b0 d
b10 e
0f
1g
b1 h
b0 i
'''
        lines=[header]
        for cycle in range(1002):
            lines.append(f'#{cycle*10000}\n0!\n')
            if cycle==1:lines.append('1a\n')
            if cycle==2:lines.append('0a\n1f\n')
            if cycle==3:lines.append('0f\n')
            lines.append(f'#{cycle*10000+5000}\n1!\n')
        (path/'cpu.vcd').write_text(''.join(lines))
        (path/'transactions.csv').write_text('1,CR,ac100000,0,2,0\n2,CD,0,1,0,0\n')
    def test_cpu_only_completion_window(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);self.capture(p);self.assertEqual(check_waveform(p)['handshakes_compared'],2)
    def test_corrupt_readback_payload(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);self.capture(p);(p/'transactions.csv').write_text('1,CR,ac100000,0,2,0\n2,CD,0,2,0,0\n')
            with self.assertRaisesRegex(ValueError,'correlation'):check_waveform(p)
    def test_repeated_dumpon_preserves_window(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);self.capture(p);vcd=p/'cpu.vcd'
            vcd.write_text(vcd.read_text().replace('\n0!\n','\n0!\n$dumpon\n$end\n'))
            self.assertEqual(check_waveform(p)['handshakes_compared'],2)
    def test_missing_read_response(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);self.capture(p);(p/'transactions.csv').write_text('1,CR,ac100000,0,2,0\n')
            with self.assertRaisesRegex(ValueError,'correlation'):check_waveform(p)
    def test_truncated_head_readback(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);self.capture(p);(p/'case.json').write_text(json.dumps({'profile':'head'}))
            with self.assertRaisesRegex(ValueError,'full head CPU readback'):check_waveform(p)
