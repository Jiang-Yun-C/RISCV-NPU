"""Passive exact norm AR/CPU staging witness shared by isolated v30 runners."""
from collections import Counter
import json
from pathlib import Path


def monitor(catalog,gate='1\'b1'):
    entries=json.loads(Path(catalog).read_text())['exact_tensors']
    tests='\n'.join(f"      if(backend.araddr>=32'h{e['address']:08x}&&{{1'b0,backend.araddr}}+norm_bytes<=33'h{e['address']+3584:09x})norm_slot={i};" for i,e in enumerate(entries))
    return '''
  integer norm_witness_fd,norm_slot;
  reg [32:0] norm_bytes;
  initial begin norm_witness_fd=$fopen("norm.csv","w");$fwrite(norm_witness_fd,"PASSIVE_EXACT_NORM_WITNESS\\n");end
  always @(posedge clk)if(!reset&&(@GATE@))begin
    if(cpu_bus.awvalid&&cpu_bus.awready&&cpu_bus.awaddr>=32'hba100000&&cpu_bus.awaddr<32'hba100e00)begin
      $fwrite(norm_witness_fd,"COPY_WRITE,%0d,%h\\n",cycles,cpu_bus.awaddr);$fflush(norm_witness_fd);
    end
    if(backend.arvalid&&backend.arready)begin
      norm_slot=-1;norm_bytes=(33'(backend.arlen)+1)*(33'd1<<backend.arsize);
@TESTS@
      if(norm_slot>=0)begin $fwrite(norm_witness_fd,"NORM_READ,%0d,%0d,%h,%0d,%0d\\n",cycles,norm_slot,backend.araddr,norm_bytes,owner);$fflush(norm_witness_fd);end
    end
    if(completed)$fflush(norm_witness_fd);
  end
'''.replace('@GATE@',gate).replace('@TESTS@',tests)


def verify(directory,catalog,repeats=1):
    entries=json.loads(Path(catalog).read_text())['exact_tensors'];counts=Counter();bursts=0
    for line in (Path(directory)/'norm.csv').read_text().splitlines():
        f=line.split(',')
        if f[0]=='COPY_WRITE':raise ValueError('unexpected accepted CPU coefficient staging write')
        if f[0]=='PASSIVE_EXACT_NORM_WITNESS':continue
        if len(f)!=6 or f[0]!='NORM_READ':raise ValueError('bad norm witness record')
        _,cycle,index,address,n,owner=f;index=int(index);address=int(address,16);n=int(n);e=entries[index]
        if int(owner)!=1 or not e['address']<=address<address+n<=e['address']+3584:raise ValueError('unowned or out-of-bounds immutable norm read')
        if address//4096!=(address+n-1)//4096:raise ValueError('norm AR crosses4KiB')
        counts[index]+=n;bursts+=1
    expected={i:3584*repeats for i in range(49)}
    if dict(counts)!=expected:raise ValueError('exact49 norm byte ledger incomplete '+repr(dict(counts)))
    return dict(immutable_norm_read_bytes=sum(counts.values()),per_catalog_bytes=dict(counts),accepted_bursts=bursts,CPU_coefficient_staging_AW=0,scope='PASSIVE_ACCEPTED_BUS_ONLY_NOT_SD_AUTHENTICATION')
