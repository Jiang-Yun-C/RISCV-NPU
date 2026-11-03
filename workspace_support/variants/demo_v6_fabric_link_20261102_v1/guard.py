"""TAP preflight and exact bit packing for the existing native Debugger scan path."""
NEXT={'RESET':('IDLE','RESET'),'IDLE':('IDLE','DRSELECT'),'DRSELECT':('DRCAPTURE','IRSELECT'),'DRCAPTURE':('DRSHIFT','DREXIT1'),'DRSHIFT':('DRSHIFT','DREXIT1'),'DREXIT1':('DRPAUSE','DRUPDATE'),'DRPAUSE':('DRPAUSE','DREXIT2'),'DREXIT2':('DRSHIFT','DRUPDATE'),'DRUPDATE':('IDLE','DRSELECT'),'IRSELECT':('IRCAPTURE','RESET'),'IRCAPTURE':('IRSHIFT','IREXIT1'),'IRSHIFT':('IRSHIFT','IREXIT1'),'IREXIT1':('IRPAUSE','IRUPDATE'),'IRPAUSE':('IRPAUSE','IREXIT2'),'IREXIT2':('IRSHIFT','IRUPDATE'),'IRUPDATE':('IDLE','DRSELECT')}
ALLOWED={0x283,0x284,0x159,0x3ff,0x286,0x287,0x288,0x289}
class Guard:
 def __init__(self):self.state='IDLE';self.ir=0x159;self.reg=0;self.count=0
 def inspect(self,n,tms,tdi):
  assert 0<=n<=2048 and len(tms)==len(tdi)==(n+7)//8,'Invalid vector'
  state,ir,reg,count=self.state,self.ir,self.reg,self.count;events=[]
  for i in range(n):
   bit=(tms[i//8]>>(i%8))&1;data=(tdi[i//8]>>(i%8))&1
   if state=='IRSHIFT':reg=(reg>>1)|(data<<9);count+=1
   nxt=NEXT[state][bit]
   if nxt=='RESET':ir=0x283
   elif nxt=='IRCAPTURE':reg=0;count=0
   elif nxt=='IRUPDATE':
    assert count==10,'Only exact single-device10-bit instruction allowed'
    assert reg in ALLOWED,'Forbidden/unqualified instruction '+hex(reg)
    ir=reg;events.append(hex(reg))
   elif state=='DRSHIFT':assert ir in ALLOWED,'Unqualified DR shift'
   state=nxt
  return (state,ir,reg,count),events
 def commit(self,after):self.state,self.ir,self.reg,self.count=after

def sequences(n,tms,tdi):
 out=[];i=0
 while i<n:
  level=(tms[i//8]>>(i%8))&1;j=i+1
  while j<n and j-i<64 and ((tms[j//8]>>(j%8))&1)==level:j+=1
  data=bytearray((j-i+7)//8)
  for k in range(i,j):data[(k-i)//8]|=((tdi[k//8]>>(k%8))&1)<<((k-i)%8)
  out.append((j-i,level,bytes(data),True));i=j
 return out

def combine(seqs,replies):
 n=sum(x[0]for x in seqs);out=bytearray((n+7)//8);at=0
 assert len(seqs)==len(replies)
 for (count,_,_,_),data in zip(seqs,replies):
  assert len(data)==(count+7)//8
  for k in range(count):out[(at+k)//8]|=((data[k//8]>>(k%8))&1)<<((at+k)%8)
  at+=count
 return bytes(out)
