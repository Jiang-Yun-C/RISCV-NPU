"""Decode two bounded bus functions without general signed division/modulo."""
import hashlib,re

MASK='''function automatic logic[3:0] cpu_strobe_mask(logic[31:0] a,logic[2:0] size);
    logic[3:0] mask;
    mask=0;
    case(a[1:0])
'''
for address in range(4):
    MASK+=f"      2'd{address}: case(size)\n"
    for size in range(8):
        end=((address>>size)+1)<<size
        value=sum(1<<i for i in range(address,min(end,4)))
        MASK+=f"        3'd{size}: mask=4'h{value:x};\n"
    MASK+='        default: mask=0;\n      endcase\n'
MASK+='      default: mask=0;\n    endcase\n    return mask;\n  endfunction'

CHOOSE='''function automatic logic[1:0] choose(input logic[2:0] requests,input logic[1:0] start);
   choose=3;
   case(start)
'''
for start in range(4):
    CHOOSE+=f"     2'd{start}: begin\n"
    for offset in (2,1,0):
        index=(start+offset)%3
        CHOOSE+=f"       if(requests[{index}]) choose=2'd{index};\n"
    CHOOSE+='     end\n'
CHOOSE+='     default: choose=3;\n   endcase\n endfunction'


def functions(bridge,arbiter):
    old_mask=re.search(r'function automatic logic\[3:0\] cpu_strobe_mask\(.*?endfunction',bridge,re.S)
    old_choose=re.search(r'function automatic logic\[1:0\] choose\(.*?endfunction',arbiter,re.S)
    if not old_mask or not old_choose:raise ValueError('bounded bus function missing')
    if "for(int i=0;i<4;i++)if(i>=a[1:0]&&i<((int'(a[1:0])/(1<<size))+1)*(1<<size))mask[i]=1;" not in old_mask[0]:raise ValueError('mask algorithm changed')
    if "for(int k=2;k>=0;k--)begin idx=2'((int'(start)+k)%3);if(requests[idx])choose=idx;end" not in old_choose[0]:raise ValueError('arbitration algorithm changed')
    return old_mask[0],old_choose[0]


def lower(bridge,arbiter):
    old_mask,old_choose=functions(bridge,arbiter)
    digest=lambda s:hashlib.sha256(s.encode()).hexdigest()
    receipt={name:{'original_sha256':digest(before),'canonical_sha256':digest(after)}
             for name,before,after in [('cpu_strobe_mask',old_mask,MASK),('choose',old_choose,CHOOSE)]}
    return bridge.replace(old_mask,MASK,1),arbiter.replace(old_choose,CHOOSE,1),receipt
