"""Reproducible SD fixtures; consume T10's frozen files without rewriting them."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'software/boot'),str(ROOT/'model_tools')]
from sd_image import build,digest
from verify_pack import verify,PackError
ERRORS=dict(E_TIMEOUT=1,E_CARD=2,E_CRC=3,E_MEDIA=4,E_MAGIC=5,E_VERSION=6,E_ENDIAN=7,E_LAYOUT=8,
 E_CHECKSUM=9,E_BOUNDS=10,E_OVERFLOW=11,E_ALIGNMENT=12,E_RESERVED=13,E_SHAPE=14,E_ALIAS=15,
 E_DUPLICATE=16,E_OVERLAP=17,E_NUMERIC=18,E_METADATA=19)
PROFILES={
 'smoke':[('legal-tail','A',None)],
 'control':[('legal-tail','A',None),('legal-tail','A','crc'),('legal-tail','B',None)],
 'rvv':[('legal-rvv','A',None)], 'down':[('legal-down','B',None)],
 'format':[],
 'errors':[("legal-tail",'A',fault) for fault in ('init-timeout','token-timeout','bad-block','truncated-card','media-crc','media-version','media-range','media-overflow','app-checksum','untrusted-model','ddr-timeout')]+[('legal-tail','B',None)]}
manifest=json.loads((ROOT/'tests/cocotb/fixtures/model_pack/manifest.json').read_text())
for c in manifest['cases']:
    if c.get('expected_error'):
        if c['expected_error']=='E_NUMERIC' or c['case_id']=='corrupt-payload':PROFILES['numeric'+str(sum(k.startswith('numeric') for k in PROFILES))]=[(c['case_id'],'A',None)]
        else:PROFILES['format'].append((c['case_id'],'A',None))

def trust_header(apps,out):
    good=[c for c in manifest['cases'] if not c.get('expected_error')]
    full=json.loads((ROOT/'docs/spec/model-pack-v1-manifest.json').read_text())
    def array(label,hashes):
        return f'#define NX_TRUSTED_{label.upper()} {len(hashes)}\nstatic const uint8_t nx_trusted_{label}[][32]={{'+','.join('{'+','.join('0x'+h[i:i+2] for i in range(0,64,2))+'}' for h in hashes)+'};\n'
    dots=[]
    for c in good:
        p=ROOT/'tests/cocotb/fixtures/model_pack'/c['pack']['file'];raw=p.read_bytes();offset=struct.unpack_from('<Q',raw,192+160)[0]
        dots.append(sum(struct.unpack('64b',raw[offset:offset+64])))
    p=ROOT/full['pack_path']
    if digest(p)!=full['sha256']:raise ValueError('full trusted model identity')
    with p.open('rb') as f:f.seek(full['directory'][0]['offset']);dots.append(sum(struct.unpack('64b',f.read(64))))
    Path(out).write_text('#include <stdint.h>\n'+array('models',[c['pack']['sha256'] for c in good]+[full['sha256']])+array('apps',[digest(p) for p in apps.values()])+
       'static const int32_t nx_trusted_dot[]={'+','.join(map(str,dots))+'};\n')

def prepare(out,apps,profile):
    out=Path(out);out.mkdir(parents=True);cases={c['case_id']:c for c in manifest['cases']};actions=[]
    root=ROOT/'tests/cocotb/fixtures/model_pack'
    for i,(cid,app,fault) in enumerate(PROFILES[profile]):
        c=cases[cid];pack=root/c['pack']['file'];assert digest(pack)==c['pack']['sha256']
        expected=c.get('expected_error');image=out/f'{i:02d}.img'
        build(apps[app],pack,image,validate=not expected)
        if expected:
            try:verify(pack)
            except PackError as e:assert e.code==expected
            else:raise ValueError('T10 negative unexpectedly legal')
        raw=bytearray(image.read_bytes());mstart=struct.unpack_from('<I',raw,68)[0]
        code=ERRORS.get(expected,0);transport=fault
        if fault in ('media-crc','media-version','media-range','media-overflow','app-checksum','untrusted-model'):
            if fault=='media-crc':raw[200]^=1;code=ERRORS['E_MEDIA']
            elif fault=='media-version':struct.pack_into('<I',raw,8,2);code=ERRORS['E_MEDIA']
            elif fault=='media-range':struct.pack_into('<I',raw,28,0x10000);code=ERRORS['E_BOUNDS']
            elif fault=='media-overflow':struct.pack_into('<I',raw,68,0xfffffffe);code=ERRORS['E_OVERFLOW']
            elif fault=='app-checksum':raw[36]^=1;code=ERRORS['E_CHECKSUM']
            else:
                # Valid structure and internal checksums, unknown whole-file identity.
                changed=bytearray(pack.read_bytes());changed[-64]^=1
                # Change a tokenizer blob; recompute every affected internal SHA.
                entries=struct.unpack_from('<I',changed,32)[0];record=192+(entries-1)*256
                offset,length=struct.unpack_from('<2Q',changed,record+160)
                changed[offset]^=1;changed[-64]^=1
                changed[record+192:record+224]=hashlib.sha256(changed[offset:offset+length]).digest()
                data=struct.unpack_from('<Q',changed,48)[0]
                changed[64:96]=hashlib.sha256(changed[192:192+entries*256]).digest();changed[96:128]=hashlib.sha256(changed[data:]).digest();changed[128:160]=hashlib.sha256(changed[:128]).digest()
                raw[mstart*512:mstart*512+len(changed)]=changed;raw[76:108]=hashlib.sha256(changed).digest();code=ERRORS['E_CHECKSUM']
            if fault!='media-crc':struct.pack_into('<I',raw,508,zlib.crc32(raw[:508]))
            transport=None
        elif fault=='init-timeout' or fault in ('token-timeout','truncated-card','ddr-timeout'):code=ERRORS['E_TIMEOUT']
        elif fault=='bad-block':code=ERRORS['E_CARD']
        elif fault=='crc':code=ERRORS['E_CRC']
        if fault=='truncated-card':raw=raw[:(mstart+1)*512]
        image.write_bytes(raw)
        packraw=bytes(raw[mstart*512:mstart*512+c['pack']['bytes']])
        views=[]
        if not expected or expected in ('E_CHECKSUM','E_NUMERIC'):
            legal=verify(root/cases.get(c.get('derived_from','legal-tail'),cases['legal-tail'])['pack']['file']) if expected else verify(pack)
            for e in legal.entries.values():
                if e['alias_of'] is None:
                    views.append(dict(name=e['name'],address=e['soc_address'],offset=e['offset'],bytes=e['length']))
        dot=None
        if code==0:
            first=views[0];dot=sum(struct.unpack('64b',packraw[first['offset']:first['offset']+64]))
        actions.append(dict(index=i,name=cid+(('-'+fault) if fault else ''),t10_case=cid,t10_sha256=c['pack']['sha256'],
          image=str(image.resolve()),image_sha256=digest(image),app=app,app_sha256=digest(apps[app]),
          expected_error=code,fault=transport,fault_lba=mstart+1,model_lba=mstart,model_bytes=c['pack']['bytes'],
          views=views,selftest=dot,full_payload=code==0 or expected=='E_NUMERIC' or fault=='untrusted-model'))
    fixture=dict(schema_version=1,profile=profile,producer='T18',test_mode='PROTOCOL_BOOT',actions=actions,
                 t10_manifest_sha256=digest(root/'manifest.json'),trusted_models=[c['pack']['sha256'] for c in manifest['cases'] if not c.get('expected_error')])
    golden=dict(errors=[a['expected_error'] for a in actions],ready=[int(a['expected_error']==0) for a in actions],
                signatures=[0xa1700001 if a['app']=='A' else 0xb1700002 for a in actions if a['expected_error']==0],
                initial_bytes=65536+131072+128)
    (out/'fixture.json').write_text(json.dumps(fixture,indent=2)+'\n');(out/'golden.json').write_text(json.dumps(golden,indent=2)+'\n')
    return out
