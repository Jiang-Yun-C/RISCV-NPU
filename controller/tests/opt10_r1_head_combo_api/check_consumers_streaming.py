"""Bounded-memory complete-EOF DOT/FP/lease/publisher review for head preparation.

No DUT or head execution is performed. Input arrays use read-only memmaps. Raw
records are consumed once, with only one bounded same-cycle bucket, two W
leases, current Sw/transport state, scalar event counters and256 state bins.
"""
from collections import Counter, deque
import csv
import hashlib
from pathlib import Path
import numpy as np


def require(ok, detail):
    if not ok:
        raise ValueError('streaming consumer raw: ' + detail)


class SampledDigest:
    def __init__(self):
        self.count = 0
        self.digest = hashlib.sha256()
        self.first = []
        self.last = deque(maxlen=8)

    def add(self, value, canonical):
        self.count += 1
        self.digest.update((canonical + '\n').encode('ascii'))
        if len(self.first) < 8:
            self.first.append(value)
        self.last.append(value)

    def result(self):
        return dict(count=self.count, sha256=self.digest.hexdigest(), first=self.first,
                    last=list(self.last), samples_only=True)


class RawRows:
    def __init__(self, path):
        self.path = Path(path)
        self.before = self.path.stat()
        self.hash = hashlib.sha256()
        self.bytes = 0
        self.complete = False

    def __iter__(self):
        with self.path.open('rb') as stream:
            for line in iter(lambda: stream.readline(4097), b''):
                require(len(line) <= 4096 and line.endswith(b'\n'), 'oversize/truncated raw record')
                self.hash.update(line)
                self.bytes += len(line)
                yield next(csv.reader([line.decode('ascii')]))
        after = self.path.stat()
        require((self.before.st_size, self.before.st_mtime_ns, self.before.st_ino) ==
                (after.st_size, after.st_mtime_ns, after.st_ino), 'raw file changed during complete replay')
        self.complete = True

    def metadata(self):
        require(self.complete, 'raw EOF not checked')
        return dict(path=str(self.path), bytes=self.bytes, sha256=self.hash.hexdigest(), entire_file_checked=True)


class Inputs:
    def __init__(self, image):
        base = Path(image['path'])
        self.n, self.k = int(image['N']), int(image['K'])
        self.groups = self.k // 64
        require(self.n > 0 and self.k > 0 and self.k % 64 == 0, 'input shape')
        def mapped(name, dtype, count):
            path = base / name
            require(path.stat().st_size == np.dtype(dtype).itemsize * count, 'input array size: ' + name)
            return np.memmap(path, dtype=dtype, mode='r', shape=(count,))
        w_name = 'W-full.bin' if (base / 'W-full.bin').exists() else 'W-first129.bin'
        sw_name = 'Sw-full.bin' if (base / 'Sw-full.bin').exists() else 'Sw-first129.bin'
        self.aq = mapped('expected-aq.bin', 'u1', self.k)
        self.w = mapped(w_name, 'u1', self.n * self.k)
        self.sa = mapped('expected-sa.bin', '<u4', self.groups)
        self.sw = mapped(sw_name, '<u4', self.n * self.groups)
        self.dots = mapped('expected-dots.bin', '<i4', self.groups * self.n).reshape(self.groups, self.n)
        self.fp = mapped('expected-fp.bin', '<u4', self.n * self.groups * 3).reshape(self.n, self.groups, 3)
        self.golden = mapped('golden.bin', '<u4', self.n)


class TransportCursor:
    """One physical pass; yield only completed Sw fragments and Y publishers."""
    ACTIVITY = {'AR', 'R', 'AW', 'W', 'B', 'NAR', 'NR', 'NAW', 'NW'}

    def __init__(self, rows, image, close, inputs, variant):
        self.rows, self.image, self.close, self.inputs, self.variant = rows, image, close, inputs, variant
        self.counts = Counter()
        self.records = 0
        self.y_count = 0
        self.sw_count = 0
        self.y_bytes = 0
        self.complete = False
        self.events = self._events()

    def _events(self):
        read = write = nread = nwrite = None
        previous = -1
        ybase, yend = int(self.image['Y']), int(self.image['Y']) + self.inputs.n * 4
        swbase, swend = int(self.image['Sw']), int(self.image['Sw']) + self.inputs.n * self.inputs.groups * 4
        for row in self.rows:
            require(len(row) == 7, 'transport grammar')
            cycle, kind = int(row[0]), row[1]
            require(previous <= cycle <= self.close['cycle'], 'transport event outside close boundary')
            previous = cycle
            require(kind in self.ACTIVITY or kind == 'COMMIT', 'unknown transport record ' + kind)
            self.records += 1
            self.counts[kind] += 1
            values = [int(x, 16) for x in row[2:]]
            if kind == 'AR':
                address, length, size, identity, burst = values
                require(read is None and 0 <= length <= 31 and size in range(5) and burst == 1, 'single DMA read/descriptor')
                amount = (length + 1) << size
                is_sw = swbase <= address < swend
                require(not is_sw or (size in (2, 4) and address + amount <= swend), 'Sw actual fragment bounds/size')
                read = dict(address=address, beats=length + 1, size=size, identity=identity,
                            seen=0, sw=is_sw, AR_cycle=cycle)
            elif kind == 'R':
                data, identity, response, last, _ = values
                require(read is not None and identity == read['identity'] and response == 0 and
                        last == int(read['seen'] + 1 == read['beats']), 'actual accepted R ID/RESP/LAST/count')
                address = read['address'] + (read['seen'] << read['size'])
                if read['sw']:
                    expected = 0
                    for k in range((1 << read['size']) // 4):
                        index = (address - swbase) // 4 + k
                        expected |= int(self.inputs.sw[index]) << (8 * (address & 15) + 32 * k)
                    require(data == expected, 'actual size4/size2 Sw R bits and byte lane')
                read['seen'] += 1
                if last:
                    done = read
                    read = None
                    if done['sw'] and self.variant:
                        self.sw_count += 1
                        yield dict(kind='Sw', address=done['address'], beats=done['beats'], size=done['size'],
                                   AR_cycle=done['AR_cycle'], last_R_cycle=cycle)
            elif kind == 'AW':
                address, length, size, identity, burst = values
                require(write is None and 0 <= length <= 31 and size in range(5) and burst == 1, 'single original publisher write')
                is_y = ybase <= address < yend
                amount = (length + 1) << size
                if is_y:
                    require(size in (2, 4) and address == ybase + self.y_bytes and address + amount <= yend and amount <= 512,
                            'complete original contiguous Y publisher coverage')
                write = dict(address=address, beats=length + 1, size=size, identity=identity, seen=0,
                             AW_cycle=cycle, Y=is_y, readback=False, last_native_W=None)
            elif kind == 'W':
                data, strobe, last, _, _ = values
                require(write is not None and write['seen'] < write['beats'] and
                        last == int(write['seen'] + 1 == write['beats']), 'original Y W count/LAST')
                if write['Y']:
                    address = write['address'] + (write['seen'] << write['size'])
                    expected = mask = 0
                    for k in range((1 << write['size']) // 4):
                        index = (address - ybase) // 4 + k
                        expected |= int(self.inputs.golden[index]) << (8 * (address & 15) + 32 * k)
                        mask |= 15 << ((address & 15) + 4 * k)
                    require(data == expected and strobe == mask, 'original publisher actual complete Y bits/strobes')
                write['seen'] += 1
            elif kind == 'B':
                identity, response, _, _, _ = values
                require(write is not None and write['seen'] == write['beats'] and identity == write['identity'] and response == 0,
                        'original Y B identity/count/status')
                done = write
                write = None
                if done['Y']:
                    require(done['readback'] and nread is None and nwrite is None and cycle - done['AW_cycle'] >= 1024,
                            'original Y native readback and1024 drain before B')
                    self.y_count += 1
                    self.y_bytes += done['beats'] << done['size']
                    if self.variant:
                        yield dict(kind='Y', address=done['address'], beats=done['beats'], size=done['size'],
                                   AW_cycle=done['AW_cycle'], B_cycle=cycle)
            elif kind == 'NAW':
                address, length, identity, _, _ = values
                require(nwrite is None and nread is None and identity == 0 and 0 <= length <= 15, 'native accepted write credit')
                nwrite = dict(address=address, beats=length + 1, seen=0)
            elif kind == 'NW':
                _, _, last, _, _ = values
                require(nwrite is not None and last == int(nwrite['seen'] + 1 == nwrite['beats']), 'native W LEN/LAST')
                nwrite['seen'] += 1
                if last:
                    if write is not None and write['Y']:
                        write['last_native_W'] = cycle
                    nwrite = None
            elif kind == 'NAR':
                address, length, identity, _, _ = values
                require(nread is None and nwrite is None and identity == 0 and 0 <= length <= 15, 'native accepted read credit')
                nread = dict(beats=length + 1, seen=0)
                if write is not None and write['Y']:
                    expected_address = ((write['address'] & ~31) - 0x80000000) // 4
                    expected_beats = (((write['address'] & 31) + (write['beats'] << write['size']) + 31) // 32)
                    if address == expected_address and length + 1 == expected_beats:
                        require(write['last_native_W'] is not None and cycle - write['last_native_W'] >= 1024,
                                'native Y readback issued before original1024-cycle drain')
                        write['readback'] = True
            elif kind == 'NR':
                _, identity, last, _, _ = values
                require(nread is not None and identity == 0 and last == int(nread['seen'] + 1 == nread['beats']), 'native R ID/LEN/LAST')
                nread['seen'] += 1
                if last:
                    nread = None
        require(read is None and write is None and nread is None and nwrite is None, 'transport accepted work pending at EOF')
        require(self.y_bytes == self.inputs.n * 4, 'complete Y object not published at EOF')
        if 'transport_activity' in self.close:
            require(sum(self.counts[k] for k in self.ACTIVITY) == self.close['transport_activity'], 'complete transport/live activity count')
        self.complete = True

    def next(self, kind):
        try:
            event = next(self.events)
        except StopIteration:
            raise ValueError('streaming consumer raw: missing actual transport event ' + kind)
        require(event['kind'] == kind, 'consumer/transport Sw-publisher order differs')
        return event

    def finish(self):
        for event in self.events:
            require(False, 'unmatched actual Sw or Y event at transport EOF: ' + event['kind'])
        require(self.complete, 'transport EOF not checked')


def review_rows(rows, transport_rows, image, close, variant=False):
    """Pure iterator entrypoint for closed-raw comparison and negative generators."""
    inputs = Inputs(image)
    n, k, groups = inputs.n, inputs.k, inputs.groups
    transport = TransportCursor(transport_rows, image, close, inputs, variant)
    counts = Counter()
    hist = {}
    reconstructed = Counter()
    state_previous = None
    state_count = 0
    completion = None
    overlap = None
    dot_in = dot_out = fp_in = fp_out = records = 0
    owner = identity = numeric_epoch = None
    leases = {}
    certified = 0
    sw_current = None
    sw_seen = 0
    sw_starts = 0
    releases = SampledDigest()
    publishers = SampledDigest()
    certificates = SampledDigest()
    last_publisher = None
    max_leases = max_cycle_records = max_dot_waiting = max_fp_pending = 0

    def bind(who, epoch, generation):
        nonlocal owner, identity
        require(who != 0 and epoch > 0, 'full nonzero real owner and epoch')
        if owner is None:
            owner, identity = who, (epoch, generation)
        require((who, epoch, generation) == (owner, *identity), 'full session/sequence/epoch/generation changed')

    def numeric_identity(epoch):
        nonlocal numeric_epoch
        require(epoch > 0, 'numeric epoch')
        if numeric_epoch is None:
            numeric_epoch = epoch
        require(epoch == numeric_epoch and (identity is None or epoch == identity[0]), 'numeric epoch differs from real owner')

    def process_cycle(bucket):
        nonlocal dot_in, dot_out, fp_in, fp_out, certified, sw_current, sw_seen, sw_starts
        nonlocal completion, overlap, state_previous, state_count, records, last_publisher
        nonlocal max_leases, max_cycle_records, max_dot_waiting, max_fp_pending
        cycle = int(bucket[0][0])
        max_cycle_records = max(max_cycle_records, len(bucket))
        actual_dots = {(int(r[2]), int(r[3]), int(r[4])) for r in bucket if r[1] == 'DOT_IN'}
        require(len(actual_dots) <= 1, 'more than one accepted DOT input per physical cycle')
        release_rows = []
        effective_certified = certified
        for r in bucket:
            if r[1] == 'BANK_STATE':
                effective_certified = int(r[3], 16)
        for row in bucket:
            kind = row[1]
            counts[kind] += 1
            records += 1
            if kind == 'DOT_IN':
                r, g, beat = map(int, row[2:5])
                tag, epoch, keep, av, wv = [int(v, 16) for v in row[5:]]
                require((r, g, beat) == (dot_in // (groups * 4), (dot_in // 4) % groups, dot_in % 4), 'original row/group/four-DOT order')
                require(r < n and tag == g and keep == 65535, 'DOT tag/keep/bounds')
                numeric_identity(epoch)
                require(av.to_bytes(16, 'little') == inputs.aq[g * 64 + beat * 16:g * 64 + beat * 16 + 16].tobytes(), 'accepted Aq operand bits')
                offset = r * k + g * 64 + beat * 16
                require(wv.to_bytes(16, 'little') == inputs.w[offset:offset + 16].tobytes(), 'accepted W operand bits')
                if variant:
                    matches = [(b, q) for b, q in leases.items() if q['row'] == r and q['first'] <= g < q['first'] + q['count']]
                    require(len(matches) == 1 and effective_certified & (1 << matches[0][0]), 'actual DOT lacks exactly one certified W lease')
                    lease = matches[0][1]
                    require(lease['consumed'] == (g - lease['first']) * 4 + beat, 'W lease consumer sequence')
                    require(sw_current is not None and sw_current['certified'] and sw_current['first'] <= r < sw_current['first'] + sw_current['rows'], 'actual DOT lacks matching certified Sw block')
                    lease['consumed'] += 1
                dot_in += 1
            elif kind == 'DOT_OUT':
                r = int(row[2])
                tag, epoch, value, bad, protocol = [int(v, 16) for v in row[3:]]
                wr, wg = divmod(dot_out, groups)
                require((r, tag) == (wr, wg) and bad == protocol == 0 and dot_out < dot_in // 4, 'DOT response order/status/accepted group credit')
                numeric_identity(epoch)
                require(value == (int(inputs.dots[wg, wr]) & 0xffffffff), 'actual integer DOT result')
                dot_out += 1
            elif kind == 'FP_IN':
                r, g = map(int, row[2:4])
                tag, epoch, dot, sa, sw, initial = [int(v, 16) for v in row[4:]]
                require((r, g) == divmod(fp_in, groups) and tag == g and fp_in < dot_out, 'FP input order/DOT result credit')
                numeric_identity(epoch)
                require(dot == (int(inputs.dots[g, r]) & 0xffffffff) and sa == int(inputs.sa[g]) and sw == int(inputs.sw[r * groups + g]), 'actual DOT/Sa/Sw FP operands')
                if g == 0:
                    require(initial == 0, 'original row accumulator starts positive zero')
                fp_in += 1
            elif kind == 'FP_OUT':
                r = int(row[2])
                tag, epoch, p, value, partial, status, flags, last = [int(v, 16) for v in row[3:]]
                wr, wg = divmod(fp_out, groups)
                require((r, tag) == (wr, wg) and status == 0 and last == int(wg == groups - 1) and fp_out < fp_in, 'FP retirement order/status/last/credit')
                numeric_identity(epoch)
                require((p, value, partial) == tuple(int(v) for v in inputs.fp[wr, wg]), 'two independent FP32 products and ordered partial bits')
                fp_out += 1
            elif kind == 'W_CMD':
                r, g, count, bank = map(int, row[2:6])
                tag, who, epoch, generation, address = [int(v, 16) for v in row[6:]]
                require(variant and bank in (0, 1) and bank not in leases and 0 <= r < n and 0 < count <= 4 and 0 <= g and g + count <= groups, 'two W bank credits without overwrite')
                require(tag == ((r << 10) | (g << 3) | count) and address == image['W'] + r * k + g * 64, 'full W tag/row/firstgroup/count/address')
                bind(who, epoch, generation)
                if last_publisher is not None:
                    require(cycle > last_publisher['B_cycle'], 'W restart before original Y B retirement/readback drain')
                require(publishers.count >= r // 128, 'W row restart missing preceding128-column publisher')
                leases[bank] = dict(row=r, first=g, count=count, tag=tag, owner=who, epoch=epoch,
                                    generation=generation, consumed=0)
                max_leases = max(max_leases, len(leases))
            elif kind == 'W_RELEASE':
                release_rows.append(row)
            elif kind == 'BANK_STATE':
                held, cert, bad, filled, tag0, tag1, who = [int(v, 16) for v in row[2:]]
                require(held < 4 and cert < 4 and bad == 0 and not (cert & ~held), 'normal W bank certification metadata')
                require(owner is None or who == owner, 'bank state full owner')
                for b, tag in enumerate((tag0, tag1)):
                    if held & (1 << b):
                        require(b in leases and tag == leases[b]['tag'], 'held W bank tag has no current lease')
                certified = cert
            elif kind == 'SW_START':
                first, block_rows, block_groups = map(int, row[2:5])
                who, epoch, generation = [int(v, 16) for v in row[5:]]
                require(variant and not leases and first == sw_starts * 4 and first < n and block_rows == min(4, n - first) and block_groups == groups, 'four-row Sw replacement extent and returned W credits')
                bind(who, epoch, generation)
                sw_current = dict(first=first, rows=block_rows, words=0, certified=False, last_R_cycle=-1)
                sw_starts += 1
            elif kind == 'SW_FRAG':
                first, offset, words = map(int, row[2:5])
                address, length, size, who = [int(v, 16) for v in row[5:]]
                require(sw_current is not None and not sw_current['certified'] and first == sw_current['first'] and offset == sw_current['words'] and who == owner, 'Sw fragment sequential extent/owner')
                require(size in (2, 4) and words == ((length + 1) << size) // 4 and offset + words <= sw_current['rows'] * groups,
                        'Sw fragment valid word count')
                require(address == image['Sw'] + (first * groups + offset) * 4, 'Sw actual logical fragment address')
                accepted = transport.next('Sw')
                require((accepted['address'], accepted['beats'], accepted['size']) == (address, length + 1, size) and cycle < accepted['AR_cycle'], 'Sw fragment binds actual accepted DMA R transport')
                sw_current['words'] += words
                sw_current['last_R_cycle'] = accepted['last_R_cycle']
            elif kind == 'SW_CERT':
                first, block_rows, block_groups = map(int, row[2:5])
                filled, cert, bad, who, epoch, generation, pending = [int(v, 16) for v in row[5:]]
                if cert:
                    bind(who, epoch, generation)
                    require(sw_current is not None and first == sw_seen * 4 == sw_current['first'] and block_groups == groups and block_rows == min(4, n - first), 'one Sw certificate per exact four-row extent')
                    require(not bad and not pending and filled == block_rows * groups == sw_current['words'] and cycle > sw_current['last_R_cycle'], 'Sw certificate before complete actual fragments/retirement')
                    sw_current['certified'] = True
                    sw_seen += 1
                    certificates.add(first, f'{first},{block_rows},{block_groups},{who:x},{epoch:x},{generation:x}')
                elif sw_current is not None:
                    sw_current['certified'] = False
            elif kind == 'PUBLISH_BEGIN':
                r = int(row[2])
                address, held, drained, who = [int(v, 16) for v in row[3:]]
                require(variant and not leases and held == 0 and drained == 1 and who == owner, 'both W banks/accepted transport returned to original publisher')
                require(r == min((publishers.count + 1) * 128, n) - 1 and fp_out == (r + 1) * groups,
                        'publisher before all original row FP results retired')
                published = transport.next('Y')
                require(address == published['address'] and cycle < published['AW_cycle'], 'publisher request binds original actual AW/W/B')
                last_publisher = published
                value = dict(cycle=cycle, row=r, address=address)
                publishers.add(value, f'{cycle},{r},{address:x}')
            elif kind == 'COMPLETE':
                require(completion is None, 'one original completion')
                completion = dict(cycle=cycle, status=int(row[2]), rows=int(row[3]), tiles=int(row[4]), epoch=int(row[5], 16), generation=int(row[6], 16))
            elif kind == 'STATE':
                state = tuple(int(v) for v in row[2:])
                require(len(state) == 18 and 0 <= state[0] < 256 and state[3] in (0, 1), 'STATE schema/control range')
                if state_previous is not None:
                    t, old = state_previous
                    require(cycle > t, 'duplicate STATE sample per cycle')
                    if old[3]:
                        reconstructed[old[0]] += cycle - t
                state_previous = (cycle, state)
                state_count += 1
            elif kind == 'HIST':
                key, ticks = int(row[2]), int(row[3])
                require(0 <= key < 256 and key not in hist and ticks > 0, 'unique bounded state histogram bin')
                require(completion is not None and cycle == completion['cycle'], 'HIST outside original completion')
                hist[key] = ticks
            elif kind == 'OVERLAP':
                require(overlap is None, 'unique overlap counters')
                overlap = dict(W_pending_and_DOT_live=int(row[2]), W_pending_and_FP_busy=int(row[3]), W_pending_and_both=int(row[4]))
            else:
                raise ValueError('streaming consumer raw: unknown consumer event ' + kind)
            max_dot_waiting = max(max_dot_waiting, dot_out - fp_in)
            max_fp_pending = max(max_fp_pending, fp_in - fp_out)
        for row in release_rows:
            bank, r, g, beat = map(int, row[2:6])
            tag, who, epoch, generation = [int(v, 16) for v in row[6:]]
            require(bank in leases, 'release has allocated W credit')
            lease = leases.pop(bank)
            require((r, g, beat, tag, who, epoch, generation) ==
                    (lease['row'], lease['first'] + lease['count'] - 1, 3, lease['tag'], lease['owner'], lease['epoch'], lease['generation']), 'release exact full tag/owner/final required operand')
            require((r, g, beat) in actual_dots and lease['consumed'] == lease['count'] * 4 and effective_certified & (1 << bank), 'release lacks actual same-cycle final DOT consumption and certificate')
            value = dict(cycle=cycle, bank=bank, row=r, group=g, beat=beat)
            releases.add(value, f'{cycle},{bank},{r},{g},{beat}')

    previous = -1
    bucket = []
    for row in rows:
        require(len(row) >= 3, 'consumer record grammar')
        cycle = int(row[0])
        require(previous <= cycle <= close['cycle'], 'consumer event outside final close boundary')
        if bucket and cycle != previous:
            process_cycle(bucket)
            bucket = []
        require(len(bucket) < 512, 'unbounded same-cycle raw bucket')
        bucket.append(row)
        previous = cycle
    if bucket:
        process_cycle(bucket)
    transport.finish()
    require(completion is not None and completion['status'] == 0 and completion['rows'] == n, 'complete successful original linear call')
    require(completion['epoch'] == numeric_epoch, 'completion differs from numeric epoch')
    require((dot_in, dot_out, fp_in, fp_out) == (n * groups * 4, n * groups, n * groups, n * groups), 'complete exact numeric event inventory')
    require(state_previous is not None and not state_previous[1][3], 'state counter active at EOF')
    require(dict(reconstructed) == hist, 'STATE intervals differ from original HIST bins')
    require(overlap is not None, 'original overlap counters absent')
    if variant:
        require(not leases and sw_seen == sw_starts == (n + 3) // 4, 'all Sw blocks and W credits close')
        require(publishers.count == transport.y_count, 'all actual Y publishers have consumer handoffs')
        require(identity == (completion['epoch'], completion['generation']), 'completion full owner epoch/generation')
    return dict(entire_raw_checked=True, records=records, event_counts=dict(counts), actual_DOT_inputs=dot_in,
        actual_DOT_results=dot_out, actual_FP_inputs=fp_in, actual_FP_results=fp_out,
        original_two_mul_ordered_accumulate_bitwise=True, full_owner=hex(owner) if owner else None,
        epoch_generation=identity, leases_remaining=len(leases), completion=completion,
        publisher_handoffs=publishers.result(), Sw_block_certificates=certificates.result(),
        release_DOT_links=releases.result(), state_residence_cycles=hist, state_residence_sum=sum(hist.values()),
        state_transition_records=state_count, state_intervals_match_HIST=True, overlap=overlap,
        transport=dict(records=transport.records, event_counts=dict(transport.counts), complete_EOF=True,
                       Sw_fragments=transport.sw_count, Y_publishers=transport.y_count, Y_bytes=transport.y_bytes),
        bounded_state=dict(max_live_W_leases=max_leases, max_same_cycle_records=max_cycle_records,
                           max_completed_DOT_waiting=max_dot_waiting, max_FP_inflight=max_fp_pending,
                           stored_full_rows=0, stored_group_records=0, input_storage='read-only np.memmap'), GO=False)


def review(path, image, close, variant=False):
    path = Path(path)
    consumers = RawRows(path)
    transport = RawRows(path.parent / 'api-transport.csv')
    result = review_rows(iter(consumers), iter(transport), image, close, variant=variant)
    result['consumer_raw'] = consumers.metadata()
    result['transport_raw'] = transport.metadata()
    return result
