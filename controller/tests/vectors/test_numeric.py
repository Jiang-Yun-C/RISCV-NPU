"""Arithmetic, exceptional inputs and checker negative controls."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(Path(__file__).parent))
from model_tools import numeric_v1 as r
from model_tools.capacity import calculate
from check_v1 import small_check, metric, THRESHOLDS


class NumericTests(unittest.TestCase):
    def test_canonical_tree_reduction(self):
        x=np.array([[1e8,1,-1e8,1],[1,2,3,4]],np.float32)
        np.testing.assert_array_equal(r.tree_sum(x),[0,10])
        np.testing.assert_array_equal(r.tree_sum(np.array([[1,2,3]],np.float32)),[6])
        np.testing.assert_array_equal(r.tree_sum(x,axis=0),[1e8,3,-1e8,5])

    def test_round_ties_even_and_sign(self):
        x=np.zeros((1,64),np.float32); x[0,:8]=[127,-127,.5,1.5,2.5,-.5,-1.5,-2.5]
        q,s=r.quantize(x)
        np.testing.assert_array_equal(q[0,:8],[127,-127,0,2,2,0,-2,-2]); self.assertEqual(s[0,0],1)

    def test_zero_and_tail_groups(self):
        for k in [1,63,64,65,127,128,129,896,4864]:
            x=np.zeros((4,k),np.float32); q,s=r.quantize(x)
            self.assertEqual(s.shape,(4,(k+63)//64)); self.assertFalse(q.any()); self.assertFalse(s.any())
            x[0,-1]=127; q,s=r.quantize(x)
            self.assertEqual(q[0,-1],127); self.assertEqual(s[0,-1],1)
            np.testing.assert_array_equal(r.dequantize(q,s),x)

    def test_int32_extremes_and_bias(self):
        a=np.full((1,64),127,np.int8); s=np.ones((1,1),np.float32)
        for sign in [-1,1]:
            y,d=r.linear_quantized(a,s,a*sign,s,np.array([.25],np.float32))
            self.assertEqual(int(d[0,0,0]),sign*1032256); self.assertEqual(y[0,0],sign*1032256+.25)

    def test_scale_before_cross_group_sum(self):
        q=np.full((1,128),127,np.int8); a=np.array([[1.,2.]],np.float32); w=np.array([[3.,5.]],np.float32)
        y,_=r.linear_quantized(q,a,q,w,np.array([7],np.float32))
        self.assertEqual(y[0,0],np.float32(1032256*13+7))
        self.assertNotEqual(y[0,0],np.float32((2*1032256)*3+7))

    def test_zero_scale_requires_zero_integer(self):
        q=np.zeros((1,1),np.int8); s=np.zeros((1,1),np.float32)
        np.testing.assert_array_equal(r.dequantize(q,s),[[0]])
        q[0,0]=1
        with self.assertRaises(ValueError): r.dequantize(q,s)

    def test_nan_inf_rejected(self):
        for bad in [np.nan,np.inf,-np.inf]:
            with self.assertRaises(ValueError): r.quantize([[bad]])
            with self.assertRaises(ValueError): r.linear([[0]],[[0]],[bad])
            with self.assertRaises(ValueError): r.dequantize(np.zeros((1,1),np.int8),[[bad]])
            with self.assertRaises(ValueError): r.softmax([[bad]],[[True]])
            with self.assertRaises(ValueError): r.rmsnorm([[bad]],[1])

    def test_finite_extremes_and_scale_floor(self):
        tiny=np.nextafter(np.float32(0),np.float32(1)); maximum=np.finfo(np.float32).max
        q,s=r.quantize([[tiny]]); self.assertEqual(s[0,0],np.finfo(np.float32).tiny); self.assertEqual(q[0,0],0)
        q,s=r.quantize([[maximum,-maximum]]); np.testing.assert_array_equal(q,[[127,-127]]); self.assertTrue(np.isfinite(s).all())
        with self.assertRaises((FloatingPointError,ValueError)):
            r.linear([[maximum]],[[maximum]])

    def test_invalid_quantized_and_shapes(self):
        for q,s in [(np.array([[-128]],np.int8),[[1]]),(np.zeros((1,1),np.int8),[[-1]]),(np.zeros((1,1),np.int8),[[1e-40]]),(np.zeros((1,1),np.int32),[[1]])]:
            with self.assertRaises(ValueError): r.dequantize(q,s)
        for x in [[],np.empty((0,2)),np.ones(3)]:
            with self.assertRaises(ValueError): r.quantize(x)
        with self.assertRaises(ValueError): r.linear([[1,2]],[[1]])
        with self.assertRaises(ValueError): r.linear([[1]],[[1]],[[1]])

    def test_rope_halves_positions(self):
        x=np.zeros((1,1,64),np.float32); x[0,0,0]=1; x[0,0,32]=2
        np.testing.assert_array_equal(r.rope(x,np.array([0])),x)
        y=r.rope(x,np.array([1]))
        self.assertAlmostEqual(float(y[0,0,0]),np.cos(1)-2*np.sin(1),places=6)
        self.assertAlmostEqual(float(y[0,0,32]),2*np.cos(1)+np.sin(1),places=6)
        for pos in [-1,32768]:
            with self.assertRaises(ValueError): r.rope(x,np.array([pos]))

    def test_gqa_causal_mapping_and_cached_attention(self):
        q=np.zeros((2,14,64),np.float32); k=np.zeros((2,2,64),np.float32); v=np.zeros_like(k)
        v[0,0]=2; v[0,1]=7; v[1,0]=4; v[1,1]=9
        y,p=r.attention(q,k,v); y=y.reshape(2,14,64)
        np.testing.assert_array_equal(y[0,:7],2); np.testing.assert_array_equal(y[0,7:],7)
        np.testing.assert_array_equal(y[1,:7],3); np.testing.assert_array_equal(y[1,7:],8)
        self.assertFalse(p[:,0,1].any())
        z,_=r.attention(q[1:],k,v,past=1); np.testing.assert_array_equal(z,y[1:].reshape(1,896))

    def test_stable_softmax_and_all_masked_rejection(self):
        y=r.softmax([[10000,10000,-10000]],[[True,True,False]])
        np.testing.assert_array_equal(y,[[.5,.5,0]])
        with self.assertRaises(ValueError): r.softmax([[0,0]],[[False,False]])

    def test_swiglu_and_norm(self):
        x=np.array([[-10000,0,10000]],np.float32)
        np.testing.assert_array_equal(r.swiglu(x,np.ones_like(x)),[[0,0,10000]])
        np.testing.assert_array_equal(r.rmsnorm(np.zeros((1,896)),np.ones(896)),np.zeros((1,896)))
        self.assertTrue(np.isfinite(r.rmsnorm(np.full((1,896),1e-4),np.ones(896))).all())

    def test_greedy_eos_and_length(self):
        logits=np.zeros(151936,np.float32); logits[7]=logits[8]=1
        self.assertEqual(r.greedy(logits),7)
        self.assertEqual(r.stop_reason(151645,128),'eos'); self.assertEqual(r.stop_reason(7,128),'max_new_tokens')
        self.assertEqual(r.stop_reason(151643,1),'continue')
        with self.assertRaises(ValueError): r.stop_reason(151936,1)
        with self.assertRaises(ValueError): r.stop_reason(1,0)

    def test_scalar_fixture_and_corrupt_evidence_rejected(self):
        path=ROOT/'tests/vectors/v1/small.npz'; small_check(path)
        with np.load(path) as x: arrays={k:x[k].copy() for k in x.files}
        with tempfile.TemporaryDirectory() as directory:
            for key in ['dots','aq','sa','y']:
                mutated={k:v.copy() for k,v in arrays.items()}; mutated[key].flat[0]-=1
                p=Path(directory)/(key+'.npz'); np.savez(p,**mutated)
                with self.assertRaises(AssertionError,msg=key): small_check(p)

    def test_error_metrics_reject_nan_and_excess_error(self):
        limit=THRESHOLDS['operators']['linear']
        with self.assertRaises(ValueError): metric([np.nan],[0],limit)
        with self.assertRaises(ValueError): metric([0],[0,1],limit)
        with self.assertRaises(AssertionError): metric([1.1],[1],limit)
        with self.assertRaises(AssertionError): metric([1e-7],[0],limit)  # NRMSE gate independently fails.

    def test_capacity_and_shared_embedding(self):
        manifest=json.loads((ROOT/'docs/spec/operator-manifest.json').read_text())
        a=calculate(manifest,512,1); b=calculate(manifest,2048,8)
        self.assertEqual(a['matrix_elements'],493961216); self.assertEqual(a['unique_parameters'],494032768)
        self.assertEqual(a['kv_fp32_bytes'],12*2**20); self.assertEqual(b['kv_fp32_bytes'],48*2**20)
        self.assertEqual(b['linear_MACs'],8*a['linear_MACs']); self.assertGreater(a['one_GiB_minus_weights_and_kv_bytes'],0)


if __name__=='__main__': unittest.main()
