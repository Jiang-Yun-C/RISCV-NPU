"""Parse both frozen rc3 and global 2024 PDS synthesis summaries."""
import math,re
DENOMINATORS=dict(luts=159800,registers=319600,drm36k=415,apm=740)
def parse_resources(text):
    patterns=dict(luts=r'Total LUTs:\s*([\d.]+)',registers=r'Total Registers:\s*([\d.]+)',
        latches=r'Total Latches:\s*([\d.]+)',drm36k=r'Total DRMs?\s*=\s*([\d.]+)',apm=r'Total APMs\s*=\s*([\d.]+)')
    result={}
    for name,pattern in patterns.items():
        matches=re.findall(pattern,text)
        if len(matches)!=1:raise ValueError('missing/ambiguous resource field: '+name)
        result[name]=float(matches[0])
        if not math.isfinite(result[name]) or result[name]<0:raise ValueError('invalid resource field: '+name)
    return result
def fits(resources):return all(resources[k]<=limit for k,limit in DENOMINATORS.items())
