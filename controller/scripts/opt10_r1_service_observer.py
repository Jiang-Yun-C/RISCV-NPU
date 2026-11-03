"""One parameterized observer integration for immutable service candidates."""
from collections import defaultdict,deque
import csv
import hashlib
import inspect
from pathlib import Path
import shutil

import run_ce64_soc
from opt10_r1_service_postload_support_v41 import service_wrapper as original_wrapper

ROOT=Path(__file__).resolve().parents[1]
MONITORS=ROOT/'tests/opt10_r1_service_observer/transport_monitors.sv'
TRACE_KINDS=('CW','CB','IRQ','CR','CD','SA','SW','NA','NW','NB','NL','NR','ND','MA','MB')


def transport_declarations():
    return '''
  wire service_cpu_write_drained,service_backend_drained,service_ddr_drained,service_native_drained;
  wire [63:0] service_cpu_write_activity,service_backend_activity,service_ddr_activity,service_native_activity;
  nx_service_axi_observer #(.FILE("transport-cpu.csv"),.READS(0)) service_cpu_write_monitor(
    .clk,.reset,.cycles,.epoch(soc.compute.ce.epoch),.owner,.fault(ddr_fault),.bus(cpu_bus),
    .idle(service_cpu_write_drained),.activity(service_cpu_write_activity));
  nx_service_axi_observer #(.FILE("transport-backend.csv")) service_backend_monitor(
    .clk,.reset,.cycles,.epoch(soc.compute.ce.epoch),.owner,.fault(ddr_fault),.bus(backend),
    .idle(service_backend_drained),.activity(service_backend_activity));
  nx_service_axi_observer #(.FILE("transport-ddr.csv")) service_ddr_monitor(
    .clk,.reset,.cycles,.epoch(soc.compute.ce.epoch),.owner,.fault(ddr_fault),.bus(soc.ddr_fabric.memory),
    .idle(service_ddr_drained),.activity(service_ddr_activity));
  nx_service_native_observer service_native_monitor(
    .clk,.reset,.cycles,.epoch(soc.compute.ce.epoch),.owner,
    .awaddr(d_awaddr),.araddr(d_araddr),.awid(d_awid),.arid(d_arid),.awlen(d_awlen),.arlen(d_arlen),
    .awvalid(d_awvalid),.awready(d_awready),.arvalid(d_arvalid),.arready(d_arready),
    .wready(d_wready),.wlast(d_wlast),.rvalid(d_rvalid),.rlast(d_rlast),.rid(d_rid),
    .commit_fire(native_model.commit_due==1),
    .model_pending(native_model.writing||native_model.reading||native_model.commit_due!=0),
    .idle(service_native_drained),.activity(service_native_activity));
  wire service_transport_drained=service_cpu_write_drained&&service_backend_drained&&service_ddr_drained&&service_native_drained&&
    soc.compute.ce.dma_idle&&soc.compute.ce.transport_drained&&soc.native_safely_drained&&
    !soc.native_pending&&!soc.upstream_pending&&!ddr_fault&&!soc.native_quarantined&&owner==0;
  wire [63:0] service_transport_activity=service_cpu_write_activity+service_backend_activity+service_ddr_activity+service_native_activity;
'''


def service_wrapper(wrapper,metadata):
    wrapper=original_wrapper(wrapper,metadata)
    head,tail=wrapper.rsplit('endmodule',1)
    return head+transport_declarations()+'\nendmodule\n'+MONITORS.read_text()+tail


def build_service(run,tools,vpi,repo,metadata,tb):
    """Private hook around the locked builder; only the measurement shell changes."""
    source=inspect.getsource(run_ce64_soc.build)
    marker="    tb=compiled/'tb_cpu.sv';tb.write_text(wrapper);shutil.copy2(tb,src/'tb_cpu.sv')"
    if source.count(marker)!=1:raise ValueError('locked builder hook changed')
    source=source.replace(marker,"    wrapper=service_wrapper(wrapper,service_metadata)\n"+marker)
    generated=run.build/'isolated_service_builder.py';generated.write_text(source)
    namespace=dict(run_ce64_soc.__dict__);namespace.update(service_wrapper=service_wrapper,service_metadata=metadata)
    exec(compile(source,str(generated),'exec'),namespace)
    overrides={str(f.relative_to(repo)):f for f in (repo/'rtl').rglob('*') if f.is_file()}
    overrides['tests/ce64_soc/tb_body.svh']=tb
    extras=[str(f.relative_to(repo)) for f in sorted((repo/'rtl/sfu').glob('*.sv'))]
    extras+=['rtl/soc/t17_uart_router.sv','rtl/soc/t18_spi.sv','rtl/ce64/nx_t25_local.sv']
    return namespace['build'](run,tools,vpi,board_memory=True,wave_window=4000,
        source_overrides=overrides,additional_sources=extras,defines=['OPT11_LANES=2'])


def verify_transport(path,close,producer,*,native=False,strict_epoch=False):
    """Replay a complete closed accepted-work ledger independently of live counts."""
    if producer.poll() is None or producer.returncode!=0:raise ValueError('transport producer must have exited successfully')
    if close.get('stage')!='AFTER_ALL_TIME_ADVANCING_INSPECTION' or not close.get('stable') or not close.get('transport_idle'):
        raise ValueError('transport close missing or not drained')
    path=Path(path);before=path.stat();digest=hashlib.sha256()
    writes=deque();early_data=deque();write_ids=defaultdict(deque);reads=defaultdict(deque)
    events=defaultdict(int);last_cycle=-1;last_epoch=None;epochs=[];max_pending=0;write_bytes=read_bytes=0
    def consume_data(data):
        q=writes[0];q['seen']+=1;q['last_cycle']=data['cycle']
        if data['last']!=int(q['seen']==q['beats']):raise ValueError('W last/length mismatch')
        if strict_epoch and data['epoch']!=q['epoch']:raise ValueError('W crossed CE epoch')
        if data['last']:writes.popleft()
    with path.open('rb') as stream:
        for line in stream:
            digest.update(line)
            if not line.endswith(b'\n'):raise ValueError('truncated transport record')
            row=next(csv.reader([line.decode('ascii')]))
            if len(row)!=10:raise ValueError('transport record grammar')
            cycle=int(row[0]);kind=row[1];identity=int(row[2]);address=int(row[3],16)
            length,size,last,resp,epoch,owner=map(int,row[4:])
            if cycle<last_cycle or cycle>close['cycle']:raise ValueError('transport event outside final observation boundary')
            last_cycle=cycle;events[kind]+=1
            if kind=='EPOCH':
                if last_epoch is not None and epoch<=last_epoch:raise ValueError('nonmonotonic CE epoch')
                if strict_epoch and (writes or early_data or any(write_ids.values()) or any(reads.values())):raise ValueError('CE epoch changed with backend accepted work pending')
                epochs.append(epoch);last_epoch=epoch
            elif kind=='FAULT':
                if resp:raise ValueError('native fault in production transport ledger')
            elif kind=='RESET':
                if writes or early_data or any(write_ids.values()) or any(reads.values()):raise ValueError('platform reset discarded accepted transport work')
            elif kind in ('AW','AR'):
                if length<0 or length>255 or size<0 or size>5 or owner not in (0,1):raise ValueError('invalid accepted address metadata')
                q=dict(identity=identity,address=address,beats=length+1,seen=0,epoch=epoch,last_cycle=None)
                if kind=='AW':
                    writes.append(q);write_ids[identity].append(q);write_bytes+=(length+1)<<size
                    while writes and early_data:consume_data(early_data.popleft())
                else:
                    reads[identity].append(q);read_bytes+=(length+1)<<size
            elif kind=='W':
                data=dict(cycle=cycle,last=last,epoch=epoch)
                if writes:consume_data(data)
                elif native:raise ValueError('physical W without accepted native AW')
                else:early_data.append(data)
            elif kind in ('B','COMMIT'):
                if (kind=='COMMIT')!=native:raise ValueError('wrong physical retirement kind')
                queue=write_ids[identity]
                if not queue:raise ValueError('retirement without accepted AW')
                q=queue.popleft()
                if resp or q['seen']!=q['beats']:raise ValueError('error or incomplete write retirement')
                if native and cycle-q['last_cycle']<6:raise ValueError('physical commit preceded original six-cycle model delay')
                if strict_epoch and epoch!=q['epoch']:raise ValueError('B crossed CE epoch')
            elif kind=='R':
                queue=reads[identity]
                if not queue:raise ValueError('R without accepted AR')
                q=queue[0];q['seen']+=1
                if resp or last!=int(q['seen']==q['beats']):raise ValueError('R error/last/length mismatch')
                if strict_epoch and epoch!=q['epoch']:raise ValueError('R crossed CE epoch')
                if last:queue.popleft()
            else:raise ValueError('unexpected transport event '+kind)
            max_pending=max(max_pending,sum(len(q) for q in write_ids.values())+sum(len(q) for q in reads.values()))
    after=path.stat()
    if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise ValueError('transport raw changed during replay')
    if writes or early_data or any(write_ids.values()) or any(reads.values()):raise ValueError('unretired accepted transport work')
    if not sum(events.values()):raise ValueError('empty transport ledger')
    return dict(path=str(path),sha256=digest.hexdigest(),bytes=after.st_size,events=dict(events),
        records=sum(events.values()),accepted_write_bytes=write_bytes,accepted_read_bytes=read_bytes,
        epochs=epochs,max_pending=max_pending,entire_file_checked=True,close_cycle=close['cycle'],
        all_accepted_work_retired=True,scope='DIGITAL_ACCEPTED_TRANSPORT_RETIREMENT_ONLY_NOT_PHY_OR_BOARD')
