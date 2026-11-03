"""Pure complete-file checker for actual DOT/ordered-FP/capture events."""
import csv
from collections import Counter
from pathlib import Path
import numpy as np

def review(path,image,close,variant=False,fault=False):
 path=Path(path);base=Path(image['path']);k=image['K'];groups=k//64;n=image['N'];y=image['Y']
 aq=(base/'expected-aq.bin').read_bytes();w=(base/'W-full.bin').read_bytes()
 sa=np.fromfile(base/'expected-sa.bin',dtype='<u4');sw=np.fromfile(base/'Sw-full.bin',dtype='<u4').reshape(n,groups)
 dots=np.fromfile(base/'expected-dots.bin',dtype='<i4').reshape(groups,1,n)
 fp=np.fromfile(base/'expected-fp.bin',dtype='<u4').reshape(n,groups,3)
 rows=list(csv.reader(path.open()));counts=Counter();previous=-1;dot_in=dot_out=fp_in=fp_out=0
 leases={};owner=None;identity=None;certified=0;publish=[];completions=[];hist={};overlap=None
 state=[];sw_certificates=[];sw_certificate_identities=[];released_rows=[];release_dot_links=[]
 actual_dot_cycles={(int(row[0]),int(row[2]),int(row[3]),int(row[4])) for row in rows if row[1]=='DOT_IN'}
 def require(ok,detail):
  if not ok:raise ValueError('consumer raw: '+detail)
 for row in rows:
  cycle=int(row[0]);kind=row[1];counts[kind]+=1
  require(previous<=cycle<=close['cycle'],'event outside final observation boundary');previous=cycle
  if kind=='DOT_IN':
   r,g,b=map(int,row[2:5]);tag,epoch,keep,av,wv=[int(v,16) for v in row[5:]]
   require((r,g,b)==(dot_in//(groups*4),(dot_in//4)%groups,dot_in%4),'original per-row/per-group four DOT order')
   require(tag==g and epoch>0 and keep==65535,'DOT tag/epoch/keep')
   require(av.to_bytes(16,'little')==aq[g*64+b*16:g*64+b*16+16],'actual accepted Aq operand bits')
   require(wv.to_bytes(16,'little')==w[r*k+g*64+b*16:r*k+g*64+b*16+16],'actual accepted W operand bits')
   dot_in+=1
  elif kind=='DOT_OUT':
   r=int(row[2]);tag,epoch,value,bad,protocol=[int(v,16) for v in row[3:]];want_r,want_g=divmod(dot_out,groups)
   require((r,tag)==(want_r,want_g) and epoch>0 and bad==protocol==0,'DOT response identity/status/order')
   require(value==int(dots[want_g,0,want_r])&0xffffffff,'actual integer DOT result');dot_out+=1
  elif kind=='FP_IN':
   r,g=map(int,row[2:4]);tag,epoch,dot,a_scale,w_scale,initial=[int(v,16) for v in row[4:]]
   require((r,g)==divmod(fp_in,groups) and tag==g and epoch>0,'FP input row/group/tag/epoch')
   require(dot==(int(dots[g,0,r])&0xffffffff) and a_scale==int(sa[g]) and w_scale==int(sw[r,g]),'actual independent DOT/Sa/Sw operands')
   if g==0:require(initial==0,'original row accumulator starts positive zero')
   fp_in+=1
  elif kind=='FP_OUT':
   r=int(row[2]);tag,epoch,p,v,partial,status,flags,last=[int(v,16) for v in row[3:]];want_r,want_g=divmod(fp_out,groups)
   require((r,tag)==(want_r,want_g) and epoch>0 and status==0 and last==int(want_g==groups-1),'FP retirement row/group/identity/status/last')
   require([p,v,partial]==[int(x) for x in fp[want_r,want_g]],'two independent rounded FP32 products and original ordered accumulation')
   fp_out+=1
  elif kind=='COMPLETE':completions.append(dict(cycle=cycle,status=int(row[2]),rows=int(row[3]),tiles=int(row[4]),epoch=int(row[5],16),generation=int(row[6],16)))
  elif kind=='STATE':state.append([cycle]+[int(v) for v in row[2:]])
  elif kind=='HIST':
   key=int(row[2]);require(key not in hist,'unique state residence counter');hist[key]=int(row[3])
  elif kind=='OVERLAP':overlap=dict(W_pending_and_DOT_live=int(row[2]),W_pending_and_FP_busy=int(row[3]),W_pending_and_both=int(row[4]))
  elif kind=='W_CMD':
   r,g,count,bank=map(int,row[2:6]);tag,who,epoch,generation,address=[int(v,16) for v in row[6:]]
   require(bank not in leases and 0<count<=4 and g+count<=groups,'two W bank credits without overwrite')
   require(tag==((r<<10)|(g<<3)|count) and address==image['W']+r*k+g*64,'exact row/firstgroup/count tag and address')
   if owner is None:owner=who;identity=(epoch,generation)
   require(who==owner and who!=0 and (epoch,generation)==identity,'full stable real session/sequence plus epoch/generation')
   leases[bank]=dict(row=r,first=g,count=count,tag=tag,owner=who,epoch=epoch,generation=generation)
  elif kind=='W_RELEASE':
   bank,r,g,b=map(int,row[2:6]);tag,who,epoch,generation=[int(v,16) for v in row[6:]]
   require(bank in leases,'release has allocated W credit');lease=leases.pop(bank)
   require((r,g,b,tag,who,epoch,generation)==(lease['row'],lease['first']+lease['count']-1,3,lease['tag'],lease['owner'],lease['epoch'],lease['generation']),'release after real final required DOT operand acceptance')
   require((cycle,r,g,b) in actual_dot_cycles,'release linked to actual same-cycle DOT_IN retirement of required operand')
   require(certified&(1<<bank),'release follows certified consumption');released_rows.append(r)
   release_dot_links.append(dict(cycle=cycle,bank=bank,row=r,group=g,beat=b))
  elif kind=='BANK_STATE':
   held,certificate,bad,filled,tag0,tag1,who=[int(v,16) for v in row[2:]]
   require(bad==0 and not(certificate&~held),'normal W certification metadata')
   certified=certificate
  elif kind=='PUBLISH_BEGIN':
   r=int(row[2]);address,held,drained,who=[int(v,16) for v in row[3:]]
   require(not leases and held==0 and drained==1 and who==owner,'both W banks and accepted transport returned to original publisher')
   publish.append(dict(cycle=cycle,row=r,address=address))
  elif kind=='SW_CERT':
   first,block_rows,block_groups=map(int,row[2:5]);filled,certificate,bad,who,epoch,generation,pending=[int(v,16) for v in row[5:]]
   if certificate:
    require(not bad and not pending and filled==block_rows*block_groups,'Sw certificate only after all actual scales and fragments')
    require(block_groups==groups and first%4==0 and block_rows==min(4,n-first),'exact four-row Sw extent')
    sw_certificates.append(first)
    sw_certificate_identities.append((who,epoch,generation))
  elif kind in ('SW_START','SW_FRAG'):pass
  else:raise ValueError('unknown consumer event '+kind)
 require(len(completions)==1,'one original linear completion')
 if fault:
  require(completions[0]['status']!=0 and not publish and not leases,'failed call cannot publish or retain W credits')
  require(dot_in==dot_out==fp_in==fp_out==0,'bad first Sw rejected before W/DOT/FP consumption')
 else:
  require(completions[0]['status']==0 and completions[0]['rows']==n,'full successful original linear completion')
  require((dot_in,dot_out,fp_in,fp_out)==(n*groups*4,n*groups,n*groups,n*groups),'complete independent numeric event count')
  if variant:
   require(not leases and len(publish)==(n+127)//128,'W to original publisher handoff and tail')
   require(sw_certificates==list(range(0,n,4)),'one certified Sw block per four rows')
   require(all(v==(owner,*identity) for v in sw_certificate_identities),'Sw certificates match full real W owner and epoch/generation')
   first_publish=publish[0]['cycle']
   restart=[int(row[0]) for row in rows if row[1]=='W_CMD' and int(row[2])==128]
   require(restart and min(restart)>first_publish,'real W restart after first128 outputs')
   transport=list(csv.reader((path.parent/'api-transport.csv').open()));pending_write=None;y_transports=[]
   for event in transport:
    if event[1]=='AW':pending_write=(int(event[0]),int(event[2],16),int(event[3],16)+1)
    elif event[1]=='B':
     require(pending_write is not None,'publisher B has accepted AW')
     if y<=pending_write[1]<y+n*4:y_transports.append((*pending_write,int(event[0])))
     pending_write=None
   require(len(y_transports)==(n+127)//128 and y_transports[0][1:3]==(y,32),'original first128-row bulk publication')
   aw_cycle,address,beats,b_cycle=y_transports[0]
   require(min(restart)>b_cycle,'W restart follows original Y B retirement and native drain')
   readback=[v for v in transport if v[1]=='NAR' and aw_cycle<int(v[0])<b_cycle and int(v[2],16)==(address-0x80000000)//4 and int(v[3],16)==15]
   require(readback and b_cycle-aw_cycle>=1024,'original actual native readback and 1024 drain before W restart')
 return dict(entire_raw_checked=True,records=len(rows),event_counts=dict(counts),actual_DOT_inputs=dot_in,actual_DOT_results=dot_out,actual_FP_inputs=fp_in,actual_FP_results=fp_out,
  original_two_mul_ordered_accumulate_bitwise=not fault,full_owner=hex(owner) if owner else None,epoch_generation=identity,leases_remaining=len(leases),publisher_handoffs=publish,
  Sw_block_certificates=sw_certificates,release_DOT_links=release_dot_links,completion=completions[0],state_residence_cycles=hist,state_residence_sum=sum(hist.values()),overlap=overlap,state_transition_records=len(state),GO=False)
