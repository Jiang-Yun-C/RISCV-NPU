import pathlib
import subprocess
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[2]


class Bridge(unittest.TestCase):
    def test_route_two_and_legacy_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            binary=pathlib.Path(folder)/'dispatch'
            subprocess.run(['gcc','-std=c11','-O2','-fno-fast-math','-ffp-contract=off',
                '-fno-strict-aliasing','-ffunction-sections','-Wl,--gc-sections',
                '-I',str(ROOT/'firmware/runtime/reference'),
                str(ROOT/'tests/board_llm/dispatch.c'),'-lm','-o',str(binary)],check=True,capture_output=True,text=True)
            result=subprocess.run([str(binary)],check=True,capture_output=True,text=True)
            self.assertIn('T25_DISPATCH_PASS',result.stdout)

    def test_actual_validator_and_commit_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            binary=pathlib.Path(folder)/'bridge'
            command=['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffunction-sections',
                '-fdata-sections','-Wl,--gc-sections',
                '-I',str(ROOT/'firmware/runtime/port'),'-I',str(ROOT/'firmware/runtime/reference'),
                '-I',str(ROOT/'firmware/drivers/accel'),'-I',str(ROOT/'software/include'),
                str(ROOT/'tests/board_llm/bridge.c'),str(ROOT/'firmware/drivers/accel/linear_api.c'),'-o',str(binary)]
            subprocess.run(command,check=True,capture_output=True,text=True)
            result=subprocess.run([str(binary)],check=True,capture_output=True,text=True)
            self.assertIn('T25_BRIDGE_PASS',result.stdout)


if __name__=='__main__':unittest.main()
