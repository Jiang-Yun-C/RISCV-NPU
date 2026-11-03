"""Represent disjoint FP pipeline array drivers as individual flop outputs.

This is simulation-only. Each existing generate iteration receives the SAME
element type and SAME FF macro/reset/enable/RHS, then continuously drives its
original packed-array element. No expression, stage, or handshake is changed.
The original packed array has only continuous drivers after conversion.
"""
import re

def lower(source):
    starts=list(re.finditer(r'for \(genvar i = 0; i < NUM_\w+_REGS; i\+\+\) begin : \w+',source))
    if len(starts)!=16:raise ValueError('FP pipeline generate count changed')
    changes=[];flops=0
    for match in starts:
        depth=1;end=None
        for token in re.finditer(r'\bbegin\b|\bend\b',source[match.end():]):
            depth += 1 if token.group()=='begin' else -1
            if depth==0:end=match.end()+token.end();break
        if end is None:raise ValueError('Unclosed pipeline block')
        block=source[match.end():end]
        names=set(re.findall(r'`FF\w*\(\s*(\w+)\[i\+1\]',block))
        names.update(re.findall(r'(\w+)\[i\+1\]\s*<=',block))
        if not names:raise ValueError('Empty pipeline block')
        declarations=[]
        for name in sorted(names):
            pattern=(r'^\s*([\w:]+(?:\s+signed)?)\s*\[0:NUM_\w+_REGS\]'
                r'((?:\s*\[[^\]]+\])*)\s+(?:\w+\s*,\s*)*'+re.escape(name)+r'(?:\s*,\s*\w+)*\s*;')
            declaration=re.search(pattern,source,re.M)
            if not declaration:raise ValueError('Cannot preserve element type '+name)
            element=declaration.group(1)+declaration.group(2)
            local='compat_'+name
            declarations += [f'    {element} {local};',f'    assign {name}[i+1] = {local};']
            block=re.sub(r'(`FF\w*\(\s*)'+re.escape(name)+r'\[i\+1\]',r'\1'+local,block)
            block=re.sub(re.escape(name)+r'\[i\+1\](\s*<=)',local+r'\1',block)
            flops+=1
        changes.append((match.end(),end,'\n'+'\n'.join(declarations)+block))
    for start,end,replacement in reversed(changes):source=source[:start]+replacement+source[end:]
    if re.search(r'`FF\w*\(\s*\w+\[i\+1\]|\w+\[i\+1\]\s*<=',source):
        raise ValueError('Unconverted mixed pipeline array driver')
    return source,{'generate_blocks':len(changes),'flop_elements_per_generated_stage':flops}
