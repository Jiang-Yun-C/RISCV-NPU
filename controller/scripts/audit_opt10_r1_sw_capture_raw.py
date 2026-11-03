#!/usr/bin/env python3
"""Replay bounded Sw-capture native/DMA/query raw; no integrated API scope."""
from collections import Counter
import csv
from pathlib import Path


def need(ok, why):
    if not ok:
        raise ValueError(why)


def scale32(word):
    return word == 0 or ((word >> 31) == 0 and 1 <= ((word >> 23) & 255) <= 254)


def replay(trace, rows=None):
    raw = Path(trace).read_bytes()
    need(raw.endswith(b'\n'), 'truncated Sw raw')
    if rows is None:
        rows = list(csv.reader(raw.decode('ascii').splitlines()))
    need(all(int(a[0]) <= int(b[0]) for a, b in zip(rows, rows[1:])), 'global Sw cycle order')
    allowed = {'BEGIN', 'DONE', 'S', 'START', 'CMD', 'AR', 'R', 'RESULT', 'NAR', 'NR', 'Q'}
    need(all(r[1] in allowed for r in rows), 'unknown Sw event')
    begins = {int(r[2]): r for r in rows if r[1] == 'BEGIN'}
    dones = {int(r[2]): r for r in rows if r[1] == 'DONE'}
    need(len(begins) == len(dones) == sum(r[1] == 'BEGIN' for r in rows) ==
         sum(r[1] == 'DONE' for r in rows) == 24, 'Sw framing inventory')
    need(set(begins) == set(dones) == set(range(1, 25)), 'Sw case sequence')
    expected_kinds = [0, 1, 2, 3, 10, 11, 12, 13, 20, 21, 22, 23, 24, 25, 26,
                      31, 32, 33, 34, 35, 36, 40, 41, 42]
    need([int(begins[i][3]) for i in begins] == expected_kinds, 'Sw frozen workload changed')
    summaries = []
    totals = Counter()
    for case, begin in begins.items():
        kind, first, last = int(begin[3]), int(begin[0]), int(dones[case][0])
        events = [r for r in rows if int(r[2]) == case and first <= int(r[0]) <= last]
        counts = Counter()
        block = command = native = None
        result_cycle = None
        native_bytes = {}
        all_native = []
        word_values = {}
        good = True
        previous_state = None
        cert_seen = False
        def expected_word(address):
            index = (address >> 2) & 4095
            if kind in (10, 12, 13) and index == 0x2200 // 4:
                return {10: 0x80000000, 12: 1, 13: 0}[kind]
            if kind == 11 and index == 0x2200 // 4 + 15:
                return 0x7fc00000
            return 0x3f000000 + index * 257
        for r in events:
            tick, event = int(r[0]), r[1]
            counts[event] += 1
            if event == 'START':
                need(command is None and native is None, 'Sw START abandoned an accepted fragment')
                fr, n, groups = map(int, r[3:6])
                block = dict(first_row=fr, rows=n, groups=groups, owner=r[6], epoch=r[7], generation=r[8])
                good = 1 <= n <= 4 and 1 <= groups <= 76 and n * groups <= 304
                word_values = {}
                result_cycle = None
                cert_seen = False
            elif event == 'CMD':
                need(block is not None and command is None and native is None, 'overlapping Sw command')
                address, size, length, offset, mode = int(r[3], 16), *map(int, r[4:8])
                command = dict(address=address, size=size, beats=length + 1, offset=offset, mode=mode, R=0, AR=False)
                words = (length + 1) * (4 if size == 4 else 1)
                if offset != len(word_values) or offset + words > block['rows'] * block['groups']:
                    good = False
                result_cycle = None
            elif event == 'AR':
                need(command is not None and not command['AR'], 'unmatched/duplicate Sw AXI AR')
                need((int(r[3], 16), int(r[4]), int(r[5]) + 1, int(r[6], 16)) ==
                     (command['address'], command['size'], command['beats'], 0), 'Sw actual AR differs from CMD')
                command['AR'] = True
            elif event == 'NAR':
                need(command is not None and native is None, 'overlapping Sw native command')
                native = dict(address=int(r[3], 16) * 4, beats=int(r[4]) + 1, index=0)
                need(native['address'] % 32 == 0 and 1 <= native['beats'] <= 16, 'Sw native geometry')
            elif event == 'NR':
                need(native is not None, 'unmatched native Sw R')
                idx, final, data = int(r[3]), int(r[4]), int(r[5], 16)
                need(idx == native['index'] and final == int(idx + 1 == native['beats']), 'Sw native LEN/LAST')
                address = native['address'] + idx * 32
                expected = sum(expected_word(address + k * 4) << (k * 32) for k in range(8))
                need(data == expected, 'Sw native frozen memory bits differ')
                for k, byte in enumerate(data.to_bytes(32, 'little')):
                    native_bytes[address + k] = byte
                native['index'] += 1
                all_native.append((tick, address))
                if native['index'] == native['beats']:
                    native = None
            elif event == 'R':
                need(command is not None and command['AR'] and native is None, 'Sw R before complete native buffering')
                idx = command['R']
                need(idx < command['beats'], 'extra real Sw AXI R')
                address = command['address'] + (idx << command['size'])
                lane, amount = address & 15, 1 << command['size']
                expect = 0
                for k in range(amount):
                    p = (address - 0x80000000) + k
                    need(p in native_bytes, 'Sw AXI byte without actual native read')
                    expect |= native_bytes[p] << (8 * (lane + k))
                need((int(r[3], 16), int(r[4], 16), int(r[5]), int(r[6], 16)) ==
                     (expect, 0, int(idx + 1 == command['beats']), 0), 'Sw actual AXI bits/response/LAST/ID differ')
                taken, response, rid, final = int(r[7]), int(r[8], 16), int(r[9], 16), int(r[10])
                if not taken or response != 0 or rid != 0 or final != int(idx + 1 == command['beats']):
                    good = False
                if taken:
                    for k in range(amount // 4):
                        word = (int(r[3], 16) >> (8 * lane + 32 * k)) & 0xffffffff
                        target = command['offset'] + idx * (amount // 4) + k
                        if target in word_values or not scale32(word):
                            good = False
                        word_values[target] = word
                command['R'] += 1
            elif event == 'RESULT':
                need(command is not None and native is None and command['R'] == command['beats'], 'Sw result before real transport LEN')
                if int(r[3], 16) != 0 or int(r[4], 16) != 0:
                    good = False
                result_cycle = tick
                command = None
            elif event == 'S':
                a, bad, cert, pending, filled, physical, no_w, stop, revoke, fault, _ = map(int, r[3:14])
                if block is not None:
                    if r[14:17] != [block['owner'], block['epoch'], block['generation']] or stop or revoke or fault or (pending and not no_w):
                        good = False
                if cert:
                    need(block is not None and good and not bad and not pending and command is None and native is None,
                         'Sw certificate after failure or with accepted fragment pending')
                    need(filled == block['rows'] * block['groups'] and set(word_values) == set(range(filled)),
                         'Sw certificate without all logical scale words exactly once')
                    need(result_cycle is not None and tick > result_cycle, 'Sw certificate before result')
                    if not cert_seen:
                        need(previous_state is not None and int(previous_state[8]) == int(previous_state[9]) == 1,
                             'Sw certificate before prior-edge true physical drain/no W lease')
                    cert_seen = True
                previous_state = r
            elif event == 'Q':
                need(block is not None and good and cert_seen, 'query without a valid complete Sw certificate')
                row, group, count = map(int, r[3:6])
                vr, vg = int(r[7]), int(r[8])
                need(0 <= row < block['rows'] and 1 <= count <= 4 and group + count <= block['groups'], 'Sw vector query bounds')
                need(0 <= vr < block['rows'] and 0 <= vg < block['groups'], 'Sw value query bounds')
                vector = sum(word_values[row * block['groups'] + group + k] << (32 * k) for k in range(count))
                need(int(r[6], 16) == vector and int(r[9], 16) == word_values[vr * block['groups'] + vg], 'Sw query bits/order/independent second port')
        done = dones[case]
        need(command is None and native is None, 'Sw terminal accepted fragment not drained')
        need([int(done[4]), int(done[5]), int(done[6]), int(done[7])] ==
             [counts['CMD'], counts['R'], counts['NR'], counts['Q']], 'Sw DONE event inventory differs')
        expected_bad = int(kind not in (0, 1, 2, 3, 13, 42))
        need((int(done[8]), int(done[9])) == (expected_bad, 1 - expected_bad), 'Sw frozen terminal expectation differs')
        need(int(done[3]) == last - first, 'Sw component cycle boundary differs')
        totals.update(counts)
        summaries.append(dict(case=case, kind=kind, component_cycles=last - first,
                              counts=dict(counts), terminal_bad=expected_bad))
    return dict(scope='SW_MODULE_REAL_NATIVE_DMA_TAPS_AND_QUERY_RAW_ONLY', cases=summaries,
                totals=dict(totals), CPU_API_cycles=None, integrated_resource_use=None, GO=False), rows
