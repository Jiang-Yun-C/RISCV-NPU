import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from run_t25_board import sd_execution_readiness


class SdExecutionPolicy(unittest.TestCase):
    def fixture(self):
        return dict(board='MES2L676-200HP',reported_board_revision='V1.4',card_on_board=True,
            sd_image_sha256='frozen-image',sd_pins_confirmed=False,sd_voltage_confirmed=False,
            execution_policy='USER_SELECTED_V1_2_REFERENCE',user_authorized_reference_execution=True,
            user_instruction='按1.2的就可以',reference_revision='V1.2',reference_voltage_mv=3300,
            reference_pins=dict(sck='F19',mosi='H14',miso='F18',cs_n='H15'))

    def test_explicit_choice_does_not_claim_physical_confirmation(self):
        decision=sd_execution_readiness(self.fixture(),'frozen-image')
        self.assertEqual(decision['mode'],'USER_SELECTED_V1_2_REFERENCE')
        self.assertIs(decision['physical_revision_correspondence_verified'],False)

    def test_choice_is_bound_to_exact_board_media_and_reference(self):
        for key,value in [('board','MINI'),('reported_board_revision','V1.2'),('card_on_board',False),
            ('sd_image_sha256','different'),('user_authorized_reference_execution',False),('user_instruction',''),
            ('reference_voltage_mv',1800),('reference_revision','V1.3'),('reference_pins',{})]:
            with self.subTest(key=key):
                ready=self.fixture();ready[key]=value
                self.assertIsNone(sd_execution_readiness(ready,'frozen-image'))

    def test_physical_evidence_path_remains_available(self):
        ready=self.fixture();ready.update(execution_policy=None,sd_pins_confirmed=True,sd_voltage_confirmed=True,
            confirmation_basis='Matched schematic and measurement')
        self.assertTrue(sd_execution_readiness(ready,'frozen-image')['physical_revision_correspondence_verified'])
