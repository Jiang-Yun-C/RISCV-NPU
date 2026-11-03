#!/usr/bin/env python3
"""Execute a PDS CRAM-only SVF or read SAMPLE through the verified adapter."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

NEXT = {
    'RESET': ('IDLE','RESET'), 'IDLE': ('IDLE','DRSELECT'),
    'DRSELECT': ('DRCAPTURE','IRSELECT'), 'DRCAPTURE': ('DRSHIFT','DREXIT1'),
    'DRSHIFT': ('DRSHIFT','DREXIT1'), 'DREXIT1': ('DRPAUSE','DRUPDATE'),
    'DRPAUSE': ('DRPAUSE','DREXIT2'), 'DREXIT2': ('DRSHIFT','DRUPDATE'),
    'DRUPDATE': ('IDLE','DRSELECT'), 'IRSELECT': ('IRCAPTURE','RESET'),
    'IRCAPTURE': ('IRSHIFT','IREXIT1'), 'IRSHIFT': ('IRSHIFT','IREXIT1'),
    'IREXIT1': ('IRPAUSE','IRUPDATE'), 'IRPAUSE': ('IRPAUSE','IREXIT2'),
    'IREXIT2': ('IRSHIFT','IRUPDATE'), 'IRUPDATE': ('IDLE','DRSELECT'),
}


class Jtag:
    def __init__(self, dependency_dir, hz):
        sys.path.insert(0, dependency_dir)
        import hid
        matches = [d for d in hid.enumerate(0x04d8, 0x00df)
                   if d.get('serial_number') == 'ATK 20210914'
                   and d.get('product_string') == 'ATK-HS-V2-CMSIS-DAP']
        if len(matches) != 1:
            raise RuntimeError('Exact adapter identity is missing or ambiguous')
        self.dev = hid.device(); self.dev.open_path(matches[0]['path'])
        self.dev.set_nonblocking(1)
        while self.dev.read(1024): pass
        self.dev.set_nonblocking(0)
        self.packets = 0; self.shifted = 0; self.state = 'RESET'
        cap = self.exchange(bytes([0,0xf0]))
        size = self.exchange(bytes([0,0xff]))
        if not cap[2] & 2 or int.from_bytes(size[2:4], 'little') != 1024:
            raise RuntimeError('Adapter capabilities or packet size changed')
        if self.exchange(bytes([2,2]))[1] != 2: raise RuntimeError('JTAG connect failed')
        self.set_frequency(hz)
        self.sequences([(8,1,b'\0',False)]); self.state='RESET'
        ident = self.scan('DR',64,b'\0'*8)
        self.idcode=int.from_bytes(ident[:4],'little')
        if self.idcode & 0x0fffffff != 0x00603899 or ident[4:] not in (b'\xff'*4, b'\0'*4):
            raise RuntimeError('Expected single PG2L200H JTAG chain differs: '+ident.hex())

    def exchange(self, payload):
        if len(payload)>1024: raise RuntimeError('CMSIS-DAP packet overflow')
        request=b'\0'+payload+b'\0'*(1024-len(payload))
        if self.dev.write(request)!=len(request): raise RuntimeError('Short HID write')
        reply=bytes(self.dev.read(1024,10000));self.packets+=1
        if len(reply)<2 or reply[0]!=payload[0]: raise RuntimeError('Invalid CMSIS-DAP reply')
        return reply

    def set_frequency(self, hz):
        if not 100000<=hz<=1000000: raise RuntimeError('Only qualified 100kHz..1MHz range allowed')
        if self.exchange(b'\x11'+hz.to_bytes(4,'little'))[1]: raise RuntimeError('TCK configuration failed')
        self.hz=hz

    def sequences(self, seqs):
        payload=bytearray([0x14,len(seqs)]);captured=[]
        for count,tms,data,cap in seqs:
            if not 1<=count<=64:raise RuntimeError('Invalid sequence size')
            payload.append((count%64)|(tms<<6)|(int(cap)<<7))
            payload.extend(data[:(count+7)//8]);self.shifted+=count
        reply=self.exchange(payload)
        if reply[1]:raise RuntimeError('JTAG sequence rejected')
        off=2
        for count,tms,data,cap in seqs:
            if cap:
                n=(count+7)//8;captured.append(reply[off:off+n]);off+=n
        if len(reply)<off:raise RuntimeError('Short captured TDO')
        return captured

    def goto(self, target):
        if target=='RESET':
            self.sequences([(8,1,b'\0',False)]);self.state='RESET';return
        queue=[(self.state,[])];seen={self.state}
        while queue:
            state,path=queue.pop(0)
            if state==target:
                if path:self.sequences([(1,bit,b'\0',False) for bit in path])
                self.state=target;return
            for bit,nxt in enumerate(NEXT[state]):
                if nxt not in seen:seen.add(nxt);queue.append((nxt,path+[bit]))
        raise RuntimeError('Unsupported TAP state '+target)

    def scan(self, kind, nbits, data, capture=True):
        self.goto(kind+'SHIFT');result=bytearray(); offset=0
        started=time.monotonic();reported=0
        # Keep the final bit separate so only that bit asserts TMS.
        while offset+64<nbits:
            count=min(112,(nbits-offset-1)//64)
            seq=[(64,0,data[(offset+i*64)//8:(offset+i*64)//8+8],capture) for i in range(count)]
            for part in self.sequences(seq):result.extend(part)
            offset+=count*64
            if nbits>1000000 and offset*10//nbits>reported:
                reported=offset*10//nbits
                print(json.dumps({'scan_progress_percent':reported*10,
                                  'shifted_bits':offset,'total_bits':nbits,
                                  'elapsed_s':round(time.monotonic()-started,1)}),flush=True)
        remain=nbits-offset
        if remain>1:
            part=self.sequences([(remain-1,0,data[offset//8:],capture)])
            tail=int.from_bytes(part[0],'little') if capture else 0
        else:tail=0
        final=(data[(nbits-1)//8]>>((nbits-1)%8))&1
        part=self.sequences([(1,1,bytes([final]),capture)])
        if capture:
            tail|=(part[0][0]&1)<<(remain-1)
            result.extend(tail.to_bytes((remain+7)//8,'little'))
        self.state=kind+'EXIT1';self.goto('IDLE')
        return bytes(result)

    def idle(self, count, state='IDLE'):
        self.goto(state);tms=int(state=='RESET')
        while count:
            n=min(count,64*112);seq=[]
            for off in range(0,n,64):
                bits=min(64,n-off);seq.append((bits,tms,b'\0'*8,False))
            self.sequences(seq);count-=n

    def instruction(self, opcode): self.scan('IR',10,opcode.to_bytes(2,'little'),False)
    def register(self, opcode):
        self.instruction(opcode);return int.from_bytes(self.scan('DR',32,b'\0'*4),'little')
    def close(self):
        try:self.instruction(0x283);self.exchange(b'\x03')
        finally:self.dev.close()


def load_svf(path):
    text=re.sub(r'//[^\n]*','',path.read_text())
    commands=[c.strip() for c in text.split(';') if c.strip()]
    for cmd in commands:
        kind=cmd.split()[0]
        if kind not in ['TRST','ENDIR','ENDDR','STATE','FREQUENCY','RUNTEST','SIR','SDR']:
            raise RuntimeError('Unsupported SVF command '+kind)
        if kind=='SIR':
            opcode=int(re.search(r'TDI\s*\(([0-9A-Fa-f\s]+)\)',cmd)[1],16)
            if int(cmd.split()[1])!=10 or opcode not in [0x283,0x28a,0x28b,0x28d,0x3ff,0x159]:
                raise RuntimeError('SVF is not approved PG2L200H CRAM-only programming')
    return commands


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--dependency-dir',required=True)
    ap.add_argument('--out',required=True);ap.add_argument('--svf',type=Path)
    ap.add_argument('--bsdl',type=Path);ap.add_argument('--samples',type=int,default=12)
    ap.add_argument('--hz',type=int,default=1000000)
    ap.add_argument('--snapshot-after-payload',action='store_true',
                    help='Read configuration status after the native payload and before its TAP reset')
    ap.add_argument('--capture-payload',action='store_true',
                    help='Use captured CMSIS-DAP sequences for large DR payloads; retain all native TDO checks')
    args=ap.parse_args()
    result={'started_at':datetime.now(timezone.utc).isoformat(),'status':'FAIL',
            'adapter_serial':'ATK 20210914','programming_performed':False,'flash_modified':False}
    result['payload_tdo_capture_enabled']=args.capture_payload
    j=None;start=time.monotonic()
    try:
        commands=load_svf(args.svf) if args.svf else []
        if args.snapshot_after_payload:
            for i,cmd in enumerate(commands):
                if cmd.startswith('SDR ') and int(cmd.split()[1])>1000000:
                    if i+1>=len(commands) or not commands[i+1].startswith('RUNTEST RESET '):
                        raise RuntimeError('Status snapshot requires the native TAP reset immediately after payload')
            result['configuration_snapshots']=[]
            result['additional_read_only_operations']='STATUS read after payload, immediately before native TAP reset'
        j=Jtag(args.dependency_dir,args.hz);result['idcode']=hex(j.idcode)
        if commands:
            result['svf_sha256']=hashlib.sha256(args.svf.read_bytes()).hexdigest()
            result['programming_performed']=True;checks=[]
            result['tdo_checks']=checks
            for cmd in commands:
                words=cmd.split();kind=words[0]
                if kind in ['ENDIR','ENDDR'] and words[1]!='IDLE':raise RuntimeError('Unsupported end state')
                elif kind=='TRST' and words[1]!='OFF':raise RuntimeError('Unsupported TRST')
                elif kind=='FREQUENCY':j.set_frequency(int(float(words[1])))
                elif kind=='STATE':
                    for state in words[1:]:j.goto(state)
                elif kind=='RUNTEST':
                    if words[3]!='TCK':raise RuntimeError('Only clocked RUNTEST supported')
                    j.idle(int(words[2]),words[1])
                elif kind in ['SIR','SDR']:
                    bits=int(words[1]); fields=dict(re.findall(r'(TDI|TDO|MASK)\s*\(([0-9A-Fa-f\s]+)\)',cmd))
                    tdi=re.sub(r'\s','',fields['TDI']);tdi='0'+tdi if len(tdi)%2 else tdi
                    data=bytes.fromhex(tdi)[::-1];data=data.ljust((bits+7)//8,b'\0')
                    capture = 'TDO' in fields or (args.capture_payload and kind=='SDR' and bits>1000000)
                    reply=j.scan('IR' if kind=='SIR' else 'DR',bits,data,capture)
                    if args.snapshot_after_payload and kind=='SDR' and bits>1000000:
                        status=j.register(0x159)
                        snapshot={'event':'AFTER_PAYLOAD_BEFORE_TAP_RESET',
                                  'elapsed_s':round(time.monotonic()-start,3),
                                  'status_register':hex(status),
                                  'done_bit':bool(status&0x1000),
                                  'documented_id_error':bool(status&1),
                                  'documented_crc_error':bool(status&2),
                                  'documented_init_complete':bool(status&0x400)}
                        result['configuration_snapshots'].append(snapshot)
                        print(json.dumps(snapshot),flush=True)
                    if 'TDO' in fields:
                        actual=int.from_bytes(reply,'little');expected=int(fields['TDO'],16)
                        mask=int(fields.get('MASK',hex((1<<bits)-1)),16)
                        checks.append({'bits':bits,'expected':hex(expected),'actual':hex(actual),'mask':hex(mask)})
                        if (actual^expected)&mask:raise RuntimeError('SVF TDO comparison failed: '+str(checks[-1]))
            result['tdo_checks']=checks
        result['status_register']=hex(j.register(0x159))
        result['done_bit']=bool(int(result['status_register'],16)&0x1000)
        if commands and not result['done_bit']:
            raise RuntimeError('Configuration DONE is not asserted after CRAM programming')
        if args.bsdl:
            s=args.bsdl.read_text();length=int(re.search(r'BOUNDARY_LENGTH.*?is\s+(\d+)',s)[1])
            pads=dict(re.findall(r'"(\w+)\s*:\s*([A-Z]+\d+),',s))
            cells={pads.get(logical):int(index) for index,logical in re.findall(r'"(\d+)\s*\(BC_7,\s*(\w+),\s*bidir',s)}
            pins=['A20','C18','C19','E18','A17','A18','C17','B17','C22']
            result['boundary_cells']={p:cells[p] for p in pins};samples=[]
            for _ in range(args.samples):
                j.instruction(0x280);data=int.from_bytes(j.scan('DR',length,b'\0'*((length+7)//8)),'little')
                values={p:(data>>cells[p])&1 for p in pins}
                samples.append({'elapsed_s':round(time.monotonic()-start,3),'pins':values,
                                'led_byte':sum(values[p]<<i for i,p in enumerate(pins[:8]))})
                time.sleep(.2)
            result['samples']=samples
        result['status']='PASS'
    except Exception as e:result['error']=type(e).__name__+': '+str(e)
    finally:
        if j:
            result.update(packets=j.packets,shifted_tck=j.shifted,tck_hz=j.hz)
            try:j.close()
            except Exception as e:result['close_error']=str(e)
        result['elapsed_s']=round(time.monotonic()-start,3)
        Path(args.out).write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k not in ['samples','boundary_cells']}))
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
