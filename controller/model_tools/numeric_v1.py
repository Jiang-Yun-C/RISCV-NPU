"""Backend-independent NumPy oracle for numeric-v1; no torch/backend imports.

All linear inputs are logical row-major [M,K] / [N,K]. Integer dot uses
int64 as an overflow-detecting oracle; the exported contract is int32.
"""
import numpy as np

VERSION = "w8a8-g64-fp32-v1"
GROUP = 64
F = np.float32


def finite(x):
    a = np.asarray(x, dtype=np.float32)
    if not np.isfinite(a).all():
        raise ValueError("nonfinite FP32 input/output")
    return a


def tree_sum(x, axis=-1, keepdims=False):
    """FP32 adjacent-pair tree, zero-padded to a power of two."""
    x = finite(x)
    axis %= x.ndim
    n = x.shape[axis]
    if n == 0:
        raise ValueError("empty reduction")
    values = np.moveaxis(x, axis, -1)
    size = 1 << (n-1).bit_length()
    values = np.pad(values, [(0,0)]*(values.ndim-1)+[(0,size-n)])
    while values.shape[-1] > 1:
        values = values[..., 0::2] + values[..., 1::2]
    result = values[..., 0]
    return finite(np.expand_dims(result, axis) if keepdims else result)


def quantize(x):
    x = finite(x)
    if x.ndim != 2 or min(x.shape) <= 0:
        raise ValueError("quantize requires nonempty [rows,K]")
    rows, k = x.shape
    groups = (k + GROUP - 1) // GROUP
    padded = np.zeros((rows, groups * GROUP), dtype=np.float32)
    padded[:, :k] = x
    values = padded.reshape(rows, groups, GROUP)
    peak = np.max(np.abs(values), axis=-1)
    # Nonzero groups use at least FLT_MIN_NORMAL: scale never underflows to 0.
    scales = np.where(peak == 0, F(0), np.maximum(peak / F(127), np.finfo(F).tiny))
    safe = np.where(scales == 0, F(1), scales)
    q = np.clip(np.rint(values / safe[..., None]), -127, 127).astype(np.int8)
    return q.reshape(rows, -1)[:, :k].copy(), scales.astype(np.float32)


def validate_quantized(q, scales):
    q = np.asarray(q)
    scales = finite(scales)
    if q.ndim != 2 or min(q.shape) <= 0 or q.dtype != np.int8 or np.any(q == -128):
        raise ValueError("invalid signed symmetric INT8")
    if scales.shape != (q.shape[0], (q.shape[1] + 63) // 64) or np.any(scales < 0):
        raise ValueError("invalid scales")
    if np.any((scales > 0) & (scales < np.finfo(F).tiny)):
        raise ValueError("subnormal scale")
    for g in range(scales.shape[1]):
        if np.any(q[scales[:, g] == 0, g*64:(g+1)*64] != 0):
            raise ValueError("nonzero integer with zero scale")
    return q, scales


def dequantize(q, scales):
    q, scales = validate_quantized(q, scales)
    return finite(q.astype(F) * np.repeat(scales, GROUP, axis=1)[:, :q.shape[1]])


def linear_quantized(aq, sa, wq, sw, bias=None):
    aq, sa = validate_quantized(aq, sa)
    wq, sw = validate_quantized(wq, sw)
    if aq.shape[1] != wq.shape[1]:
        raise ValueError("linear K mismatch")
    m, k = aq.shape
    n = wq.shape[0]
    out = np.zeros((m, n), dtype=F)
    dots = np.empty((sa.shape[1], m, n), dtype=np.int32)
    with np.errstate(over="raise", invalid="raise"):
        for g in range(sa.shape[1]):
            lo, hi = g*GROUP, min(k, (g+1)*GROUP)
            dot = aq[:, lo:hi].astype(np.int64) @ wq[:, lo:hi].astype(np.int64).T
            if np.any(np.abs(dot) > (hi-lo)*127*127):
                raise ValueError("INT32 dot bound violated")
            dots[g] = dot.astype(np.int32)
            # Two multiplications, then one addition; never fuse/reassociate.
            restored = dot.astype(F) * sa[:, g, None]
            restored = restored * sw[None, :, g]
            out = out + restored
        if bias is not None:
            bias = finite(bias)
            if bias.shape != (n,):
                raise ValueError("bias shape mismatch")
            out = out + bias
    return finite(out), dots


def linear(x, w, bias=None):
    aq, sa = quantize(x)
    wq, sw = quantize(w)
    return linear_quantized(aq, sa, wq, sw, bias)[0]


def rmsnorm(x, gamma, eps=1e-6):
    x, gamma = finite(x), finite(gamma)
    if x.shape[-1:] != gamma.shape or eps != 1e-6:
        raise ValueError("RMSNorm shape/epsilon")
    with np.errstate(over="raise", invalid="raise"):
        variance = tree_sum(x*x, keepdims=True) / F(x.shape[-1])
        r = F(1) / np.sqrt(variance + F(eps))
        return finite((x*r)*gamma)


def rope(x, positions, theta=1000000.0):
    x = finite(x)
    p = np.asarray(positions)
    if x.ndim != 3 or x.shape[-1] != 64 or p.shape != (x.shape[0],) or p.dtype.kind not in 'iu' or np.any(p < 0) or np.any(p >= 32768):
        raise ValueError("RoPE shape/position")
    inv = F(1) / np.power(F(theta), np.arange(0, 64, 2, dtype=F) / F(64))
    angle = p.astype(F)[:, None] * inv[None, :]
    angle = np.concatenate((angle, angle), axis=-1)[:, None, :]
    rotated = np.concatenate((-x[..., 32:], x[..., :32]), axis=-1)
    return finite(x*np.cos(angle) + rotated*np.sin(angle))


def softmax(scores, mask):
    scores = finite(scores)
    mask = np.asarray(mask)
    if mask.dtype != np.bool_:
        raise ValueError("mask must be boolean")
    mask = np.broadcast_to(mask, scores.shape)
    if not np.all(np.any(mask, axis=-1)):
        raise ValueError("all-masked attention row")
    selected = np.where(mask, scores, F(-np.inf))
    shifted = selected - np.max(selected, axis=-1, keepdims=True)
    e = np.exp(shifted)
    return finite(e / tree_sum(e, keepdims=True))


def attention_scores(q, k):
    q, k = finite(q), finite(k)
    if q.ndim != 3 or q.shape[1:] != (14, 64) or k.ndim != 3 or k.shape[1:] != (2, 64):
        raise ValueError("QK shape")
    qh = q.transpose(1,0,2)
    kh = np.repeat(k, 7, axis=1).transpose(1,0,2)
    return finite(tree_sum(qh[:,:,None,:] * kh[:,None,:,:]) * F(0.125))


def attention(q, k, v, past=0):
    q, k, v = finite(q), finite(k), finite(v)
    if q.ndim != 3 or q.shape[1:] != (14, 64) or k.ndim != 3 or k.shape[1:] != (2, 64) or k.shape != v.shape or past < 0 or past+q.shape[0] != k.shape[0]:
        raise ValueError("GQA shape/cache length")
    # Query heads 0..6 share KV 0; query heads 7..13 share KV 1.
    vr = np.repeat(v, 7, axis=1)
    scores = attention_scores(q, k)
    mask = np.arange(k.shape[0])[None, :] <= (past + np.arange(q.shape[0]))[:, None]
    prob = softmax(scores, mask[None, ...])
    products = prob[:,:,:,None] * vr.transpose(1,0,2)[:,None,:,:]
    y = tree_sum(products, axis=2).transpose(1,0,2)
    return finite(y.reshape(q.shape[0], 896)), prob


def swiglu(gate, up):
    gate, up = finite(gate), finite(up)
    if gate.shape != up.shape:
        raise ValueError("SwiGLU shape")
    # Stable sigmoid in both tails; no overflow for a finite negative input.
    e = np.exp(-np.abs(gate))
    sigmoid = np.where(gate >= 0, F(1)/(F(1)+e), e/(F(1)+e))
    return finite((gate * sigmoid) * up)


def residual(x, y):
    x, y = finite(x), finite(y)
    if x.shape != y.shape:
        raise ValueError("residual shape")
    return finite(x+y)


def block(x, weights, cache=None):
    """One real Qwen layer, absolute positions from a contiguous FP32 KV cache."""
    x = finite(x)
    if x.ndim != 2 or x.shape[1] != 896:
        raise ValueError("block shape")
    past = 0 if cache is None else cache[0].shape[0]
    t = {'input': x, 'norm1': rmsnorm(x, weights['input_layernorm.weight'])}
    for name, heads in [('q', 14), ('k', 2), ('v', 2)]:
        stem = 'self_attn.' + name + '_proj'
        t[name] = linear(t['norm1'], weights[stem+'.weight'], weights[stem+'.bias']).reshape(-1, heads, 64)
    t['qr'] = rope(t['q'], np.arange(past, past+x.shape[0]))
    newk = rope(t['k'], np.arange(past, past+x.shape[0]))
    t['cache_k'] = newk if cache is None else np.concatenate((finite(cache[0]), newk))
    t['cache_v'] = t['v'] if cache is None else np.concatenate((finite(cache[1]), t['v']))
    t['scores'] = attention_scores(t['qr'], t['cache_k'])
    t['attn'], t['prob'] = attention(t['qr'], t['cache_k'], t['cache_v'], past)
    t['o'] = linear(t['attn'], weights['self_attn.o_proj.weight'])
    t['res1'] = residual(x, t['o'])
    t['norm2'] = rmsnorm(t['res1'], weights['post_attention_layernorm.weight'])
    t['gate'] = linear(t['norm2'], weights['mlp.gate_proj.weight'])
    t['up'] = linear(t['norm2'], weights['mlp.up_proj.weight'])
    t['act'] = swiglu(t['gate'], t['up'])
    t['down'] = linear(t['act'], weights['mlp.down_proj.weight'])
    t['output'] = residual(t['res1'], t['down'])
    return t


def greedy(logits):
    logits = finite(logits)
    if logits.ndim != 1 or logits.size != 151936:
        raise ValueError("logits shape")
    return int(np.argmax(logits))


def stop_reason(token, generated_count, max_new_tokens=128):
    if not isinstance(token, (int, np.integer)) or not 0 <= token < 151936 or not 1 <= generated_count <= max_new_tokens or max_new_tokens != 128:
        raise ValueError("invalid generation state")
    return 'eos' if token == 151645 else ('max_new_tokens' if generated_count == max_new_tokens else 'continue')
