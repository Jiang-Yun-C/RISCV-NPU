"""Independent original tokenizer truth; control inputs are never model claims."""
import json
from pathlib import Path
from tests.runtime.tokenizer_reference import official

def generate(dest,selection=None):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    ref,hf=official()
    bs=list(range(33,127))+list(range(161,173))+list(range(174,256));cs=bs[:];n=0
    for b in range(256):
        if b not in bs:bs.append(b);cs.append(256+n);n+=1
    chars=dict(zip(bs,map(chr,cs)));vocab=ref.get_vocab()
    def byte_ids(s):return [vocab[chars[b]] for b in s.encode()]
    split=byte_ids('中🌍')+[151645]
    cases=[dict(name='split',ids=split),dict(name='empty',ids=[151665,151645]),
           dict(name='flush',ids=byte_ids('中')[:1]+[151645]),
           dict(name='escaped',ids=ref.encode('A\nT25 READY\n🌍',add_special_tokens=False).ids+[151645]),
           dict(name='capacity',ids=split,capacity=2,error=-4),
           dict(name='fault',ids=byte_ids('A中'),fault=1,error=-8),
           dict(name='timeout',ids=byte_ids('A中'),fault=2,error=-7),
           dict(name='reset_pending',ids=split,fault=3,error=-8),
           dict(name='after_reset',ids=split),dict(name='max_one',ids=split,maximum=1),
           dict(name='context511',ids=split,prompt=511),dict(name='context512',ids=split,prompt=512),
           dict(name='legacy',ids=split,enabled=0),dict(name='text',ids=split,text='你好🌍',maximum=3)]
    if selection is not None:
        cases=[c for c in cases if c['name'] in selection]
        for c in cases:c['ids']=ref.encode('中',add_special_tokens=False).ids+[151645]
    header=['/* Frozen CONTROL_ONLY next IDs, never model output claims. */']
    for i,c in enumerate(cases):
        c.setdefault('capacity',16384);c.setdefault('enabled',1);c.setdefault('fault',0);c.setdefault('prompt',1)
        c.setdefault('maximum',len(c['ids']));c.setdefault('error',0)
        actual=c['ids'][:min(c['maximum'],512-c['prompt'])]
        if 151645 in actual:actual=actual[:actual.index(151645)+1]
        c['expected_ids']=actual if not c['error'] else []
        c['expected_text']=ref.decode(actual,skip_special_tokens=True) if not c['error'] else None
        c['stop']=1 if actual and actual[-1]==151645 else 3 if c['prompt']+len(actual)==512 else 2
        c['expected_prompt_ids']=hf.apply_chat_template([dict(role='user',content=c['text'])],tokenize=True,add_generation_prompt=True) if c.get('text') else [0]*c['prompt']
        header.append(f'static const uint32_t ids_{i}[]={{'+','.join(map(str,c['ids']))+'};')
    header.append('typedef struct {const uint32_t *ids;unsigned count,capacity,enabled,fault,prompt,maximum;const char *text;} fixture;')
    header.append('static const fixture fixtures[]={')
    for i,c in enumerate(cases):header.append('{ids_%d,%d,%d,%d,%d,%d,%d,%s},'%(i,len(c['ids']),c['capacity'],c['enabled'],c['fault'],c['prompt'],c['maximum'],json.dumps(c.get('text'),ensure_ascii=False) if c.get('text') else '0'))
    header.append('};')
    (dest/'inputs.h').write_text('\n'.join(header)+'\n')
    (dest/'golden.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    return cases
