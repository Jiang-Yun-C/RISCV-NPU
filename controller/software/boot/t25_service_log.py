"""Strict T25 :verify transcript decoder and frozen-T05 numerical comparison.

Only decodes board output; never executes a host model or supplies logits/KV.
"""
import re
import numpy as np


def compare(actual,reference,tolerance):
    if actual.shape!=reference.shape:raise ValueError('Shape mismatch')
    a=actual.astype('f8');b=reference.astype('f8');delta=np.abs(a-b)
    if not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError('Nonfinite board/reference data')
    nrmse=float(np.sqrt(np.mean(delta**2))/max(float(np.sqrt(np.mean(b**2))),1e-12))
    bad=delta>tolerance['atol']+tolerance['rtol']*np.abs(b)
    if bad.any() or nrmse>tolerance['nrmse']:
        raise ValueError(f'Frozen numeric gate failed: max_abs={delta.max()} nrmse={nrmse}')
    return dict(elements=actual.size,max_abs=float(delta.max()),nrmse=nrmse)


class VerifyLog:
    def __init__(self,golden,limits,layers=24,width=128):
        self.golden=golden;self.limits=limits;self.layers=layers;self.width=width
        self.vocab=golden['logits'].shape[1];self.steps=golden['logits'].shape[0]
        self.stage='step';self.index=0;self.words=[];self.kv_index=0;self.stats=[]
        self.output=None;self.metrics=None;self.step_fields=None

    def feed(self,line):
        line=line.strip()
        if line.startswith(('T25 ERROR ','T25 TRAP ','T25 SD ERROR ')):raise ValueError(line)
        if self.stage=='step':
            if line.startswith('T25 STEP '):
                if self.index>=self.steps:raise ValueError('Extra forward step')
                fields=line.split()
                if len(fields)!=4:raise ValueError('Malformed STEP')
                prefilled,generated=map(lambda s:int(s,16),fields[2:])
                prompt=len(self.golden['input_ids'])
                expected=(min(self.index+1,prompt),max(0,self.index-prompt+2))
                if (prefilled,generated)!=expected:raise ValueError('Forward sequence changed')
                self.step_fields=(prefilled,generated);self.stage='logits_header'
            elif line.startswith('T25 IDS '):
                if self.index!=self.steps or self.output is not None:raise ValueError('Premature/duplicate output')
                self.output=np.array([int(x,16) for x in line.split()[2:]],dtype='<u4')
                if not np.array_equal(self.output,self.golden['output_ids']):raise ValueError('Generated token sequence differs from frozen golden')
            elif line.startswith('T25 METRICS '):
                if self.output is None or self.metrics is not None:raise ValueError('Premature/duplicate metrics')
                self.metrics={k:int(v,16) for k,v in re.findall(r'(\w+)=([0-9a-f]{16})(?: |$)',line)}
                for key in ('generated','prompt','kv','ce_calls','fallback_calls','stack_peak_bytes','first_token_ticks','total_ticks'):
                    if key not in self.metrics:raise ValueError('Missing metric '+key)
                if self.metrics['generated']!=len(self.output) or self.metrics['prompt']!=len(self.golden['input_ids']) or self.metrics['kv']!=self.steps:
                    raise ValueError('Output/metrics identity mismatch')
                if self.metrics['ce_calls']<=0 or self.metrics['fallback_calls']!=0:raise ValueError('Missing CE route or unexpected fallback')
            return
        if self.stage=='logits_header':
            if line!='T25 LOGITS':raise ValueError('Missing logits header')
            self.stage='logits';self.words=[];return
        if self.stage=='kv_header':
            fields=line.split()
            if len(fields)!=5 or fields[:2]!=['T25','KV']:raise ValueError('Missing KV header')
            layer,value,length=[int(x,16) for x in fields[2:]]
            if (layer,value,length)!=(self.kv_index//2,self.kv_index%2,self.index+1):raise ValueError('Reordered/duplicate/stale KV header')
            self.stage='kv';self.words=[];return
        if self.stage=='end':
            if line!='T25 DUMP END':raise ValueError('Missing complete dump terminator')
            self.index+=1;self.stage='step';return
        if self.stage in ('logits','kv'):
            fields=line.split()
            if not fields or any(re.fullmatch('[0-9a-f]{8}',x) is None for x in fields):raise ValueError('Malformed/missing board FP32 words')
            self.words.extend(int(x,16) for x in fields)
            count=self.vocab if self.stage=='logits' else (self.index+1)*self.width
            if len(self.words)>count:raise ValueError('Extra board FP32 words')
            if len(self.words)==count:
                actual=np.array(self.words,dtype='<u4').view('<f4')
                if self.stage=='logits':
                    ref=self.golden['logits'][self.index]
                    stats=compare(actual,ref,self.limits['cumulative']['logits_24_layers'])
                    # Full greedy sequence is checked independently above.
                    stats.update(step=self.index,kind='logits',argmax=int(np.argmax(actual)))
                    output_index=self.index-len(self.golden['input_ids'])+1
                    if output_index>=0 and stats['argmax']!=int(self.golden['output_ids'][output_index]):
                        raise ValueError('Published token is not the board logits greedy argmax')
                    self.kv_index=0;self.stage='kv_header'
                else:
                    layer,value=self.kv_index//2,self.kv_index%2
                    ref=self.golden['kv'][layer,value,:self.index+1,:].reshape(-1)
                    stats=compare(actual,ref,self.limits['cumulative']['kv'])
                    stats.update(step=self.index,kind='kv',layer=layer,value=value)
                    self.kv_index+=1;self.stage='end' if self.kv_index==self.layers*2 else 'kv_header'
                self.stats.append(stats);self.words=[]

    def finish(self):
        if self.stage!='step' or self.index!=self.steps or self.output is None or self.metrics is None:
            raise ValueError('Incomplete board generation/dumps/metrics')
        return dict(status='PASS',forward_steps=self.index,generated=len(self.output),metrics=self.metrics,
            compared_elements=sum(x['elements'] for x in self.stats),comparisons=self.stats)
