import json,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class NativeTransport(unittest.TestCase):
    def test_drain_completion_and_fault_isolation(self):
        tools=json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools'];src=ROOT/'firmware/drivers/accel'
        with tempfile.TemporaryDirectory() as td:
            exe=Path(td)/'transport'
            subprocess.run([tools['host_cc']['path'],'-std=c11','-O2','-Wall','-Wextra','-Werror','-I',str(src),'-I',str(ROOT/'software/include'),str(src/'coral_linear.c'),str(ROOT/'tests/soc_accel/host_transport.c'),'-o',str(exe)],check=True,capture_output=True)
            result=subprocess.run([str(exe)],check=True,capture_output=True,text=True);self.assertIn('PASS native transport',result.stdout)
