"""T22 component tests; the independent environment does not model the PHY."""
import json
import os
from pathlib import Path
import random
import sys

import cocotb
from cocotb.triggers import Timer
from cocotb.utils import get_sim_time
from common.checks import Checks, digest


def ram_pattern(address, phase):
    value = (address << 24) | ((255-address) << 16) | ((address ^ 0x5a) << 8) | (address ^ 0xa5)
    return value ^ (0xffffffff if phase else 0)


def ddr_pattern(word, seed):
    return sum(((word+i) ^ seed) << (32*i) for i in range(8))


class Platform:
    def __init__(self, dut, cfg, checks):
        self.d = dut
        self.cfg = cfg
        self.c = checks
        self.rng = random.Random(cfg['seed'])
        self.cycles = 0
        self.events = []
        self.ram = {}
        self.ram_writes = 0
        self.monitor_ram = False
        self.transactions = []

    def v(self, name):
        return int(getattr(self.d, name).value)

    async def tick(self):
        await Timer(1, unit='ns')
        self.cycles += 1
        self.c.require(self.cycles <= self.cfg['max_cycles'], 'completion', 'cycle timeout')
        edge = int(get_sim_time(unit='ps'))
        state = self.v('phase_status') & 7
        if self.v('rst_n'):
            for ch, active, fields in (
                ('aw', self.v('axi_awvalid') and self.v('axi_awready'), ('axi_awaddr', 'axi_awlen')),
                ('w', state == 2 and self.v('axi_wready'), ('axi_wdata', 'axi_wstrb', 'axi_wlast')),
                ('ar', self.v('axi_arvalid') and self.v('axi_arready'), ('axi_araddr', 'axi_arlen')),
                ('r', state == 5 and self.v('axi_rvalid'), ('axi_rdata', 'axi_rid', 'axi_rlast')),
            ):
                if active:
                    self.events.append([edge, ch, *[self.v(n) for n in fields]])
        old_ram = None
        if self.monitor_ram:
            m = self.d.minimal
            address = int(m.addr.value)
            old_ram = self.ram.get(address)
            if int(m.ready.value) and int(m.state.value) == 0:
                self.c.equal(address, self.ram_writes % 256, 'ram_data', 'RAM write address order')
                phase = self.ram_writes // 256
                self.c.equal(int(m.phase.value), phase, 'ram_data', 'RAM complement sweep')
                self.ram[address] = ram_pattern(address, phase)
                self.ram_writes += 1
        self.d.clk.value = 1
        await Timer(4, unit='ns')
        if self.monitor_ram and old_ram is not None:
            self.c.equal(int(self.d.minimal.rd.value), old_ram, 'ram_latency', 'one-cycle read-first RAM')
        self.d.clk.value = 0
        await Timer(5, unit='ns')

    async def minimal(self):
        self.d.reset_n.value = 0
        for _ in range(5):
            await self.tick()
            self.c.equal(self.v('uart_tx'), 1, 'reset', 'UART idle in reset')
        if self.cfg.get('negative') != 'held-reset':
            self.d.reset_n.value = 1
        for step in range(3):
            await self.tick()
            self.c.equal(int(self.d.minimal.ready.value), int(step == 2) if self.cfg.get('negative') != 'held-reset' else 0,
                         'reset', 'three-cycle synchronous release')
        self.ram_writes = 0
        self.monitor_ram = True
        for _ in range(2200):
            await self.tick()
            if int(self.d.minimal.done.value):
                break
        self.c.require(bool(int(self.d.minimal.done.value)), 'completion', 'RAM BIST timeout under held reset')
        self.c.equal(self.ram_writes, 512, 'ram_data', 'two complete 256-word sweeps')
        self.c.equal(int(self.d.minimal.failed.value), 0, 'ram_data', 'RAM BIST failed')
        for a in range(256):
            self.c.equal(self.ram[a], ram_pattern(a, 1), 'ram_data', 'complete independent RAM contents')
        # The RAM read port keeps running; BIST write enable must be disabled after completion.
        for _ in range(7):
            await self.tick()
            self.c.equal(self.ram_writes, 512, 'ram_enable', 'no writes after completion')
        self.monitor_ram = False
        for _ in range(2400):
            if int(self.d.minimal.bitpos.value) == 0 and int(self.d.minimal.baud.value) == 0:
                break
            await self.tick()
        else:
            self.c.require(False, 'uart', 'UART start timeout')
        for bit in [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]:
            for _ in range(234):
                self.c.equal(self.v('uart_tx'), bit, 'uart', '115200 8N1 0x55 at 27MHz: 234 clocks/bit')
                await self.tick()
        # Assert between clock edges, then rerun without clearing the memory.
        self.d.reset_n.value = 0
        await Timer(1, unit='ns')
        self.c.equal(int(self.d.minimal.ready.value), 0, 'reset', 'asynchronous PLL-lock/reset assertion')
        await self.tick()
        self.c.equal(int(self.d.minimal.done.value), 0, 'recovery', 'completion clears on reset')
        self.d.reset_n.value = 1
        for _ in range(3):
            await self.tick()
        self.ram_writes = 0
        self.monitor_ram = True
        for _ in range(2200):
            await self.tick()
            if int(self.d.minimal.done.value):
                break
        self.c.equal(self.ram_writes, 512, 'recovery', 'RAM reset/retest full sweeps')
        self.c.equal(int(self.d.minimal.failed.value), 0, 'recovery', 'RAM reset/retest')
        self.monitor_ram = False

    async def ddr_reset(self):
        self.d.rst_n.value = 0
        self.d.ddr_init_done.value = 0
        for n in ('axi_awready', 'axi_arready', 'axi_wready', 'axi_wlast', 'axi_rvalid', 'axi_rlast', 'axi_rid'):
            getattr(self.d, n).value = 0
        for _ in range(3):
            await self.tick()
        self.c.equal(self.v('errors'), 0, 'reset', 'DDR reset clears errors')
        self.c.equal(self.v('verified_passes'), 0, 'reset', 'DDR reset clears passes')
        self.c.equal(self.v('failed'), 0, 'recovery', 'DDR reset clears failure')
        self.d.rst_n.value = 1
        for _ in range(9):
            await self.tick()
            self.c.equal(self.v('axi_awvalid') | self.v('axi_arvalid'), 0, 'calibration_gate', 'no traffic before init')
        self.d.ddr_init_done.value = 1
        await self.tick()

    async def ddr_run(self, fault=None, passes=2):
        await self.ddr_reset()
        memory = bytearray(4096)
        write = read = None
        previous_aw = previous_ar = previous_w = None
        read_fault_sent = False
        expected_aw = expected_ar = 0
        mask_index = 0
        masks = set()
        reads = writes = 0
        initial_events = len(self.events)
        for _ in range(9000):
            state = self.v('phase_status') & 7
            completed = self.v('verified_passes')
            seed = 0xa5a55a5a if completed % 2 == 0 else 0x5a5aa5a5
            aw = (self.v('axi_awaddr'), self.v('axi_awlen')) if self.v('axi_awvalid') else None
            ar = (self.v('axi_araddr'), self.v('axi_arlen')) if self.v('axi_arvalid') else None
            if previous_aw is not None:
                self.c.equal(aw, previous_aw, 'stability', 'AW stable until accepted')
            if previous_ar is not None:
                self.c.equal(ar, previous_ar, 'stability', 'AR stable until accepted')
            if previous_w is not None:
                self.c.equal((self.v('axi_wdata'), self.v('axi_wstrb')), previous_w,
                             'stability', 'write payload stable while controller does not request data')
            awready = int(self.rng.randrange(4) != 0 and write is None and read is None)
            arready = int(self.rng.randrange(4) != 0 and write is None and read is None)
            wready = int(write is not None and self.rng.randrange(4) != 0)
            rvalid = int(read is not None and self.rng.randrange(4) != 0)
            if fault == 'timeout':
                awready = 0
            self.d.axi_awready.value = awready
            self.d.axi_arready.value = arready
            self.d.axi_wready.value = wready
            self.d.axi_rvalid.value = rvalid
            self.d.axi_wlast.value = int(wready and write['beat'] == write['len']) if write else 0
            if wready and fault == 'wlast':
                self.d.axi_wlast.value = 1 - int(write['beat'] == write['len'])
            if rvalid:
                word = read['addr'] + 8*read['beat']
                payload = int.from_bytes(memory[word*4:word*4+32], 'little')
                last = read['beat'] == read['len']
                if fault == 'data' and not read_fault_sent:
                    payload ^= 1 << 64  # corrupt word2; first error must name that word
                    read_fault_sent = True
                self.d.axi_rdata.value = payload
                self.d.axi_rid.value = 3 if fault == 'rid' else 0
                self.d.axi_rlast.value = int(not last if fault == 'rlast' else last)
            if fault == 'init-loss' and state == 2:
                self.d.ddr_init_done.value = 0
            await Timer(1, unit='ns')
            previous_aw = aw if aw and not awready else None
            previous_ar = ar if ar and not arready else None
            previous_w = (self.v('axi_wdata'), self.v('axi_wstrb')) if state == 2 and not wready else None
            # Read-only observations of accepted traffic, checked before DUT advances.
            if aw and awready:
                addr, length = aw
                self.c.require(read is None and write is None, 'address', 'one outstanding burst')
                if length == 15:
                    self.c.equal(addr, expected_aw, 'address', 'full write sweep word addresses')
                    expected_aw += 128
                else:
                    self.c.equal((addr, length), (0, 0), 'address', 'single-beat mask write')
                self.c.require(addr % 128 == 0 and addr+8*(length+1) <= 1024, 'address', 'bounds/alignment/column')
                write = dict(addr=addr, len=length, beat=0)
            if ar and arready:
                addr, length = ar
                if length == 15:
                    self.c.equal(addr, expected_ar, 'address', 'full read sweep word addresses')
                    expected_ar += 128
                else:
                    self.c.equal((addr, length), (0, 0), 'address', 'independent mask readback')
                read = dict(addr=addr, len=length, beat=0)
            if wready:
                word = write['addr'] + 8*write['beat']
                mask = write['len'] == 0
                expected = ddr_pattern(word, seed) ^ ((1 << 256)-1 if mask else 0)
                if self.cfg.get('negative') == 'bad-golden':
                    expected ^= 1
                self.c.equal(self.v('axi_wdata'), expected, 'write_data', 'independent address/complement data')
                strobes = self.v('axi_wstrb')
                self.c.equal(strobes, 1 << mask_index if mask else 0xffffffff, 'byte_enable', 'byte-enable order/polarity')
                if mask:
                    masks.add(mask_index)
                for lane in range(32):
                    if strobes & (1 << lane):
                        memory[word*4+lane] = (expected >> (8*lane)) & 255
                write['beat'] += 1
                writes += 1
                if write['beat'] > write['len']:
                    write = None
            if rvalid:
                word = read['addr'] + 8*read['beat']
                if fault not in ('data', 'rid', 'rlast'):
                    expected = ddr_pattern(word, seed)
                    if read['len'] == 0:
                        expected ^= (1 << (8*(mask_index+1)))-1
                    self.c.equal(self.v('axi_rdata'), expected, 'read_data', 'independent readback')
                read['beat'] += 1
                reads += 1
                if read['beat'] > read['len']:
                    if read['len'] == 0:
                        mask_index = (mask_index+1) % 32
                    read = None
            await self.tick()
            if self.v('failed'):
                self.c.require(fault is not None, 'fault', 'unexpected BIST failure')
                self.c.equal(self.v('errors'), 1, 'fault', 'one latched error')
                self.c.equal(self.v('debug_reason'), {'init-loss':1, 'timeout':2, 'wlast':3, 'data':4, 'rid':5, 'rlast':6}[fault],
                             'fault', 'frozen native110 diagnostic error code')
                self.c.equal(self.v('first_error_word_address'), 2 if fault == 'data' else 0, 'fault', 'first error address')
                for _ in range(3):
                    for n in ('axi_wready', 'axi_rvalid', 'axi_awready', 'axi_arready'):
                        getattr(self.d, n).value = 0
                    await self.tick()
                    self.c.equal(self.v('failed'), 1, 'fault', 'sticky failure')
                    self.c.equal(self.v('errors'), 1, 'fault', 'stable error count')
                    self.c.equal(self.v('axi_awvalid') | self.v('axi_arvalid'), 0, 'fault', 'no new traffic after failure')
                self.transactions.append(dict(fault=fault, writes=writes, reads=reads))
                return
            if self.v('verified_passes') != completed:
                self.c.require(fault is None, 'fault', 'fault was not detected before completion')
                self.c.equal((writes, reads), ((completed+1)*160, (completed+1)*160), 'completion', 'complete 4KiB plus32 mask round')
                self.c.equal(masks, set(range(32)), 'byte_enable', 'all32 masks and readbacks')
                self.c.equal(self.v('full_range_verified'), 1, 'completion', 'range flag')
                self.c.equal(self.v('byte_masks_verified'), 1, 'completion', 'mask flag')
                expected_aw = expected_ar = mask_index = 0
                if completed+1 == passes:
                    self.c.equal(self.v('errors'), 0, 'completion', 'zero errors')
                    self.transactions.append(dict(fault=None, passes=passes, writes=writes, reads=reads,
                                                  events=len(self.events)-initial_events))
                    return
        self.c.require(False, 'completion', 'DDR component timeout')


@cocotb.test()
async def platform_adapter(dut):
    cfg = json.loads(Path(os.environ['NEXUSRV_CASE']).read_text())
    checks = Checks()
    platform = Platform(dut, cfg, checks)
    try:
        checks.equal(cfg['test_mode'], 'COMPONENT', 'input_identity', 'no board/PHY qualification')
        await platform.minimal()
        await platform.ddr_run()
        for fault in ('data', 'rid', 'rlast', 'wlast', 'timeout', 'init-loss'):
            await platform.ddr_run(fault)
        # Interrupt an accepted request with reset; outstanding environment is discarded.
        await platform.ddr_reset()
        dut.axi_awready.value = 1
        await platform.tick()
        checks.equal(platform.v('phase_status') & 7, 2, 'recovery', 'write burst active before reset')
        await platform.ddr_run(passes=1)
        checks.equal(platform.v('verified_passes'), 1, 'recovery', 'fresh round after interrupted write')
    except BaseException as error:
        if checks.first_failure is None:
            checks.first_failure = {'category': 'execution', 'detail': str(error)}
        raise
    finally:
        observed = {'events': platform.events, 'transactions': platform.transactions,
                    'summary': {'cycles': platform.cycles}}
        Path('observations.json').write_text(json.dumps(observed, indent=2)+'\n')
        checks.save('checks.json', **{k: cfg[k] for k in ('case_id','run_id','seed','profile','fixture_sha256','golden_sha256')},
                    runtime={'prefix': sys.prefix, 'cocotb': cocotb.__version__},
                    sequence_sha256=digest(observed), result=observed['transactions'])
