"""Independent byte scoreboard and delayed simplified-port environment.

The DUT is real synthesizable RTL. This environment models digital user-port
semantics only; PHY calibration and physical bandwidth are outside its scope.
"""
import json
import os
from pathlib import Path
import random
import sys
import cocotb
from cocotb.triggers import Timer
from cocotb.utils import get_sim_time
from common.checks import Checks, digest

ROOT = Path(__file__).resolve().parents[2]


class Adapter:
    def __init__(self, dut, cfg, checks):
        self.d, self.cfg, self.c = dut, cfg, checks
        self.rng = random.Random(cfg['seed'])
        self.bus = cfg['data_width']//8
        self.cycles = 0
        self.events, self.transactions = [], []
        self.mem, self.golden = {}, {}
        self.write = self.read = None
        self.commits = []
        self.previous = {}
        self.inject = None
        self.aw_log, self.ar_log = [], []
        self.written = self.returned = 0

    def v(self, n):
        return int(getattr(self.d, n).value)

    def set(self, **values):
        for n, value in values.items():
            getattr(self.d, n).value = value

    async def tick(self):
        self.cycles += 1
        self.c.require(self.cycles <= self.cfg['max_cycles'], 'completion', 'bounded simulation cycles')
        for due, writes in self.commits[:]:
            if due <= self.cycles:
                self.mem.update(writes)
                self.commits.remove((due, writes))
        wr, rd = self.write, self.read
        ready_w = int(wr is not None and self.rng.randrange(4) != 0)
        valid_r = int(rd is not None and self.rng.randrange(4) != 0)
        self.set(d_awready=int(wr is None and rd is None and self.inject != 'timeout' and self.rng.randrange(4)!=0),
                 d_arready=int(wr is None and rd is None and self.inject != 'read-timeout' and self.rng.randrange(4)!=0),
                 d_wready=ready_w, d_wlast=int(bool(wr) and wr['beat']==wr['len']),
                 d_rvalid=valid_r, d_rid=7 if self.inject=='rid' else 0)
        if wr and self.inject=='wlast':
            self.d.d_wlast.value = 1-int(wr['beat']==wr['len'])
        if rd:
            # Model the documented column wrap, so a bad native split aliases.
            word = (rd['word'] & ~1023) | ((rd['word']+8*rd['beat']) & 1023)
            payload = int.from_bytes(bytes(self.mem.get(word*4+i, 0) for i in range(32)), 'little')
            if self.inject=='data':
                payload ^= 1
            last = rd['beat']==rd['len']
            self.set(d_rdata=payload, d_rlast=int(not last if self.inject=='rlast' else last))
        await Timer(1, unit='ns')
        snap={n:self.v(n) for n in ('s_awready','s_arready','s_wready','s_bvalid','s_rvalid','fault')}
        if snap['s_bvalid']:
            snap.update(bid=self.v('s_bid'), bresp=self.v('s_bresp'))
        if snap['s_rvalid']:
            snap.update(rid=self.v('s_rid'), rresp=self.v('s_rresp'), rlast=self.v('s_rlast'), rdata=self.v('s_rdata'))
        edge=int(get_sim_time(unit='ps'))
        if self.v('rst_n'):
            channels=(
                ('saw', self.v('s_awvalid') and snap['s_awready'], ('s_awaddr','s_awid','s_awlen','s_awsize','s_awburst')),
                ('sw', self.v('s_wvalid') and snap['s_wready'], ('s_wdata','s_wstrb','s_wlast')),
                ('sar', self.v('s_arvalid') and snap['s_arready'], ('s_araddr','s_arid','s_arlen','s_arsize','s_arburst')),
                ('sb', snap['s_bvalid'] and self.v('s_bready'), ('s_bid','s_bresp')),
                ('sr', snap['s_rvalid'] and self.v('s_rready'), ('s_rdata','s_rid','s_rresp','s_rlast')),
                ('aw', self.v('d_awvalid') and self.v('d_awready'), ('d_awaddr','d_awlen','d_awid')),
                ('w', self.v('adapter_state')==5 and self.v('d_wready'), ('d_wdata','d_wstrb','d_wlast')),
                ('ar', self.v('d_arvalid') and self.v('d_arready'), ('d_araddr','d_arlen','d_arid')),
                ('r', self.v('adapter_state')==8 and self.v('d_rvalid'), ('d_rdata','d_rid','d_rlast')),
            )
            for ch, active, fields in channels:
                if active:
                    self.events.append([edge,ch,*[self.v(n) for n in fields]])
            # Check native address and AXI B/R stability through arbitrary gaps.
            for ch, valid, ready, fields in (
                ('aw',self.v('d_awvalid'),self.v('d_awready'),('d_awaddr','d_awlen','d_awid')),
                ('ar',self.v('d_arvalid'),self.v('d_arready'),('d_araddr','d_arlen','d_arid')),
                ('b',snap['s_bvalid'],self.v('s_bready'),('s_bid','s_bresp')),
                ('r',snap['s_rvalid'],self.v('s_rready'),('s_rdata','s_rid','s_rresp','s_rlast')),
            ):
                value=tuple(self.v(n) for n in fields) if valid else None
                if ch in self.previous and not snap['fault']:
                    self.c.equal(value,self.previous[ch],'stability',ch+' stable until accepted')
                if valid and not ready:
                    self.previous[ch]=value
                else:
                    self.previous.pop(ch,None)
            if self.v('d_awvalid') and self.v('d_awready'):
                self.c.require(wr is None and rd is None,'native_protocol','no overlapping native burst')
                word, length=self.v('d_awaddr'),self.v('d_awlen')
                self.c.equal(self.v('d_awid'),0,'id','fixed vendor write ID0')
                self.c.require(word%8==0 and (word&1023)+8*(length+1)<=1024,'address','native word unit and column boundary')
                self.aw_log.append((word,length))
                self.write={'word':word,'len':length,'beat':0,'bytes':{}}
            if self.v('d_arvalid') and self.v('d_arready'):
                self.c.require(wr is None and rd is None,'native_protocol','no overlapping native read')
                word, length=self.v('d_araddr'),self.v('d_arlen')
                self.c.equal(self.v('d_arid'),0,'id','fixed vendor read ID0')
                self.c.require(word%8==0 and (word&1023)+8*(length+1)<=1024,'address','native read address and boundary')
                self.ar_log.append((word,length))
                self.read={'word':word,'len':length,'beat':0}
            if wr and ready_w and self.v('adapter_state')==5:
                data, mask=self.v('d_wdata'),self.v('d_wstrb')
                word=(wr['word']&~1023)|((wr['word']+8*wr['beat'])&1023)
                for i in range(32):
                    if mask>>i&1:
                        value=data>>(8*i)&255
                        if not self.inject:
                            self.c.equal(value,self.golden.get(word*4+i,0),'write_data','independent native enabled byte')
                        wr['bytes'][word*4+i]=value
                wr['beat']+=1
                if wr['beat']==wr['len']+1:
                    self.commits.append((self.cycles+(1000 if self.inject=='stale' else 6),wr['bytes']))
                    self.write=None
            if rd and valid_r and self.v('adapter_state')==8:
                rd['beat']+=1
                if rd['beat']==rd['len']+1:
                    self.read=None
        self.d.clk.value=1
        await Timer(4, unit='ns')
        self.d.clk.value=0
        await Timer(5, unit='ns')
        return snap

    async def reset(self):
        self.set(rst_n=0,ddr_init_done=0,s_awvalid=0,s_arvalid=0,s_wvalid=0,s_bready=0,s_rready=0)
        self.write=self.read=None
        self.commits=[]; self.previous={}; self.inject=None
        self.written=self.returned=0
        for _ in range(3):
            await self.tick()
        self.c.equal(self.v('fault'),0,'recovery','fault clears only on coordinated reset')
        if self.cfg.get('negative')=='held-reset':
            # Issue a real request with reset continuously asserted. The normal
            # bounded handshake driver must time out on the DUT's inactive port.
            self.d.ddr_init_done.value=1
            await self.request('aw',0x80000000,1,0,1)
            self.c.equal(self.v('s_awready'),0,'completion','reset cannot admit a request')
        self.d.rst_n.value=1
        self.set(s_awvalid=1,s_awaddr=0x80000000,s_awlen=0,s_awsize=0)
        for _ in range(7):
            snap=await self.tick()
            self.c.equal(snap['s_awready']|snap['s_arready']|self.v('d_awvalid')|self.v('d_arvalid'),0,
                         'calibration_gate','no requests before real init_done input')
        self.set(s_awvalid=0,ddr_init_done=1)
        await self.tick()

    def bursts(self, addr, count, size):
        start=addr&~31; end=addr+(count<<size)
        out=[]
        while start<end:
            beats=min(16,((end-start+31)//32),(4096-(start&4095))//32)
            out.append(((start-0x80000000)//4,beats-1)); start+=beats*32
        return out

    async def request(self,ch,addr,count,size,ident,burst=1):
        self.set(**{f's_{ch}addr':addr,f's_{ch}len':count-1,f's_{ch}size':size,
                    f's_{ch}id':ident,f's_{ch}burst':burst,f's_{ch}valid':1})
        for _ in range(300):
            snap=await self.tick()
            if snap[f's_{ch}ready']:
                self.set(**{f's_{ch}valid':0}); return
        self.c.require(False,'completion','address handshake timeout')

    async def write_tx(self,addr,data,masks,size,ident=0,expected=0,burst=1,bad_last=False):
        before_aw,before_ar=len(self.aw_log),len(self.ar_log)
        if expected==0:
            for beat,(value,mask) in enumerate(zip(data,masks)):
                cursor=addr+(beat<<size); lane=cursor%self.bus
                for byte in range(1<<size):
                    if mask>>(lane+byte)&1:
                        self.golden[cursor+byte-0x80000000]=value>>(8*(lane+byte))&255
        await self.request('aw',addr,len(data),size,ident,burst)
        for beat,(value,mask) in enumerate(zip(data,masks)):
            for _ in range(self.rng.randrange(3)):
                await self.tick()
            last=int(beat==len(data)-1)
            self.set(s_wvalid=1,s_wdata=value,s_wstrb=mask,s_wlast=1-last if bad_last else last)
            for _ in range(300):
                if (await self.tick())['s_wready']:
                    break
            else:
                self.c.require(False,'completion','AXI W handshake timeout')
            self.d.s_wvalid.value=0
        for _ in range(3000):
            snap=await self.tick()
            if snap['s_bvalid']:
                break
        else:
            self.c.require(False,'completion','write response timeout')
        self.c.equal(snap['bid'],ident,'id','AXI write ID restored')
        self.c.equal(snap['bresp'],expected,'visibility','B OKAY only after masked readback')
        for _ in range(5):
            snap=await self.tick()
            self.c.equal(snap['bresp'],expected,'stability','B held through backpressure')
        self.d.s_bready.value=1
        await self.tick(); self.d.s_bready.value=0
        if expected==0:
            self.written+=sum(m.bit_count() for m in masks)
            self.c.equal(self.aw_log[before_aw:],self.bursts(addr,len(data),size),'burst','write split LEN+1')
            self.c.equal(self.ar_log[before_ar:],self.bursts(addr,len(data),size),'visibility','independent readback of every written line')
            self.c.require(not self.commits,'visibility','writes committed before B handshake')
            for a,v in self.golden.items():
                self.c.equal(self.mem.get(a,0),v,'byte_enable','complete enabled/untouched byte scoreboard')
        elif not self.inject:
            self.c.equal(len(self.aw_log),before_aw,'reject','invalid AXI causes no DDR write')
        self.transactions.append(['write',addr,len(data),size,ident,expected])

    async def read_tx(self,addr,count,size,ident=0,expected=0,burst=1,fixture=None):
        before=len(self.ar_log)
        await self.request('ar',addr,count,size,ident,burst)
        actual=[]
        for beat in range(count):
            self.d.s_rready.value=0
            for _ in range(3000):
                snap=await self.tick()
                if snap['s_rvalid']:
                    break
            else:
                self.c.require(False,'completion','read response timeout')
            for _ in range(self.rng.randrange(4)):
                await self.tick()
            self.d.s_rready.value=1
            snap=await self.tick()
            self.d.s_rready.value=0
            self.c.equal(snap['rid'],ident,'id','AXI read ID restored')
            self.c.equal(snap['rresp'],expected,'fault' if expected==2 else 'read_data','AXI read response')
            self.c.equal(snap['rlast'],int(beat==count-1),'burst','exact AXI RLAST')
            cursor=addr+(beat<<size); lane=cursor%self.bus
            golden=sum(self.golden.get(cursor+i-0x80000000,0)<<(8*(lane+i)) for i in range(1<<size)) if expected==0 else 0
            if self.cfg.get('negative')=='bad-golden': golden^=1
            self.c.equal(snap['rdata'],golden,'read_data','independent byte addressed read result')
            if fixture is not None:
                shifted=fixture[beat]<<((cursor%self.bus-cursor%4)*8)
                self.c.equal(snap['rdata'],shifted,'t04','frozen T04 RTL response replay')
            actual.append(snap['rdata'])
        if expected==0:
            self.returned+=count*(1<<size)
            self.c.equal(self.ar_log[before:],self.bursts(addr,count,size),'burst','read split and full buffering')
        elif expected==3:
            self.c.equal(len(self.ar_log),before,'reject','invalid AXI causes no DDR read')
        self.transactions.append(['read',addr,count,size,ident,expected,actual])

    async def generated(self):
        size=self.bus.bit_length()-1
        for addr,count in [(0x80000000,1),(0x80000200,33),(0x80001000,256),(0xbffff000,256)]:
            if count*self.bus>4096: continue
            data=[self.rng.getrandbits(self.bus*8) for _ in range(count)]
            masks=[(1<<self.bus)-1 for _ in data]
            await self.write_tx(addr,data,masks,size,63)
            await self.read_tx(addr,count,size,37)
        # Explicitly visit every high address bit independently, preserving old addresses.
        addresses=[0x80000000]+[0x80000000+(1<<bit) for bit in range(5,30)]+[0xbfffffe0]
        for i,addr in enumerate(addresses):
            await self.write_tx(addr,[self.rng.getrandbits(self.bus*8)],[(1<<self.bus)-1],size,i%64)
        for i,addr in enumerate(addresses):
            await self.read_tx(addr,1,size,(63-i)%64)
        # One-byte masks at every byte of a native 256-bit line.
        for i in range(32):
            addr=0x80003000+i; lane=addr%self.bus
            await self.write_tx(addr,[(i^0xa5)<<(lane*8)],[1<<lane],0,i)
        await self.read_tx(0x80003000,32,0,17)
        for _ in range(12):
            sz=self.rng.randrange(size+1); count=self.rng.randrange(1,25)
            addr=0x80008000+self.rng.randrange(0,512)*(1<<sz)
            count=min(count,(4096-(addr&4095))>>sz)
            data=[self.rng.getrandbits(self.bus*8) for _ in range(count)]
            masks=[]
            for beat in range(count):
                lane=(addr+(beat<<sz))%self.bus
                masks.append(self.rng.getrandbits(1<<sz)<<lane)
            await self.write_tx(addr,data,masks,sz,self.rng.randrange(64))
            await self.read_tx(addr,count,sz,self.rng.randrange(64))
        self.c.equal(self.v('write_payload_bytes'),self.written,'counters','64-bit enabled write payload')
        self.c.equal(self.v('read_payload_bytes'),self.returned,'counters','64-bit accepted read payload')

    async def t04(self):
        await self.reset()
        self.mem={}; self.golden={}  # New T04 external fixture, explicitly empty.
        fixture=json.loads((ROOT/'tests/cocotb/fixtures/t04-memory-subset.json').read_text())
        for w in fixture['writes']:
            data=[]; masks=[]
            for i,(d,m) in enumerate(zip(w['data'],w['strobes'])):
                addr=w['addr']+(i<<w['size']); shift=addr%self.bus-addr%4
                data.append(d<<(shift*8)); masks.append(m<<shift)
            await self.write_tx(w['addr'],data,masks,w['size'],w['id'])
        for i,r in enumerate(fixture['reads']):
            await self.read_tx(r['addr'],r['beats'],r['size'],i%64,fixture=r['expected'])
        self.c.require(len(fixture['writes'])==141 and len(fixture['reads'])==148,'t04','complete frozen aligned INCR subset')

    async def t14(self):
        import hashlib
        fixture=json.loads((ROOT/'tests/ddr/t14-boundaries.json').read_text())
        for case in fixture['cases']:
            payload=bytes.fromhex(case['payload_hex'])
            self.c.equal(hashlib.sha256(payload).hexdigest(),case['payload_sha256'],'t14','frozen boundary input identity')
            for addr in (case['source_address'],case['destination_address']):
                offset=0
                while offset<len(payload):
                    cursor=addr+offset; left=len(payload)-offset
                    full=cursor%self.bus==0 and left>=self.bus
                    size=self.bus.bit_length()-1 if full else 0
                    step=1<<size
                    count=min(256,left//step,(4096-(cursor&4095))//step)
                    if not full: count=min(count,self.bus-cursor%self.bus)
                    data=[]; masks=[]
                    for beat in range(count):
                        lane=(cursor+beat*step)%self.bus
                        value=int.from_bytes(payload[offset+beat*step:offset+(beat+1)*step],'little')
                        data.append(value<<(8*lane)); masks.append(((1<<step)-1)<<lane)
                    await self.write_tx(cursor,data,masks,size,23)
                    await self.read_tx(cursor,count,size,41)
                    offset+=count*step
                actual=bytes(self.golden[addr+i-0x80000000] for i in range(len(payload)))
                self.c.equal(actual,payload,'t14','all frozen row/tail bytes consumed')

    async def contention(self):
        # Two continuously pending masters, represented by distinct AXI IDs.
        # Only one is admitted; both complete without vendor multi-ID assumptions.
        await self.read_tx(0x80005000,1,0,1)
        self.golden[0x5000]=0x5c
        self.set(s_awaddr=0x80005000,s_awlen=0,s_awsize=0,s_awid=31,s_awburst=1,s_awvalid=1,
                 s_araddr=0x80005000,s_arlen=0,s_arsize=0,s_arid=47,s_arburst=1,s_arvalid=1)
        snap=await self.tick()
        self.c.equal((snap['s_awready'],snap['s_arready']),(1,0),'arbitration','round-robin single admission')
        self.set(s_awvalid=0,s_wvalid=1,s_wdata=0x5c,s_wstrb=1,s_wlast=1)
        for _ in range(200):
            snap=await self.tick()
            self.c.equal(snap['s_arready'],0,'arbitration','pending read backpressured during write')
            if snap['s_wready']: break
        else: self.c.require(False,'completion','contended W timeout')
        self.d.s_wvalid.value=0
        for _ in range(1000):
            snap=await self.tick()
            if snap['s_bvalid']: break
        else: self.c.require(False,'completion','contended B timeout')
        self.c.equal(snap['bid'],31,'arbitration','writer response owner')
        self.c.equal(snap['bresp'],0,'visibility','writer verified before reader admission')
        self.d.s_bready.value=1
        await self.tick(); self.d.s_bready.value=0
        snap=await self.tick()
        self.c.equal(snap['s_arready'],1,'arbitration','held reader eventually admitted')
        self.d.s_arvalid.value=0
        for _ in range(1000):
            snap=await self.tick()
            if snap['s_rvalid']: break
        else: self.c.require(False,'completion','contended R timeout')
        self.c.equal((snap['rid'],snap['rresp'],snap['rdata']),(47,0,0x5c),'visibility','reader observes completed writer')
        self.d.s_rready.value=1
        await self.tick(); self.d.s_rready.value=0

    async def errors(self):
        for addr,count,sz,burst in [(0x7ffffffc,1,2,1),(0xc0000000,1,2,1),
                                    (0xbffffffc,2,2,1),(0x80000ffc,2,2,1),
                                    (0x80000001,1,2,1),(0x80000000,1,2,0),(0x80000000,1,2,2),
                                    (0x80000000,1,6,1)]:
            await self.read_tx(addr,count,sz,63,3,burst)
            await self.write_tx(addr,[0]*count,[0]*count,sz,63,3,burst)
        await self.write_tx(0x80000000,[0],[0],0,4,2,bad_last=True)
        if self.bus>4:
            await self.write_tx(0x80000000,[0],[1<<4],2,5,2)
        for kind,reason in [('wlast',3),('rid',4),('rlast',5),('data',6),('stale',6),('timeout',2)]:
            await self.reset(); self.mem={}; self.golden={}; self.inject=kind
            await self.write_tx(0x80000000,[(1<<64)-1 if self.bus>=8 else 0xffffffff],[(1<<self.bus)-1],self.bus.bit_length()-1,13,2)
            self.c.equal(self.v('fault'),1,'fault',kind+' quarantines native port')
            self.c.equal(self.v('fault_reason'),reason,'fault',kind+' reason')
            self.d.s_awvalid.value=1
            for _ in range(4):
                self.c.equal((await self.tick())['s_awready'],0,'fault','no reuse of uncancellable native burst')
            self.d.s_awvalid.value=0
        await self.reset(); self.inject='read-timeout'
        await self.read_tx(0x80000000,3,0,29,2)
        self.c.equal(self.v('fault_reason'),2,'fault','read timeout reason')
        # Lose calibration while the buffer is being prepared. An accepted
        # AW still requires all declared W beats before an error B response.
        await self.reset(); await self.request('aw',0x80000000,2,0,12)
        self.set(ddr_init_done=0,s_wvalid=1,s_wdata=0,s_wstrb=0,s_wlast=0)
        for beat in range(2):
            self.d.s_wlast.value=int(beat==1)
            for _ in range(200):
                snap=await self.tick()
                self.c.equal(snap['s_bvalid'],0,'fault','no premature B after calibration loss')
                if snap['s_wready']: break
            else: self.c.require(False,'completion','calibration loss during buffer preparation')
        self.d.s_wvalid.value=0
        snap=await self.tick()
        self.c.equal((snap['bid'],snap['bresp']),(12,2),'fault','prepared-buffer failure drains W')
        # Calibration loss after accepted AW: finish consuming W, then error.
        await self.reset(); await self.request('aw',0x80000000,2,0,11)
        while self.v('adapter_state')!=2: await self.tick()
        self.set(ddr_init_done=0,s_wvalid=1,s_wdata=0,s_wstrb=0,s_wlast=0)
        for beat in range(2):
            self.d.s_wlast.value=int(beat==1)
            for _ in range(200):
                if (await self.tick())['s_wready']: break
            else: self.c.require(False,'completion','calibration loss W drain')
        self.d.s_wvalid.value=0
        snap=await self.tick()
        self.c.equal(snap['bresp'],2,'fault','calibration loss cannot complete successfully')
        self.c.equal(self.v('fault_reason'),1,'fault','calibration loss quarantine')
        await self.reset()
        # Reset an outstanding vendor read; controller/environment reset is coordinated.
        await self.request('ar',0x80000000,16,0,7)
        while not self.read: await self.tick()
        await self.reset()
        await self.write_tx(0x80005000,[0x5a],[1],0,2)
        await self.read_tx(0x80005000,1,0,2)
        self.c.equal(self.v('fault'),0,'recovery','fresh operation after interrupted read')


@cocotb.test()
async def ddr_adapter(dut):
    cfg=json.loads(Path(os.environ['NEXUSRV_CASE']).read_text())
    checks=Checks(); adapter=Adapter(dut,cfg,checks)
    try:
        checks.equal(cfg['test_mode'],'COMPONENT','input_identity','digital adapter qualification scope')
        await adapter.reset()
        await adapter.generated()
        await adapter.contention()
        await adapter.t04()
        await adapter.t14()
        await adapter.errors()
    except BaseException as error:
        if checks.first_failure is None:
            checks.first_failure={'category':'execution','detail':str(error)}
        raise
    finally:
        observed={'events':adapter.events,'transactions':adapter.transactions,'cycles':adapter.cycles,
                  'data_width':cfg['data_width']}
        Path('observations.json').write_text(json.dumps(observed,indent=2)+'\n')
        checks.save('checks.json',**{k:cfg[k] for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256')},
                    runtime={'prefix':sys.prefix,'cocotb':cocotb.__version__},sequence_sha256=digest(observed))
