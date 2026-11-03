"""Independently inspect the recorded HMIC native channel and masked visibility."""
from pathlib import Path

def check_native_waveform(directory):
    path=Path(directory)/'cpu.vcd';scope=[];ids={};current={};updates={};time=0;header=True;dumped=True
    write=None;read=None;shadow={};counts={'addresses':0,'write_beats':0,'read_beats':0,'visible_bytes':0,'checks':0}
    def require(ok,detail):
        if not ok:raise ValueError('native VCD: '+detail)
        counts['checks']+=1
    def sample():
        nonlocal write,read
        nxt=current|updates
        if dumped and current.get('clk')==0 and nxt.get('clk')==1 and current.get('reset')==0:
            def value(name):
                v=current.get(name);require(v is not None,'unknown '+name);return v
            for prefix in ('aw','ar'):
                if current.get('d_'+prefix+'valid')==1 and current.get('d_'+prefix+'ready')==1:
                    address=value('d_'+prefix+'addr');identity=value('d_'+prefix+'id');length=value('d_'+prefix+'len')
                    require(current.get('ddr_init_done')==1,'transaction before init');require(identity==0,'ID must be zero')
                    require(address<0x10000000 and address%8==0,'word address/range/alignment')
                    require((address%1024)+8*(length+1)<=1024,'column boundary')
                    counts['addresses']+=1
                    if prefix=='aw':require(write is None,'overlapping native write');write=[address*4+0x80000000,length+1]
                    else:require(read is None,'overlapping native read');read=[address*4+0x80000000,length+1]
            if current.get('d_wready')==1 and write is not None:
                data=value('d_wdata');mask=value('d_wstrb');last=value('d_wlast')
                require(last==(write[1]==1),'WLAST versus native AWLEN')
                for i in range(32):
                    if mask&(1<<i):shadow[write[0]+i]=(data>>(8*i))&255
                counts['write_beats']+=1;write[0]+=32;write[1]-=1
                if not write[1]:write=None
            if current.get('d_rvalid')==1:
                require(value('d_rid')==0,'RID must be zero')
                if read is not None:
                    data=value('d_rdata');last=value('d_rlast');require(last==(read[1]==1),'RLAST versus native ARLEN')
                    for i in range(32):
                        address=read[0]+i
                        if address in shadow:require((data>>(8*i))&255==shadow[address],'masked write readback byte');counts['visible_bytes']+=1
                    counts['read_beats']+=1;read[0]+=32;read[1]-=1
                    if not read[1]:read=None
        current.update(updates);updates.clear()
    with path.open() as stream:
        for line in stream:
            parts=line.split()
            if not parts:continue
            if header:
                if parts[0]=='$scope':scope.append(parts[2])
                elif parts[0]=='$upscope':scope.pop()
                elif parts[0]=='$var' and scope==['tb_cpu'] and (parts[4].startswith('d_') or parts[4] in ('clk','reset','ddr_init_done')):ids[parts[3]]=parts[4]
                elif parts[0]=='$enddefinitions':header=False
                continue
            if line.startswith('$dumpoff'):sample();dumped=False
            elif line.startswith('$dumpon'):
                sample()
                if not dumped:current.clear();write=None;read=None;shadow.clear()
                dumped=True
            elif line[0]=='#':sample();time=int(line[1:])
            elif line[0] in '01xzXZ' and line.strip()[1:] in ids:updates[ids[line.strip()[1:]]]=int(line[0]) if line[0] in '01' else None
            elif line[0] in 'bB' and len(parts)==2 and parts[1] in ids:updates[ids[parts[1]]]=None if any(c in parts[0].lower() for c in 'xz') else int(parts[0][1:],2)
    sample()
    require(counts['addresses']>0 and counts['write_beats']>0 and counts['read_beats']>0 and counts['visible_bytes']>0,'empty native channel/visibility coverage')
    return counts
