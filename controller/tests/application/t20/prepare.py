"""Immutable model outputs plus explicit fault mutations; no oracle in firmware."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from software.application_v2.program import parse,execute,ProgramError,score

def verify_model(path):
    path=Path(path);m=json.loads((path/'manifest.json').read_text())
    if m['task_id']!='T20_MODEL' or m['status']!='PASS' or m['exit_code']!=0 or (path/'exit-status.txt').read_text().strip()!='0':raise ValueError('model acceptance')
    for name,h in m['artifacts'].items():
        target=(path/name).resolve()
        if not target.is_relative_to(path.resolve()) or hashlib.sha256(target.read_bytes()).hexdigest()!=h:raise ValueError('model artifact '+name)
    source=m['source']
    if hashlib.sha256(json.dumps(source['files'],sort_keys=True,separators=(',',':')).encode()).hexdigest()!=source['sha256']:raise ValueError('model source digest')
    with tarfile.open(path/'source.tar.gz') as tar:
        if set(tar.getnames())!=set(source['files']):raise ValueError('model source inventory')
        for name,h in source['files'].items():
            if hashlib.sha256(tar.extractfile(name).read()).hexdigest()!=h:raise ValueError('model source identity')
        cases=[json.loads(l) for l in tar.extractfile('tests/application/v2/dev.jsonl').read().decode().splitlines()]
        if m.get('extra_cases'):cases += [json.loads(l) for l in tar.extractfile(m['extra_cases']).read().decode().splitlines()]
        prompts={n:tar.extractfile(n).read().decode() for n in source['files'] if n.endswith('.txt') and 'prompt' in n}
        if m['model']!=json.load(tar.extractfile('docs/spec/model-pack-v1-manifest.json')):raise ValueError('model pack identity')
    summary=json.loads((path/'summary.json').read_text())
    if summary!=m['result'] or summary['count'] not in (50,56) or summary['metrics']['legal']['rate']<0.9 or summary['metrics']['refusal']['rate']<0.95 or summary['pairs']['passed']!=summary['pairs']['total']:raise ValueError('model quality')
    if summary['count']==56 and (summary.get('multi')!={'passed':6,'total':6} or summary.get('combined_legal',{}).get('rate',0)<0.9):raise ValueError('extended legal model quality')
    rows=[json.loads(l) for l in (path/'results.jsonl').read_text().splitlines()]
    if len(rows)!=len(cases) or len(rows)!=summary['count'] or hashlib.sha256((path/'results.jsonl').read_bytes()).hexdigest()!=summary['results_sha256']:raise ValueError('model result inventory')
    for c,r in zip(cases,rows):
        if r['id']!=c['id'] or r['input']!=c['instruction'] or r['state']!=c['state'] or r['score']!=score(c,r['text'],r['stop']) or r['output_sha256']!=hashlib.sha256(r['text'].encode()).hexdigest():raise ValueError('model input/score provenance')
        if m.get('compiler'):
            candidates=r.get('candidates',[])
            order=['configs/application_v2/prompt.txt','configs/t20-prompt.txt','configs/t20-completion-prompt.txt']
            if not 1<=len(candidates)<=3 or [s['prompt'] for s in candidates]!=order[:len(candidates)]:raise ValueError('model candidate inventory')
            if r['selected_route'] not in ('PRIMARY','EXTENSION_PRESERVES_PRIMARY_NODE','EXTENSION_UNFOLDS_PRIMARY_ELSE_AS_SEPARATE_CONDITION'):raise ValueError('model selection route')
            if not any(all(r[k]==s[k] for k in ('text','output_ids','stop')) and r['selected_prompt']==s['prompt'] for s in candidates):raise ValueError('intent is not a whole model output')
        else:candidates=[dict(prompt=m.get('prompt','configs/application_v2/prompt.txt'),messages=r['messages'])]
        for s in candidates:
            msg=[dict(role='system',content=prompts[s['prompt']]),dict(role='user',content='状态：'+json.dumps(c['state'],ensure_ascii=False,separators=(',',':'))+'\n指令：'+c['instruction'])]
            if s['messages']!=msg:raise ValueError('model prompt/input identity')
    for legal,key in ((True,'legal'),(False,'refusal')):
        values=[r['score']['pass'] for c,r in zip(cases[:50],rows[:50]) if c['legal']==legal]
        if summary['metrics'][key]!=dict(passed=sum(values),total=len(values),rate=sum(values)/len(values)):raise ValueError('model aggregate score')
    pairs={c['pair_id'] for c in cases[:50] if c['pair_id']}
    passed=sum(all(r['score']['pass'] for c,r in zip(cases[:50],rows[:50]) if c['pair_id']==pair) for pair in pairs)
    if summary['pairs']!=dict(passed=passed,total=len(pairs)):raise ValueError('model paired score')
    if len(rows)==56:
        multi=dict(passed=sum(r['score']['pass'] for r in rows[50:]),total=6)
        legal=summary['metrics']['legal'];combined=dict(passed=legal['passed']+multi['passed'],total=legal['total']+6)
        combined['rate']=combined['passed']/combined['total']
        if summary['multi']!=multi or summary['combined_legal']!=combined:raise ValueError('extended aggregate score')
    repeat=json.loads((path/'repeat.json').read_text())
    if repeat['input']!=rows[0]['input'] or repeat['state']!=rows[0]['state'] or any(repeat[k]!=rows[0][k] for k in ('text','output_ids','stop')):raise ValueError('model fresh-process replay')
    if json.loads((path/'build.json').read_text())['library_sha256']!=summary['library_sha256']:raise ValueError('model library identity')
    return m

def fingerprint(s):
    h=2166136261
    for b in s.encode():h=((h^b)*16777619)&0xffffffff
    return h

def expected(row):
    if row.get('forced_status'):return dict(actions=[],readings={},error=row['forced_status'])
    try:return execute(parse(row['intent']),row['state'])
    except ProgramError as e:return dict(actions=[],readings={},error=e.code)

def prepare(model_path):
    model_path=Path(model_path)
    m=verify_model(model_path)
    if m['status']!='PASS' or m['exit_code']!=0:raise ValueError('fresh full model did not pass')
    dev=[json.loads(l) for l in (ROOT/'tests/application/v2/dev.jsonl').read_text().splitlines()]
    all_rows=[json.loads(l) for l in (model_path/'results.jsonl').read_text().splitlines()];rows=all_rows[:50]
    if len(rows)!=50 or [r['id'] for r in rows]!=[c['id'] for c in dev]:raise ValueError('development inventory')
    requests=[]
    for c,r in zip(dev,rows):
        if r['input']!=c['instruction'] or r['state']!=c['state'] or r['stop']!='eos' or hashlib.sha256(r['text'].encode()).hexdigest()!=r['output_sha256']:raise ValueError('model provenance')
        if score(c,r['text'],r['stop'])!=r['score']:raise ValueError('independent model score')
        requests.append(dict(name=c['id'],text=r['input'],intent=r['text'],state=r['state'],
            origin='DESKTOP_FULL_MODEL',output_sha256=r['output_sha256'],source_run=str(model_path.resolve()),
            expected=r['score']['actual'],semantic_expected=c['expected'],semantic_pass=r['score']['pass'],
            category=c['category'],pair_id=c['pair_id']))
    faults=[]
    mutations=[
        ('unknown-op','[["relay",1]]','FORMAT'),
        ('unknown-sensor','[["read","humidity"]]','UNSUPPORTED'),
        ('unsupported-reject','[["reject","UNSUPPORTED"]]','UNSUPPORTED'),
        ('illegal-device','[["led",1],["read","door"]]','UNSUPPORTED'),
        ('range-led','[["led",2]]','RANGE'),('range-low','[["pwm",-1]]','RANGE'),
        ('range-high','[["led",1],["pwm",101]]','RANGE'),
        ('missing-field','[["led"]]','FORMAT'),('missing-if','[["if","light",">",20,[]]]','FORMAT'),
        ('extra-field','[["led",1,0]]','FORMAT'),('bool','[["led",true]]','FORMAT'),
        ('float','[["pwm",25.0]]','FORMAT'),('string','[["pwm","25"]]','FORMAT'),
        ('overflow','[["pwm",4294967296]]','FORMAT'),('null','[["led",null]]','FORMAT'),
        ('trailing','[["led",1]] junk','FORMAT'),('truncate','[["led",1]','FORMAT'),
        ('object','{"led":1}','FORMAT'),('leading-zero','[["led",01]]','FORMAT'),
        ('bad-comparator','[["if","light","==",1,[],[]]]','FORMAT'),
        ('bad-threshold','[["if","light",">",100001,[],[]]]','FORMAT'),
        ('unselected-range','[["led",1],["if","temperature",">",100,[["pwm",101]],[]]]','RANGE'),
        ('duplicate','[["led",1],["led",1]]','DUPLICATE'),
        ('duplicate-branch','[["led",1],["if","temperature",">",0,[["led",1]],[]]]','DUPLICATE'),
        ('wide',json.dumps([['read','light']]*9),'FORMAT'),
        ('deep','[["if","light",">",0,[["if","light",">",0,[["if","light",">",0,[],[]]],[]]],[]]]','FORMAT'),
        ('total-nodes',json.dumps([['if','light','>',0,[['read','light']]*8,[['read','light']]*8]]*2),'FORMAT'),
        ('action-capacity',json.dumps([['if','temperature','>',0,[['pwm',n] for n in range(8)],[]],['led',1]]),'FORMAT'),
        ('invalid-reject','[["reject","RANGE"]]','FORMAT'),
        ('bad-condition-sensor','[["if","humidity",">",30,[],[]]]','UNSUPPORTED'),
    ]
    base=requests[0]
    for name,intent,status in mutations:
        faults.append(dict(base,name=name,intent=intent,forced_status=status,origin='EXPLICIT_FAULT_MUTATION',
            source_output_sha256=base['output_sha256'],output_sha256=hashlib.sha256(intent.encode()).hexdigest()))
    for name,status in [('nack','NACK'),('timeout','TIMEOUT'),('stale','STALE'),('future','STALE'),('epoch-change','STATE'),('sensor-low','STATE'),('sensor-high','STATE'),('light-range','STATE')]:
        faults.append(dict(base,name=name,fault=name,forced_status=status,origin='VIRTUAL_SENSOR_FAULT'))
    for name,value in [('request-zero',0),('request-overflow',0xffffffff),('request-repeat',1)]:
        faults.append(dict(base,name=name,request_id=value,forced_status='REQUEST_ID',origin='REQUEST_FAULT'))
    # Explicit current-state condition, ordering and boundary cases use documented
    # program fixtures; these are not claimed to have been generated by the model.
    extras=[]
    for name,intent,state in [
        ('empty','[]',{}),('pwm-zero','[["pwm",0]]',{}),('pwm-full','[["pwm",100]]',{}),
        ('order','[["led",1],["pwm",35],["led",0],["read","light"],["pwm",0]]',{}),
        ('conditional-hot','[["if","temperature",">",30,[["pwm",75]],[["pwm",0]]]]',{'temperature':31}),
        ('conditional-equal','[["if","temperature",">",30,[["pwm",75]],[["pwm",0]]]]',{'temperature':30}),
        ('threshold-ge','[["if","light",">=",10,[["led",1]],[["led",0]]]]',{'light':10}),
        ('threshold-le','[["if","light","<=",10,[["led",1]],[["led",0]]]]',{'light':10}),
        ('threshold-lt','[["if","light","<",10,[["led",1]],[["led",0]]]]',{'light':9}),
        ('escaped','[["l\\u0065d",1]]',{}),
        ('nested-both','[["if","temperature",">",30,[["if","light","<",100,[["led",1]],[["led",0]]]],[["pwm",0]]]]',{'temperature':31,'light':50}),
        ('nested-inner-false','[["if","temperature",">",30,[["if","light","<",100,[["led",1]],[["led",0]]]],[["pwm",0]]]]',{'temperature':31,'light':200}),
        ('nested-outer-false','[["if","temperature",">",30,[["if","light","<",100,[["led",1]],[["led",0]]]],[["pwm",0]]]]',{'temperature':29,'light':50}),
    ]:
        r=dict(base,name=name,intent=intent,state={**base['state'],**state},origin='DIRECTED_PROGRAM_FIXTURE',output_sha256=hashlib.sha256(intent.encode()).hexdigest());r['expected']=expected(r);extras.append(r)
    groups={'short':[requests[0],requests[3],extras[3],extras[4],extras[5]],'throughput':[requests[0]],'directed':extras}
    for i in range(8):groups['dev'+str(i)]=requests[i::8]
    for i in range(8):
        group=[]
        for fault in faults[i::8]:
            # Each fault is followed by a valid request to prove local recovery.
            group += [fault,dict(base,name=fault['name']+'-recover')]
        groups['fault'+str(i)]=group
    if len(all_rows)>50:
        data=[json.loads(l) for l in (ROOT/m['extra_cases']).read_text().splitlines()]
        output=all_rows[50:]
        if len(data)!=6 or len(output)!=6:raise ValueError('multi-condition inventory')
        groups['multi']=[]
        for i,(case,row) in enumerate(zip(data,output)):
            evaluated=score(case,row['text'],row['stop'])
            if case['id']!=row['id'] or evaluated!=row['score'] or not evaluated['pass']:raise ValueError('multi-condition scoring identity')
            groups['multi'].append(dict(name=row['id'],id=i+1,epoch=1,text=row['input'],intent=row['text'],state=row['state'],origin='DESKTOP_FULL_MODEL_MULTI',
                output_sha256=row['output_sha256'],source_run=str(model_path),expected=evaluated['actual'],semantic_expected=case['expected'],semantic_pass=evaluated['pass'],fnv32=fingerprint(row['text'])))
    for name in [*(f'dev{i}' for i in range(8)),*(['multi'] if 'multi' in groups else [])]:
        initialized=[]
        for row in groups[name]:
            row=dict(row,check_actuator_snapshot=True)
            intent=json.dumps([['led',row['state']['led']],['pwm',row['state']['pwm']]],separators=(',',':'))
            setup=dict(name=row['name']+'-state-precondition',text='T20 explicit CPU actuator precondition',intent=intent,state=row['state'],origin='CPU_STATE_PRECONDITION',output_sha256=hashlib.sha256(intent.encode()).hexdigest())
            setup['expected']=expected(setup);initialized += [setup,row]
        groups[name]=initialized
    for group in groups.values():
        last=0
        for i,r in enumerate(group):
            r=dict(r);r['id']=r.get('request_id',i+1);r['epoch']=1
            if r['name']=='request-repeat':r['id']=last
            if r['id'] not in (0,0xffffffff):last=max(last,r['id'])
            r['expected']=expected(r) if r.get('forced_status') else r['expected']
            r['fnv32']=fingerprint(r['intent']);group[i]=r
    return dict(schema_version=1,producer='T20',generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),checker_sha256=hashlib.sha256((ROOT/'tests/cocotb/test_application.py').read_bytes()).hexdigest(),model_run=str(model_path.resolve()),model_manifest_sha256=hashlib.sha256((model_path/'manifest.json').read_bytes()).hexdigest(),
        dtype='UTF8_JSON_PROGRAM_AND_LE_U32_SENSOR_PACKET',shape='bounded AST depth2/nodes32/actions8',stride='n/a',endian='little',
        group_size='n/a',layout_id='n/a',logical_view='UART request -> CPU validated program -> external GPIO/PWM pins',
        tolerance='exact integer, order and byte comparisons',groups=groups)
