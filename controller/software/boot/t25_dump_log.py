"""Check a complete final-state :dump against an independent frozen reference."""
import re
import numpy as np
from software.boot.t25_service_log import compare


class DumpLog:
    def __init__(self,golden,limits):
        self.golden=golden;self.limits=limits;self.stage='header';self.words=[];self.index=0;self.stats=[]
        self.layers,self.values,self.length,self.width=golden['kv'].shape
        self.vocab=golden['logits'].size

    def feed(self,line):
        line=line.strip()
        if line.startswith(('T25 ERROR','T25 TRAP','T25 SD ERROR')):raise ValueError(line)
        if self.stage=='done':
            if line!='T25 READY':raise ValueError('Unexpected data after complete dump')
            return
        if self.stage=='header':
            if line!='T25 LOGITS':raise ValueError('Missing logits header')
            self.stage='logits';return
        if self.stage=='kv_header':
            if line!=f'T25 KV {self.index//self.values:08x} {self.index%self.values:08x} {self.length:08x}':
                raise ValueError('KV shape/order mismatch')
            self.stage='kv';return
        if self.stage=='end':
            if line!='T25 DUMP END':raise ValueError('Missing dump terminator')
            self.stage='done';return
        fields=line.split()
        if not fields or any(re.fullmatch('[0-9a-f]{8}',x) is None for x in fields):raise ValueError('Malformed FP32 data')
        self.words.extend(int(x,16) for x in fields)
        count=self.vocab if self.stage=='logits' else self.length*self.width
        if len(self.words)>count:raise ValueError('Extra FP32 data')
        if len(self.words)==count:
            actual=np.array(self.words,dtype='<u4').view('<f4')
            logits=self.stage=='logits'
            reference=self.golden['logits'].reshape(-1) if logits else self.golden['kv'][self.index//self.values,self.index%self.values].reshape(-1)
            stat=compare(actual,reference,self.limits['cumulative']['logits_24_layers' if logits else 'kv'])
            stat.update(kind='logits' if logits else 'kv',index=self.index)
            if logits:stat['argmax']=int(np.argmax(actual))
            else:self.index+=1
            self.stats.append(stat);self.words=[]
            self.stage='end' if self.index==self.layers*self.values else 'kv_header'

    def finish(self):
        if self.stage!='done':raise ValueError('Incomplete final dump')
        return dict(status='PASS',kv_length=self.length,compared_elements=sum(s['elements'] for s in self.stats),comparisons=self.stats)
