#!/usr/bin/env python3
"""Compile the pinned original tokenizer into bounded, endian-defined RV32 tables.

Only this build tool uses JSON/Unicode libraries. Runtime encoding, NFC, BPE,
chat framing and incremental UTF-8 decoding execute in the same C on host/RV32.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import unicodedata
import regex
import tokenizers
from tokenizers import Regex, normalizers, pre_tokenizers

ROOT = Path(__file__).resolve().parents[1]


def export(destination):
    lock = json.loads((ROOT/'docs/spec/application-v2-model-lock.json').read_text())
    source = ROOT/lock['tokenizer_local_path']
    identities = {}
    for name, record in lock['tokenizer_files'].items():
        data = (source/name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == record['sha256'], name
        identities[name] = record['sha256']
    raw = json.loads((source/'tokenizer.json').read_text())
    assert raw['normalizer'] == {'type': 'NFC'}
    assert raw['model']['type'] == 'BPE'
    expected = r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"
    assert raw['pre_tokenizer']['pretokenizers'][0]['pattern']['Regex'] == expected
    # Standard ByteLevel bijection; reconstruct explicitly to avoid locale/codecs.
    byte_values = list(range(33,127))+list(range(161,173))+list(range(174,256))
    chars = byte_values.copy(); extra = 0
    for b in range(256):
        if b not in byte_values:
            byte_values.append(b); chars.append(256+extra); extra += 1
    inverse = {chr(c): b for b,c in zip(byte_values,chars)}
    vocab = raw['model']['vocab']; count=max(t['id'] for t in raw['added_tokens'])+1
    strings = [b'']*count; flags=[0]*count
    for text, i in vocab.items(): strings[i]=bytes(inverse[c] for c in text)
    for t in raw['added_tokens']:
        strings[t['id']]=t['content'].encode(); flags[t['id']]=1+int(t['special'])
    blob=bytearray(); entries=[]
    for i,s in enumerate(strings):
        entries.extend((len(blob),len(s)|(flags[i]<<24))); blob.extend(s)
    base=[0]*256
    for c,b in inverse.items(): base[b]=vocab[c]
    merges=[]
    for rank, pair in enumerate(raw['model']['merges']):
        a,b=pair.split(' ') if isinstance(pair,str) else pair
        merges.append((vocab[a],vocab[b],rank,vocab[a+b]))
    assert len({m[:2] for m in merges})==len(merges)
    merges.sort()

    # Classify with the SAME Rust/oniguruma regex engine as the pinned reference.
    # Splitting each Unicode block gives one match per member, without guessing
    # which Unicode version Python's built-in database implements.
    classes=bytearray(0x110000)
    for pattern,mask in ((r'\p{L}',1),(r'\p{N}',2),(r'\s',4)):
        splitter=pre_tokenizers.Split(Regex(pattern),behavior='removed',invert=True)
        for start in range(0,0x110000,4096):
            values=[c for c in range(start,min(start+4096,0x110000)) if not 0xd800<=c<=0xdfff]
            text=''.join(map(chr,values))
            for part,_ in splitter.pre_tokenize_str(text):
                for ch in part: classes[ord(ch)] |= mask
    for c in (10,13): classes[c] |= 8
    ranges=[]; lo=0
    for c in range(1,len(classes)+1):
        if c==len(classes) or classes[c]!=classes[lo]:
            if classes[lo]: ranges.extend((lo,c-1,classes[lo]))
            lo=c
    nfd=normalizers.NFD(); nfc=normalizers.NFC()
    decomps=[]; scalars=[]; compositions={}; combining=[]
    # Numeric CCC is supplied by the installed regex Unicode database, then
    # checked against the official normalizer's actual ordering below.
    ccc_patterns=[(i,regex.compile(r'\A\p{ccc='+str(i)+r'}\Z')) for i in range(1,256)
                  if i in (1,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,84,91,103,107,118,122,129,130,132,133,200,202,214,216,218,220,222,224,226,228,230,232,233,234,240)]
    marks=regex.compile(r'\A\p{M}\Z')
    representatives={}
    for c in range(0x110000):
        if 0xd800<=c<=0xdfff: continue
        ch=chr(c); decomp=nfd.normalize_str(ch)
        if decomp!=ch:
            decomps.extend((c,len(scalars),len(decomp))); scalars.extend(map(ord,decomp))
            if len(decomp)>1 and nfc.normalize_str(decomp)==ch:
                prefix=nfc.normalize_str(decomp[:-1])
                if len(prefix)==1: compositions[(ord(prefix),ord(decomp[-1]))]=c
        if marks.fullmatch(ch):
            cc=next((i for i,p in ccc_patterns if p.fullmatch(ch)),0)
            if cc:
                combining.extend((c,cc))
                if unicodedata.ucd_3_2_0.combining(ch)==cc:
                    representatives.setdefault(cc,ch)
    # New Unicode classes unsupported by the official engine must not silently
    # change its NFC. Check every combining scalar against neighboring classes.
    effective=[]
    for c,cc in zip(combining[::2],combining[1::2]):
        if nfd.normalize_str(chr(c))!=chr(c): continue
        supported=True
        for other,r in representatives.items():
            if nfd.normalize_str(r)!=r: continue
            want=(r+chr(c)) if other<=cc else (chr(c)+r)
            if nfd.normalize_str(r+chr(c))!=want: supported=False
            want=(chr(c)+r) if cc<=other else (r+chr(c))
            if nfd.normalize_str(chr(c)+r)!=want: supported=False
        if supported: effective.extend((c,cc))
        else:
            # The official normalizer treats newly assigned scalars as CCC=0.
            assert all(nfd.normalize_str(r+chr(c))==r+chr(c) and
                       nfd.normalize_str(chr(c)+r)==chr(c)+r
                       for r in representatives.values() if nfd.normalize_str(r)==r),hex(c)
    combining=effective
    comps=[x for pair,c in sorted(compositions.items()) for x in (*pair,c)]
    sections=[entries,base,[x for m in merges for x in m],ranges,decomps,scalars,comps,combining]
    header=[0x31544b4e,1,0,count,len(merges),len(ranges)//3,len(decomps)//3,len(comps)//3,len(combining)//2,len(raw['added_tokens'])]
    payload=bytearray(128); offsets=[]
    for section in sections:
        offsets.append(len(payload)); payload.extend(struct.pack('<'+'I'*len(section),*section))
    offsets.append(len(payload)); payload.extend(blob)
    header[2]=len(payload)
    struct.pack_into('<'+'I'*(len(header)+len(offsets)),payload,0,*(header+offsets))
    if len(payload)>5630976: raise ValueError('T10 derived tokenizer index budget exceeded')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    (destination/'tokenizer.nxt').write_bytes(payload)
    manifest={'version':'nxt-v1','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),
              'source_files':identities,'tokenizers':tokenizers.__version__,'regex':regex.__version__,
              'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'vocab':count,'merges':len(merges),'unicode_ranges':len(ranges)//3,
              'decompositions':len(decomps)//3,'compositions':len(comps)//3,'ccc':len(combining)//2,
              'pretokenizer_regex':expected,'runtime_text_bytes_limit':4096}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    print(json.dumps(export(p.parse_args().output),indent=2))
