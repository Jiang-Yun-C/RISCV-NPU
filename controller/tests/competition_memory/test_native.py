"""Native real model callbacks plus the actual backend's exact tail bounds."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from tests.production_streaming.fixtures import WEIGHTS_HEADER

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

class ModelCallbacks(unittest.TestCase):
    def test_actual_pv_driver_capability_bounds_and_failures(self):
        with tempfile.TemporaryDirectory(prefix='t27-memory-pv-driver-') as d:
            exe=Path(d)/'pv-driver'
            args=['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
                '-ffunction-sections','-fdata-sections','-I',str(ROOT/'software/include'),
                '-I',str(ROOT/'firmware/drivers/accel'),str(HERE/'pv_driver.c'),
                str(ROOT/'firmware/drivers/accel/opt12.c'),'-Wl,--gc-sections','-lm','-o',str(exe)]
            built=subprocess.run(args,capture_output=True,text=True,timeout=60)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            done=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(done.returncode,0,done.stdout+done.stderr)
            self.assertEqual(json.loads(done.stdout)['status'],'PASS');print(done.stdout.strip())

    def test_actual_backend_policy_and_result_identity(self):
        with tempfile.TemporaryDirectory(prefix='t27-memory-policy-') as d:
            exe=Path(d)/'policy'
            args=['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
                '-ffp-contract=off','-fno-fast-math','-ffunction-sections','-fdata-sections',
                '-DNX_PORTABLE','-DNX_KV_TAIL_DIRECT=1','-DNX_HEAD_ARGMAX=1','-DNX_PV_LONG=1',
                '-I',str(ROOT/'software/include'),
                '-I',str(ROOT/'firmware/runtime/reference'),'-I',str(ROOT/'firmware/runtime/port'),
                '-I',str(ROOT/'firmware/drivers/accel'),
                str(HERE/'backend_policy.c'),str(ROOT/'firmware/runtime/port/ce64_backend.c'),
                str(ROOT/'firmware/drivers/accel/linear_api.c'),'-Wl,--gc-sections','-lm','-o',str(exe)]
            built=subprocess.run(args,capture_output=True,text=True,timeout=60)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            done=subprocess.run([str(exe)],check=True,capture_output=True,text=True,timeout=30)
            record=json.loads(done.stdout);self.assertEqual(record['tail_faults'],8);print(done.stdout.strip())

    def test_real_model_tail_leases_and_head_selection(self):
        with tempfile.TemporaryDirectory(prefix='t27-memory-callbacks-') as d:
            p=Path(d);(p/'full_weights.h').write_text(WEIGHTS_HEADER)
            outcomes=[]
            for enabled in (0,1):
                exe=p/f'callbacks-{enabled}'
                args=['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                    '-Wno-misleading-indentation','-Wno-unknown-pragmas','-Wno-unused-function',
                    '-ffp-contract=off','-fno-fast-math','-DNX_PORTABLE','-DNX_OPT13_TEST',
                    '-DNX_PREFIX_CAPTURE=1','-DNX_PROFILE_INTEGER=1',
                    f'-DNX_KV_TAIL_DIRECT={enabled}',f'-DNX_HEAD_ARGMAX={enabled}',
                    '-I',str(p),'-I',str(ROOT/'firmware/runtime/reference'),
                    str(ROOT/'firmware/runtime/reference/nx_reference.c'),str(HERE/'model_callbacks.c'),'-lm','-o',str(exe)]
                subprocess.run(args,check=True,capture_output=True,timeout=60)
                done=subprocess.run([str(exe)],check=True,capture_output=True,text=True,timeout=90)
                outcomes.append(json.loads(done.stdout))
            self.assertEqual(outcomes[0]['tail_calls'],0)
            self.assertGreater(outcomes[1]['lease_mutations'],1000)
            self.assertGreater(outcomes[1]['head_calls'],100)
            for record in outcomes:
                self.assertEqual(record['prefix_hits'],2)
                self.assertEqual(record['joint_compares'],4)
                self.assertEqual(record['integer_profile_checks'],2)
            self.assertEqual(outcomes[0]['prefix_revocations'],1)
            self.assertEqual(outcomes[1]['prefix_revocations'],3)
            print(json.dumps({'model_callback_cases':outcomes}))

if __name__=='__main__':unittest.main()
