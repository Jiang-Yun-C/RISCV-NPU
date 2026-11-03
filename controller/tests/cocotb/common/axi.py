"""Single-driver 32-bit AXI environment and separate passive protocol monitor.

Subset shared with T04: independent AW/W/B/AR/R, INCR bursts, byte strobes,
zero-filled sparse storage, DECERR precedence, SLVERR injection, reset abort.
No DUT execution results are synthesized by this environment.
"""
from collections import deque
import random


class SparseMemory:
    def __init__(self):
        self.data = {}

    def load(self, address, data):
        self.data.update((address+i, b) for i, b in enumerate(data))

    def read(self, address):
        return sum(self.data.get((address & ~3)+i, 0) << (8*i) for i in range(4))

    def read_transfer(self, address, size):
        mask = ((1 << (8*(1<<size))) - 1) << (8*(address % 4))
        return self.read(address) & mask

    def write(self, address, data, strobe):
        for i in range(4):
            if strobe & (1 << i):
                self.data[(address & ~3)+i] = (data >> (8*i)) & 255

    @staticmethod
    def response(address, write=False):
        if 0xbc000000 <= address or address < 0x10000:
            return 3
        if 0xb4300000 <= address < 0xb4300020:
            return 2
        if write and 0x10000 <= address < 0x20000:
            return 3
        if (0x10000 <= address < 0x30000 or 0x10000000 <= address < 0x10001000
                or 0x80000000 <= address < 0xbc000000):
            return 0
        return 3


def signals(dut, prefix, writable):
    channels = {"ar": ("addr", "len"), "r": ("data", "resp", "last")}
    if writable:
        channels.update(aw=("addr", "len", "size"), w=("data", "strb", "last"), b=("resp",))
        channels["ar"] = ("addr", "len", "size")
    result = {}
    for ch, fields in channels.items():
        for suffix in ("valid", "ready"):
            result[f"{ch}_{suffix}"] = getattr(dut, f"{prefix}_{ch}_{suffix}")
        for field in fields:
            result[f"{ch}_{field}"] = getattr(dut, f"{prefix}_{ch}_payload_{field}")
    return result


class AxiEnvironment:
    def __init__(self, dut, prefix, memory, seed, delay, writable=False, read_hook=None, write_hook=None):
        self.s = signals(dut, prefix, writable)
        self.memory, self.writable = memory, writable
        self.rng, self.delay = random.Random(seed), delay
        self.read_hook, self.write_hook = read_hook, write_hook
        self.reads, self.addresses, self.writes, self.responses = deque(), deque(), deque(), deque()
        self.active_r = self.active_b = None

    def put(self, key, value):
        self.s[key].value = value

    def latency(self):
        return 1+self.rng.randrange(self.delay+1)

    def drive(self, cycle, reset):
        if reset:
            self.reads.clear(); self.addresses.clear(); self.writes.clear(); self.responses.clear()
            self.active_r = self.active_b = None
        self.put("ar_ready", int(not reset and len(self.reads)<4 and self.rng.randrange(self.delay+1)==0))
        if self.active_r is None and self.reads and self.reads[0][0] <= cycle and not reset:
            _, address, beats, beat, size = self.reads[0]
            a = (address & ~((1 << size)-1))+beat*(1 << size)
            resp = self.memory.response(a)
            value = self.memory.read_transfer(a, size) if not resp else 0
            if self.read_hook and not resp:
                value = self.read_hook(a, value)
            self.active_r = (value, resp, int(beat+1 == beats))
        self.put("r_valid", int(self.active_r is not None))
        for key, val in zip(("r_data", "r_resp", "r_last"), self.active_r or (0, 0, 0)):
            self.put(key, val)
        if self.writable:
            self.put("aw_ready", int(not reset and len(self.addresses)<4 and self.rng.randrange(self.delay+1)==0))
            self.put("w_ready", int(not reset and len(self.writes)<8 and self.rng.randrange(self.delay+1)==0))
            if self.active_b is None and self.responses and self.responses[0][0] <= cycle and not reset:
                self.active_b = self.responses.popleft()[1]
            self.put("b_valid", int(self.active_b is not None))
            self.put("b_resp", self.active_b or 0)

    def snapshot(self):
        values={k:int(v.value) for k,v in self.s.items() if k.endswith(('_valid','_ready'))}
        for k,v in self.s.items():
            if k not in values:
                try:
                    values[k]=int(v.value) if values[k.split('_')[0]+'_valid'] else 0
                except ValueError:
                    raise ValueError(f'active AXI {k} is unknown: {v.value}') from None
        return values

    def sample(self, v, cycle, reset):
        if reset:
            return
        if v["r_valid"] and v["r_ready"]:
            _, address, beats, beat, size = self.reads.popleft()
            if beat+1 < beats:
                self.reads.appendleft((cycle+self.latency(), address, beats, beat+1, size))
            self.active_r = None
        if v["ar_valid"] and v["ar_ready"]:
            self.reads.append((cycle+self.latency(), v["ar_addr"], v["ar_len"]+1, 0, v.get("ar_size", 2)))
        if not self.writable:
            return
        if v["b_valid"] and v["b_ready"]:
            self.active_b = None
        if v["aw_valid"] and v["aw_ready"]:
            self.addresses.append([v["aw_addr"], v["aw_len"]+1, v["aw_size"], 0])
        if v["w_valid"] and v["w_ready"]:
            self.writes.append((v["w_data"], v["w_strb"], v["w_last"]))
        if self.addresses and self.writes:
            address, beats, size, beat = self.addresses[0]
            data, strobe, last = self.writes.popleft()
            a = (address & ~((1 << size)-1))+beat*(1 << size)
            resp = self.memory.response(a, True)
            if not resp:
                self.memory.write(a, data, strobe)
                if self.write_hook:
                    self.write_hook(a, data, strobe, cycle)
            if beat+1 == beats:
                self.addresses.popleft()
                self.responses.append((cycle+self.latency(), resp))
            else:
                self.addresses[0][3] += 1


class AxiMonitor:
    """Reconstructs handshakes independently of the active environment queues."""
    def __init__(self, name, checks, writable=False):
        self.name, self.checks, self.writable = name, checks, writable
        self.stalled = {}
        self.reads, self.addresses, self.writes = deque(), deque(), deque()
        self.pending_b = 0
        self.events = []
        self.observed_writes = []

    def sample(self, v, cycle, reset, phase):
        if reset:
            self.stalled.clear(); self.reads.clear(); self.addresses.clear(); self.writes.clear()
            self.pending_b = 0
            return
        channels = [("ar", ("addr", "len")), ("r", ("data", "resp", "last"))]
        if self.writable:
            channels += [("aw", ("addr", "len", "size")), ("w", ("data", "strb", "last")), ("b", ("resp",))]
        for ch, fields in channels:
            payload = tuple(v[f"{ch}_{f}"] for f in fields)
            if ch in self.stalled:
                self.checks.require(v[f"{ch}_valid"] and payload == self.stalled[ch], "axi_stability", [self.name, ch, cycle])
            if v[f"{ch}_valid"] and not v[f"{ch}_ready"]:
                self.stalled[ch] = payload
            else:
                self.stalled.pop(ch, None)
            if not (v[f"{ch}_valid"] and v[f"{ch}_ready"]):
                continue
            self.events.append([cycle, phase, ch, *payload])
            if ch in ("ar", "aw"):
                a, n = v[f"{ch}_addr"], v[f"{ch}_len"]+1
                size = v.get(f"{ch}_size", 2)
                self.checks.require(size<=2 and (a>>12)==((a+n*(1<<size)-1)>>12), "axi_request", [self.name, ch, a, n, size])
                (self.reads if ch=="ar" else self.addresses).append([a, n, size, 0])
            elif ch == "r":
                self.checks.require(bool(self.reads), "axi_response", "R must have AR")
                req = self.reads[0]
                self.checks.equal(v["r_last"], int(req[3]+1==req[1]), "axi_response", "RLAST")
                req[3] += 1
                if v["r_last"]:
                    self.reads.popleft()
            elif ch == "w":
                self.writes.append((v["w_data"], v["w_strb"], v["w_last"]))
            elif ch == "b":
                self.checks.require(self.pending_b>0, "axi_response", "B must follow complete AW/W")
                self.pending_b -= 1
        while self.addresses and self.writes:
            a, n, size, beat = self.addresses[0]
            data, strobe, last = self.writes.popleft()
            a = (a & ~((1<<size)-1))+beat*(1<<size)
            self.checks.equal(last, int(beat+1==n), "axi_write", "WLAST")
            mask = ((1<<(1<<size))-1) << (a % 4)
            self.checks.require(strobe & ~mask == 0, "axi_write", "WSTRB in transfer lanes")
            self.observed_writes.append((cycle, phase, a, data, strobe))
            self.addresses[0][3] += 1
            if last:
                self.addresses.popleft(); self.pending_b += 1
