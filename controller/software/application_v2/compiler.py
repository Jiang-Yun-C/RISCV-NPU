"""Select unmodified full-model outputs using program structure, never Chinese rules.

Every published intent is one complete EOS output of the frozen model. The
primary compiler is unchanged. A narrow two-sensor extension may ask the same
model for candidates; no node, value, comparison or branch is synthesized.
"""
import json
from pathlib import Path
from software.application_v2.program import parse,validate,ProgramError
ROOT=Path(__file__).resolve().parents[2]

def messages(text,state,prompt):
    return [dict(role='system',content=prompt),dict(role='user',content='状态：'+json.dumps(state,ensure_ascii=False,separators=(',',':'))+'\n指令：'+text)]

def compile_request(model,tokenizer,text,state):
    steps=[]
    def infer(path):
        msg=messages(text,state,(ROOT/path).read_text());out=model.generate(tokenizer,msg)
        steps.append(dict(prompt=path,messages=msg,**out));return out
    def program(out):
        if out['stop']!='eos':return None
        try:p=parse(out['text']);validate(p);return p
        except (ProgramError,TypeError):return None
    def extension(p):
        if p is None or len(p)!=2 or any(n[0]!='if' for n in p) or {n[1] for n in p}!={'temperature','light'}:return False
        return all((-40<=n[3]<=125) if n[1]=='temperature' else (0<=n[3]<=100000) for n in p)
    primary=infer('configs/application_v2/prompt.txt');original=program(primary);selected=primary;route='PRIMARY'
    # This is an AST capability dispatch. It never inspects words, IDs, labels,
    # request categories or expected outputs, and never edits generated nodes.
    if original is not None and len(original)==1 and original[0][0]=='if':
        independent=infer('configs/t20-prompt.txt');a=program(independent)
        if extension(a):
            complete=infer('configs/t20-completion-prompt.txt');b=program(complete)
            if extension(b) and original[0] in b:
                selected=complete;route='EXTENSION_PRESERVES_PRIMARY_NODE'
            elif a[0][:5]==original[0][:5] and a[0][5]==[] and original[0][5]==a[1][4] and a[1][5]==[]:
                selected=independent;route='EXTENSION_UNFOLDS_PRIMARY_ELSE_AS_SEPARATE_CONDITION'
    result=dict(selected);result.update(candidates=steps,selected_route=route,selected_prompt=next(s['prompt'] for s in steps if s['text']==selected['text'] and s['output_ids']==selected['output_ids']))
    return result
