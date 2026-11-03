"""Flatten sv2v's constant interface declaration scopes for the rc3 parser.

Only if(1) blocks containing wire declarations qualify. Renaming preserves
all connections; no behavioral or conditional generate block is removed.
"""
import re
BLOCK=re.compile(r'generate\s+if\s*\(1\)\s*begin\s*:\s*(\w+)\s*((?:(?:wire|localparam)\s+[^;]+;\s*)+)end\s+endgenerate')
def flatten(text):
    edits=[]
    def module(match):
        body=match[0];blocks=list(BLOCK.finditer(body))
        for b in blocks:
            scope,decl=b.groups();names=re.findall(r'\b(?:wire|localparam)\s+(?:\[[^;]+?\]\s*)?(\w+)\s*(?:=[^;]+)?;',decl)
            if not names or len(names)!=decl.count(';'):raise ValueError('unsupported interface declaration scope')
            declarations=decl
            for name in names:
                declarations=re.sub(r'\b'+re.escape(name)+r'\b',scope+'__'+name,declarations)
            body=body.replace(b[0],declarations)
            body=re.sub(r'(?<![\w$])'+re.escape(scope)+r'\.(\w+)',lambda m:scope+'__'+m[1],body)
            edits.append({'scope':scope,'signals':names})
        return body
    result=re.sub(r'\bmodule\b[\s\S]*?\bendmodule\b',module,text)
    return result,edits
