import csv,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
from opt14_model import geometry,history,serial_floor,FEEDBACK
from tests.opt14.score import golden

class Accounting(unittest.TestCase):
    def test_full_head_geometry_and_tail(self):
        g=geometry(json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text()))
        self.assertEqual((g['macs'],g['group_restores'],g['weight_bytes'],g['scale_bytes']),
                         (136134656,2127104,136134656,8508416))
        self.assertEqual((g['logits_bytes'],g['packed_m1_output_commands'],g['fixed_output_drain_cycles']),
                         (607744,37984,38895616))
        self.assertEqual((g['row_blocks_256'],g['final_block_rows']),(594,128))

    def test_trimmed_vocabulary_rejected(self):
        manifest=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
        for x in manifest['directory']:
            if x['name']=='model.embed_tokens.weight':x['shape'][0]-=128
        with self.assertRaisesRegex(ValueError,'full head'):geometry(manifest)

    def test_aggregate_decode_bound_is_not_average_head_subtraction(self):
        s,p=history(ROOT)
        self.assertEqual(s['unprofiled_cycles'],598128022)
        self.assertEqual(p['unprofiled_cycles'],213190438)
        self.assertAlmostEqual(s['decode_interval_seconds_lower_bound'],19.59483602,places=7)
        self.assertGreater(s['decode_interval_seconds_lower_bound'],2)
        self.assertIsNone(p['decode_interval_seconds_lower_bound'])

    def test_missing_profile_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)/FEEDBACK;d.mkdir(parents=True)
            for n in ('measurements.csv','operator_profile.csv'):(d/n).write_bytes((ROOT/FEEDBACK/n).read_bytes())
            p=d/'operator_profile.csv'
            with p.open() as f:rows=list(csv.DictReader(f))
            fields=list(rows[0])
            rows=[r for r in rows if not(r['variant']=='B' and r['case']=='S' and r['operator']=='head')]
            with p.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
            with self.assertRaisesRegex(ValueError,'historical operator'):history(tmp)

    def test_full_vocabulary_semantic_fixture(self):
        g=golden();self.assertEqual(g['vocabulary'],151936)
        self.assertEqual([(x['status'],x['token']) for x in g['cases']],
            [(0,151935),(0,255),(0,151645),(-2,123456),(-2,123456),(-2,123456),(0,0)])

    def test_serial_layer_floor_does_not_credit_removed_head(self):
        manifest=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
        control=(ROOT/'variants/opt10/rtl/ce64/nx_ce64_control.sv').read_text()
        f=serial_floor(manifest,control)
        self.assertEqual(f['cycles_per_group'],52)
        self.assertEqual(f['layer_groups_without_head'],5591040)
        self.assertEqual(f['layer_only_cycles_floor'],290734080)
        self.assertGreater(f['layer_only_seconds_floor'],2.0)
        with self.assertRaises(ValueError):serial_floor(manifest,control.replace('state<=RAM_WAIT','state<=RAM_WRITE'))

if __name__=='__main__':unittest.main()
