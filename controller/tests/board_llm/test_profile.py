import unittest
from scripts.audit_t25_profile import CALLS_PER_FORWARD, parse_profile, subtract_profile


class Profile(unittest.TestCase):
    def record(self):
        return ('T25 PROFILE CUMULATIVE ' + ''.join(
            f'{i:08x} ticks={100 + i:016x} calls={n:016x} '
            for i, n in enumerate(CALLS_PER_FORWARD)) + '\n').encode()

    def test_parser_and_existing_cumulative_baseline(self):
        current = parse_profile(self.record())
        previous = [(ticks - 50, 0) for ticks, _ in current]
        self.assertEqual([x['ticks'] for x in subtract_profile(current, previous, 1)], [50] * 8)

    def test_dropped_reordered_duplicate_or_changed_count_rejected(self):
        record = self.record()
        for bad in (record[:-60], record + record, record.replace(b'00000003 ticks=', b'00000002 ticks=')):
            with self.subTest(bad=bad), self.assertRaises(ValueError): parse_profile(bad)
        current = parse_profile(record)
        with self.assertRaises(ValueError): subtract_profile(current, [(0, 0)] * 8, 2)
        with self.assertRaises(ValueError): subtract_profile(current, current, 1)
