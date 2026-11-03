"""Independent CPU-report and passive AXI ownership scoreboard for T13."""
import csv
from pathlib import Path
from common.checks import Checks
MODES=[0,0,1,6,7,2,3,4,5,8,9,10]
STATUSES=[0,0,0,0,0,-8,-7,-11,-8,-11,-11,-7]
def u32(v):return v&0xffffffff

def score(directory,golden,checks=None):
    d=Path(directory);c=checks or Checks();observed={}
    for line in (d/'cpu-output.txt').read_text().splitlines():
        group,item,value=map(int,line.split());key=(group,item)
        c.require(key not in observed,'output_set',f'duplicate {key}');observed[key]=value
    expected={}
    def expect(group,item,value,cat='state'):
        expected[group,item]=u32(value)
        c.equal(observed.get((group,item)),u32(value),cat,f'{group}:{item}')
    expect(1,0,0);expect(1,1,1)
    for i,v in enumerate([0x12345600,0x1234ab01,0xcdef5602,0x12345603]):expect(2,i,v,'lane')
    for i,v in enumerate([-4,-4,-3,-3,-5,-4,-10,-2,0]):expect(3,i,v,'reject')
    session=1;sequence=0
    for k,status in enumerate(STATUSES):
        group=10+k;sequence+=1
        for item,value in [(0,status),(1,status==0),(2,session),(3,sequence),(4,0 if status==0 else 2),(6,status),(7,1),(8,1)]:
            expect(group,item,value,'completion' if item in (0,1) else 'state')
        c.require((group,5) in observed,'interrupt','observed interrupt delta');expected[group,5]=observed.get((group,5))
        if status==0:
            for i in range(16):expect(group,32+i,golden['outputs'][str(k)][i],'data')
        else:
            expect(group,9,-10,'recovery')
            if MODES[k]==10:expect(group,10,-7,'recovery')
            expect(group,11,0,'recovery');session+=1;sequence=0
            expect(group,12,session,'recovery');expect(group,13,0,'recovery');expect(group,14,-10,'recovery')
    expect(30,0,0);expect(30,1,session)
    for i in range(16):expect(30,32+i,golden['outputs']['99'][i],'data')
    for i in range(6):expect(40,i,2,'protection')
    for i,v in enumerate([-11,2,0]):expect(41,i,v,'recovery')
    expect(42,0,0);expect(42,1,0);expect(42,3,session+1)
    c.require(observed.get((42,2),0)>0,'interrupt','actual CPU interrupt handler observed')
    expected[42,2]=observed.get((42,2))
    c.equal(set(observed),set(expected),'output_set','complete report set')
    return check_transactions(d,c),len(observed)

def check_transactions(d,c):
    events=[];native_aw=[];native_w=[];naw=[];nw=[];nr=[];pending_w=0;pending_r=0;cpu_read=None;cpu_beats=0
    launches=0;mode=0;successful_reads=0;seen_error=0;shared_reads=0;cpu_writes=0;refill=False
    starts=[];interrupts=[];early_halt=False;last_b=0;max_drain=0;last_native_aw=None;last_nr=None;last_nw=None
    for row in csv.reader((d/'transactions.csv').open()):
        cycle=int(row[0]);kind=row[1];a,data,extra=int(row[2],16),int(row[3],16),int(row[4],16);owner=int(row[5])
        events.append((cycle,kind,a,data,extra,owner))
        c.require(kind!='EARLY','visibility','owner released with outstanding backend response')
        if kind=='CW':
            cpu_writes+=1
            if a==0x100000a0:mode=data
            if a==0x20030000 and data==0:
                c.require(owner==1 and pending_w==0 and pending_r==0,'ownership','native start only after exclusive acquire/drain')
                starts.append((cycle,mode));launches+=1
            if a in (0x10000100,0x20030000) and data in (0,3):
                if a==0x10000100 and data==0 or a==0x20030000 and data==3:
                    c.require(pending_w==0 and pending_r==0,'visibility',{'control':hex(a),'pending_w':pending_w,'pending_r':pending_r})
            if (0xac000000<=a<0xb4000000 or 0xba000000<=a<0xbc000000):
                c.equal(owner,0,'ownership','CPU shared write only while CPU owns buffers')
        if kind=='CR':
            c.require(cpu_read is None,'axi','CPU data read serializes through RLAST')
            cpu_read=a;cpu_beats=data+1
            if a>=0xb4000000 and a<0xb8000000 and data==7:refill=True
            if a in range(0xba000000,0xba000040,4):
                c.equal(owner,0,'visibility','CPU reads result only after release');shared_reads+=1
            if a in range(0xac000000,0xac000040,4) or a in range(0xba000000,0xba000040,4):
                c.equal(data,0,'cache','shared region never refills a cache line')
        if kind=='IRQ':interrupts.append((cycle,data,extra))
        if kind=='CD':
            if cpu_read==0x20030008 and data&1 and pending_w:early_halt=True
            c.require(cpu_read is not None and cpu_beats>0,'axi','CPU R has request');cpu_beats-=1
            if cpu_read in range(0xba000000,0xba000040,4) and extra==0:successful_reads+=1
            if not cpu_beats:cpu_read=None
        if kind=='SA':native_aw.append((a,extra))
        if kind=='SW':native_w.append((data,extra))
        while native_aw and native_w:
            aa,size=native_aw.pop(0);dd,st=native_w.pop(0)
            c.equal(st & ~(((1<<(1<<size))-1)<<(aa&15)),0,'lane','native WSTRB fits lane/size')
            c.require(st!=0,'lane','native write has active lanes')
        if kind=='NA':
            pending_w+=1;naw.append((a,data,extra));last_nw=cycle
            c.equal(owner,1,'ownership','backend write requires owner')
        if kind=='NW':nw.append((data,extra))
        if kind=='NB':
            c.equal(pending_w,1,'axi','backend B matches accepted AW');pending_w-=1
            aa,ident,size=naw.pop(0);dd,st=nw.pop(0)
            c.equal(data,ident,'axi','BID preserved');c.equal(st,15<<(aa&15),'lane','backend write lane')
            max_drain=max(max_drain,cycle-last_nw);last_b=cycle
            seen_error+=extra!=0
        if kind=='NR':pending_r+=1;nr.append((a,data,extra));last_nr=cycle;c.equal(owner,1,'ownership','backend read requires owner')
        if kind=='ND':c.equal(pending_r,1,'axi','backend R matches AR');pending_r-=1;nr.pop(0);seen_error+=extra!=0
        if kind=='MA':c.require(0xba000000<=a<0xba000040,'protection','backend forbidden/private write never forwarded')
    c.equal([v for _,v in starts],MODES+[0],'sequence','only accepted jobs launch, in order')
    c.equal(pending_w+pending_r+len(native_aw)+len(native_w),0,'axi','all responses drained')
    c.require(early_halt,'visibility','CPU observed halted while a backend B response was still pending')
    c.require(not any(job==5 for _,job,_ in interrupts),'interrupt','dropped job notification absent, polling still completes')
    c.require(any(job>4 and job<8 and mode==0 and cycle-starts[3][0]>=16000 for cycle,job,mode in interrupts),'interrupt','late job-4 IRQ delivered after a later submission')
    c.require(max_drain>=39000,'recovery',{'delayed_write_response_cycles':max_drain})
    c.require(seen_error>=3,'fault','actual SLVERR/DECERR responses observed')
    c.require(refill,'cache','CPU private D-cache refill observed with caches enabled')
    c.equal(shared_reads,96,'data','six successful jobs each read sixteen words')
    c.equal(successful_reads,96,'visibility','all CPU result reads returned through AXI')
    c.require(cpu_writes>500,'execution','actual firmware stores/control flow')
    return {'launches':launches,'events':len(events),'max_write_drain_cycles':max_drain,'backend':'CORAL_NATIVE_TRANSACTION_TEST_DOUBLE','real_cpu':True}
