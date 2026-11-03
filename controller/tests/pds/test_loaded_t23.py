"""A new clean window cannot hide an earlier post-boot fault or reset."""
import struct
import sys
from pathlib import Path
import unittest
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from replay_t23_loaded import boot_crc_audit,same_counter_epoch


def packet(sequence):
    data=struct.pack('<64I',0x31443244,sequence,*([0]*62))
    return data+struct.pack('<I',zlib.crc32(data))


class ContinuedT23(unittest.TestCase):
    def test_truncated_prior_image_is_preserved_before_boot(self):
        old=packet(16697)[:17];raw=old+packet(0)+packet(1)
        audit=boot_crc_audit(raw)
        self.assertEqual(audit['bad_crc_offsets'],[0])
        self.assertEqual(audit['sequence_zero_offset'],17)
        self.assertTrue(audit['all_bad_crc_before_sequence_zero'])

    def test_fault_after_boot_is_not_eligible_for_continuation(self):
        bad=bytearray(packet(1));bad[-1]^=1
        audit=boot_crc_audit(packet(0)+bad+packet(2))
        self.assertEqual(audit['bad_crc_offsets'],[260])
        self.assertFalse(audit['all_bad_crc_before_sequence_zero'])

    def test_missing_boot_cannot_classify_a_fault_as_preboot(self):
        bad=bytearray(packet(55));bad[-1]^=1
        self.assertFalse(boot_crc_audit(bad+packet(56))['all_bad_crc_before_sequence_zero'])

    def test_original_counter_epoch_and_rollover(self):
        old={'core_cycles':10,'sequence':0xffffffff,'verified_passes':4,'training_reset_error_count':0}
        new=dict(old,core_cycles=20,sequence=0,verified_passes=5)
        self.assertTrue(same_counter_epoch(new,old))
        for corrupt in (dict(new,core_cycles=0),dict(new,verified_passes=0),dict(new,training_reset_error_count=1)):
            self.assertFalse(same_counter_epoch(corrupt,old))


if __name__=='__main__':unittest.main()
