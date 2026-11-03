import copy
import unittest
from bandwidth import measure

class PhysicalCounters(unittest.TestCase):
    def fixture(self):
        return [{'sequence':i,'host_elapsed_s':float(i*5),'core_cycles':100+i*625000000,
                 'write_payload_bytes':2**32-16+i*128,'read_payload_bytes':i*256,
                 'errors':0,'init_done':True} for i in range(3)]
    def test_effective_read_write_and_mixed(self):
        samples=self.fixture()
        writes=copy.deepcopy(samples);reads=copy.deepcopy(samples)
        for s in writes:s['read_payload_bytes']=0
        for s in reads:s['write_payload_bytes']=0
        self.assertEqual(measure(writes,'sequential_write')['bytes_per_second'],25.6)
        self.assertEqual(measure(reads,'sequential_read')['bytes_per_second'],51.2)
        self.assertEqual(measure(samples,'mixed')['payload_bytes'],768)
    def test_high_counter_preserved(self):
        self.assertEqual(measure(self.fixture(),'mixed')['write_payload_bytes'],256)
    def test_wrong_workload_direction_and_invalid_time_rejected(self):
        for name in ('sequential_read','sequential_write','made_up'):
            with self.assertRaises(ValueError):measure(self.fixture(),name)
        for invalid in (float('nan'),float('inf')):
            samples=self.fixture();samples[-1]['host_elapsed_s']=invalid
            with self.assertRaises(ValueError):measure(samples,'mixed')
    def test_missing_reset_gap_time_and_calibration_rejected(self):
        for key,value in [('write_payload_bytes',0),('sequence',9),('core_cycles',0),
                          ('host_elapsed_s',0),('errors',1),('init_done',False)]:
            with self.subTest(key=key):
                samples=self.fixture();samples[1][key]=value
                with self.assertRaises(ValueError): measure(samples,'mixed')
    def test_short_or_empty_window_rejected(self):
        with self.assertRaises(ValueError): measure([],'mixed')
        with self.assertRaises(ValueError): measure(self.fixture()[:2],'mixed')
    def test_wrong_clock_and_impossible_counter_rejected(self):
        samples=self.fixture();samples[-1]['core_cycles']+=100000000
        with self.assertRaises(ValueError): measure(samples,'mixed')
        samples=self.fixture();samples[-1]['read_payload_bytes']+=10**12
        with self.assertRaises(ValueError): measure(samples,'mixed')
