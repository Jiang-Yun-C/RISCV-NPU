"""Transport framing. A soft cancel needs its complete matched recovery tail."""
import re
class ResponseFramer:
 def __init__(self,cancel_expected=False):
  self.buffer=bytearray();self.text_bytes=None;self.lines=[];self.ready=False
  self.error=False;self.halted=False;self.snapshot=False;self.snapshots=0
  self.cancel_expected=cancel_expected;self.request_session=None;self.recovered=False
 def feed(self,block):
  self.buffer.extend(block)
  while True:
   if self.text_bytes is not None:
    prefix=b'T25 TEXT '
    if len(self.buffer)<len(prefix):return
    if not self.buffer.startswith(prefix):raise ValueError('Missing final TEXT prefix')
    size=len(prefix)+self.text_bytes
    if len(self.buffer)<size+1:return
    bytes(self.buffer[len(prefix):size]).decode('utf8',errors='strict')
    if self.buffer[size]!=10:raise ValueError('Missing final TEXT terminator')
    del self.buffer[:size+1];self.text_bytes=None;continue
   if b'\n'not in self.buffer:
    if len(self.buffer)>65536:raise ValueError('Oversized response line')
    return
   raw,_,tail=self.buffer.partition(b'\n');self.buffer=bytearray(tail)
   line=raw.rstrip(b'\r').decode('utf8',errors='strict');self.lines.append(line)
   if line.startswith('T25 REQUEST 1 '):
    m=re.search(r'\bsession=([0-9a-f]{16}) ',line)
    if not m or self.request_session is not None:raise ValueError('Malformed/duplicate request')
    self.request_session=m[1]
   if line.startswith('D27 SNAPSHOT 1 CID='):
    if self.snapshot:raise ValueError('Nested snapshot')
    self.snapshot=True
   elif line=='D27 SNAPSHOT END':
    if not self.snapshot:raise ValueError('Unopened snapshot')
    self.snapshot=False;self.snapshots+=1
   elif line.startswith('T25 ERROR '):self.error=True
   elif line=='D27 HALTED':
    if not self.error or self.snapshots!=2 or self.snapshot or self.buffer:raise ValueError('Incomplete diagnostic halt')
    self.halted=True;return
   elif line.startswith(('T25 TRAP','T25 SD ERROR','T25 NOT_READY')):raise ValueError('Board failure: '+line)
   if line.startswith('T25 TEXTLEN '):
    m=re.fullmatch(r'T25 TEXTLEN 1 bytes=([0-9a-f]{16})\s*',line)
    if not m or int(m[1],16)>16384:raise ValueError('Malformed final TEXT length')
    self.text_bytes=int(m[1],16)
   if line=='T25 READY':
    if self.buffer:raise ValueError('Unexpected bytes after READY')
    if self.error:
     s=self.request_session
     end=f'T25 REQUEST_END 1 session={s} next_session={int(s,16)+1:016x} status=cancelled 'if s else ''
     ends=[x for x in self.lines if x.startswith('T25 REQUEST_END ')]
     controls=[x for x in self.lines if x.startswith('T25 CONTROL ')]
     aborts=[x for x in self.lines if x.startswith('T25 STREAM 1 ABORT ')]
     errors=[x for x in self.lines if x.startswith('T25 ERROR ')]
     self.recovered=bool(self.cancel_expected and s and len(ends)==1 and ends[0].rstrip()==end.rstrip() and len(controls)==1 and controls[0].rstrip()==f'T25 CONTROL 1 session={s} status=accepted' and len(aborts)==1 and f'session={s} 'in aborts[0] and 'error=00000000fffffff5 data='in aborts[0] and errors==['T25 ERROR fffffff5'] and not self.snapshots and not any(x.startswith(('D27 ','T25 METRICS ','T27 ACTION'))for x in self.lines))
     if not self.recovered:raise ValueError('ERROR/READY without complete matching cancel recovery')
     positions=[self.lines.index(x) for x in [controls[0],aborts[0],errors[0],ends[0],line]]
     if positions!=sorted(positions):raise ValueError('Reordered cancel recovery')
    self.ready=True;return
 def terminal(self):
  if self.buffer or self.snapshot:raise ValueError('Truncated framing')
  if self.error and not self.recovered:
   if not self.halted:raise ValueError('Missing HALTED')
   return 'DIAGNOSTIC_FAILURE_CAPTURED_STOP_ALL_TRANSMIT'
  if not self.ready:raise ValueError('Missing READY')
  return 'MATCHED_CANCEL_RECOVERY'if self.recovered else'CONTROL_RESPONSE_ONLY_NOT_NUMERIC_PASS'
