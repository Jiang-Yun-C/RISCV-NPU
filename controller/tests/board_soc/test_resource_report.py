"""Both primary tool versions must retain real device budget failures."""
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from pds.resource_report import parse_resources,fits
class ResourceReport(unittest.TestCase):
    def old(self):return (ROOT/'evidence/T24_SYNTH/coral-resource-20261011-v14-sram/RvvCoreMiniAxi.snr').read_text()
    def new(self):return (ROOT/'evidence/T24_RESOURCE/core-rob2024-budget-20261012-v3-command/nx_soc_core_sg.snr').read_text()
    def test_old_singular_and_new_plural_reports(self):
        old=parse_resources(self.old());new=parse_resources(self.new())
        self.assertEqual((old['luts'],old['drm36k']),(489009,18))
        self.assertEqual((new['luts'],new['drm36k']),(334051,27))
        self.assertFalse(fits(old));self.assertFalse(fits(new))
    def test_missing_field_is_never_defaulted(self):
        with self.assertRaisesRegex(ValueError,'drm36k'):parse_resources(self.new().replace('Total DRMs','Missing DRMs'))
    def test_duplicate_summary_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'ambiguous'):parse_resources(self.new()+self.new())
if __name__=='__main__':unittest.main()
