"""Synthetic local assets; never substitute these for production model assets.

The C implementation still executes real model forward/greedy/KV operations.
Only its already-supported NX_OPT13_TEST geometry and weight data are reduced.
The tokenizer format is real, but its vocabulary contents are synthetic.
"""
from pathlib import Path
import hashlib
import struct


def make_tokenizer(path, text_encoding=False):
    vocab, merges = 151665, 151387
    categories = [(9, 9, 4), (10, 10, 12), (13, 13, 12), (32, 32, 4),
                  (48, 57, 2), (65, 90, 1), (97, 122, 1)] if text_encoding else []
    offsets = [128]
    for size in (8 * vocab, 1024, 16 * merges, 12 * len(categories), 0, 0, 0, 0):
        offsets.append(offsets[-1] + size)
    # IDs 0..31 cover all outputs of the reduced real model. The remaining
    # special fixture IDs exercise split scalars, replacement, EOS and controls.
    pieces = {i: "中".encode() for i in range(32)}
    pieces.update({100: b"\xe4", 101: b"\xb8", 102: b"\xad", 103: b" ",
                   104: b"\nT25 READY\n", 105: b"A", 106: b"\xf0\x9f",
                   107: b"\x8c\x8d", 108: b"\xff", 109: b"\r\x00\t",
                   151645: b"<|im_end|>"})
    if text_encoding:
        # Text tests retain the real encoder, but map all byte tokens into the
        # reduced graph's 32-token vocabulary. No real model quality claim.
        pieces[151645] = b"\x00fixture_end"
        # Used only by explicit action-gate fixture modes. The real reduced
        # model still runs; those modes override returned next IDs to exercise
        # a complete JSON/EOS commit or a final-boundary refusal, not semantics.
        pieces[30] = b'[["led",1]]'
        pieces[28] = b'[["led",0]]'
        pieces[29] = b'[["led",1],["led",0]]'
        pieces[27] = b'[["led",1],["led",0],["led",1]]'
        pieces[31] = b'[["led",1],["pwm",1]]'
    payload = bytearray(b"?")
    entries = [(0, 1)] * vocab
    for token, raw in pieces.items():
        entries[token] = (len(payload), len(raw) | ((2 << 24) if token == 151645 else 0))
        payload.extend(raw)
    blob = bytearray(offsets[-1] + len(payload))
    header = [0x31544B4E, 1, len(blob), vocab, merges, len(categories), 0, 0, 0, 22, *offsets]
    struct.pack_into("<" + "I" * len(header), blob, 0, *header)
    for token, (offset, size) in enumerate(entries):
        struct.pack_into("<II", blob, offsets[0] + 8 * token, offset, size)
    if text_encoding:
        for byte in range(256):
            struct.pack_into("<I", blob, offsets[1] + byte * 4, byte % 28)
        for index, category in enumerate(categories):
            struct.pack_into("<III", blob, offsets[3] + index * 12, *category)
    blob[offsets[-1]:] = payload
    Path(path).write_bytes(blob)


WEIGHTS_HEADER = r'''
/* SYNTHETIC TEST ASSETS ONLY: two complete small Transformer blocks. */
static int8_t fixture_q[15][32*64];
static float fixture_scale[15][32], fixture_bias[15][32];
static float fixture_norm[5][28], fixture_inv[1] = {1.0f};
static uint32_t fixture_rng = 0x7cb2d102u;
static unsigned fixture_model_load_count;
static nx_matrix fixture_matrix(unsigned slot,int n,int k,int bias) {
    for(int row=0;row<n;row++) {
        fixture_scale[slot][row]=0.001f + (float)(row%3)*0.0001f;
        fixture_bias[slot][row]=((float)(row%5)-2.0f)*0.001f;
        for(int col=0;col<k;col++) {
            fixture_rng=fixture_rng*1664525u+1013904223u;
            fixture_q[slot][row*64+col]=(int8_t)((fixture_rng>>24)%127)-63;
        }
    }
    return (nx_matrix){fixture_q[slot],fixture_scale[slot],
        bias?fixture_bias[slot]:NULL,n,k};
}
static void load_full(nx_weights *w) {
    fixture_model_load_count++;
    memset(w,0,sizeof(*w));
    w->embedding=fixture_matrix(0,32,28,0);
    for(unsigned layer=0;layer<2;layer++) {
        unsigned slot=1+layer*7;
        w->layer[layer].q=fixture_matrix(slot,28,28,1);
        w->layer[layer].k=fixture_matrix(slot+1,4,28,1);
        w->layer[layer].v=fixture_matrix(slot+2,4,28,1);
        w->layer[layer].o=fixture_matrix(slot+3,28,28,0);
        w->layer[layer].gate=fixture_matrix(slot+4,32,28,0);
        w->layer[layer].up=fixture_matrix(slot+5,32,28,0);
        w->layer[layer].down=fixture_matrix(slot+6,28,32,0);
        w->layer[layer].norm1=fixture_norm[layer*2];
        w->layer[layer].norm2=fixture_norm[layer*2+1];
    }
    for(unsigned row=0;row<5;row++)for(unsigned col=0;col<28;col++)
        fixture_norm[row][col]=1.0f+(float)(col%3)*0.001f;
    w->norm=fixture_norm[4];w->inv_freq=fixture_inv;
}
'''


def write_assets(directory, text_encoding=False):
    directory = Path(directory)
    make_tokenizer(directory / "synthetic.nxt", text_encoding=text_encoding)
    (directory / "full_weights.h").write_text(WEIGHTS_HEADER)
    model_hash = hashlib.sha256(WEIGHTS_HEADER.encode()).hexdigest()
    tokenizer_hash = hashlib.sha256((directory / "synthetic.nxt").read_bytes()).hexdigest()
    (directory / "t25_identity.h").write_text(
        '/* Synthetic test assets only; these are NOT production identities. */\n'
        f'#define T25_MODEL_SHA256 "{model_hash}"\n'
        f'#define T25_TOKENIZER_SHA256 "{tokenizer_hash}"\n')
    token_path = str(directory / "synthetic.nxt").replace("\\", "\\\\").replace('"', '\\"')
    (directory / "tokenizer.S").write_text(
        '.section .rodata\n.balign 16\n.global t25_tokenizer\n'
        '.global t25_tokenizer_end\nt25_tokenizer:\n'
        f'.incbin "{token_path}"\nt25_tokenizer_end:\n'
        '.section .note.GNU-stack,"",@progbits\n')
