"""Actual production service on reduced synthetic model; no board speed claim."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from .fixtures import write_assets

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


class ServiceEnhancementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="t27-enhanced-service-")
        cls.directory = Path(cls.temp.name)
        write_assets(cls.directory, text_encoding=True)
        spec = importlib.util.spec_from_file_location("build_enhanced", ROOT / "scripts/build_t27_streaming.py")
        build = importlib.util.module_from_spec(spec); spec.loader.exec_module(build)
        _, header = build.runtime_identity(ROOT, ["-DNX_OPT13_TEST", "-DNX_PROFILE_INTEGER=1"], "synthetic-native-test")
        (cls.directory / "t27_runtime_identity.h").write_text(header)
        command = ["gcc", "-std=c11", "-O2", "-fno-strict-aliasing", "-ffp-contract=off", "-fno-fast-math",
                   "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation", "-Wno-unknown-pragmas",
                   "-DNX_PORTABLE", "-DNX_OPT13_TEST", "-DNX_T25_UART", "-DNX_T25_SERVICE_TEST",
                   "-DNX_T27_SERVICE_ENHANCEMENTS=1", "-DNX_PROFILE_INTEGER=1", "-DNX_PREFIX_CAPTURE=1",
                   "-DNX_DIAG_HOST", "-include", str(ROOT / "firmware/runtime/board/diag.h"),
                   "-idirafter", str(ROOT / "firmware/drivers/accel"),
                   "-idirafter", str(ROOT / "software/include"),
                   "-I", str(cls.directory), "-I", str(ROOT / "firmware/runtime/port"),
                   "-I", str(ROOT / "firmware/runtime/reference"), str(HERE / "native_main.c"),
                   str(cls.directory / "tokenizer.S")]
        command += [str(ROOT / ("firmware/runtime/port/" + name + ".c")) for name in ("runtime", "model", "tokenizer", "stream", "prefix", "control")]
        command += [str(ROOT / p) for p in ("firmware/runtime/reference/nx_reference.c",
                    "firmware/runtime/board/diag.c", "firmware/runtime/board/led_control.c",
                    "firmware/application/application.c")]
        command += ["-lm", "-o", str(cls.directory / "service")]
        subprocess.run(command, check=True, timeout=60)
        bank_command = command.copy()
        bank_command.insert(1, "-DNX_LED_BANK=1")
        bank_command[-1] = str(cls.directory / "service-bank")
        subprocess.run(bank_command, check=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_service(self, commands, *arguments):
        run = subprocess.run([str(self.directory / "service"), *arguments], input=commands,
                             capture_output=True, text=True, check=True, timeout=45)
        return run.stdout, [json.loads(x) for x in run.stderr.splitlines()]

    def run_bank(self, commands, *arguments):
        run = subprocess.run([str(self.directory / "service-bank"), *arguments], input=commands,
                             capture_output=True, text=True, check=True, timeout=45)
        return run.stdout, [json.loads(x) for x in run.stderr.splitlines()]

    @staticmethod
    def fields(line):
        return {k: int(v, 16) for k, v in re.findall(r"(\w+)=([0-9a-f]{16})", line)}

    def test_cold_hot_full_production_text_keeps_output_and_kv(self):
        wire, states = self.run_service(":text 2 hello\n:text 2 hello\n")
        self.assertNotIn("T25 ERROR", wire)
        prefix = [self.fields(x) for x in wire.splitlines() if x.startswith("T25 PREFIX 1 ")]
        self.assertEqual([x["hit"] for x in prefix], [0, 1])
        self.assertEqual([x["captured"] for x in prefix], [1, 0])
        self.assertGreater(prefix[0]["prepare_ticks"], 0)
        self.assertEqual(prefix[1]["prepare_ticks"], 0)
        self.assertGreater(prefix[0]["tokens"], 0)
        self.assertEqual(states[0], states[1])
        cold, cold_states = self.run_service(":prefix 0\n:text 2 hello\n")
        self.assertNotIn("T25 ERROR", cold)
        self.assertEqual(states[0], cold_states[-1])

    def test_prefix_disable_and_explicit_reset_revoke_hits(self):
        wire, _ = self.run_service(":text 1 alpha\n:text 1 beta\n:reset\n:text 1 alpha\n:prefix 0\n:text 1 beta\n")
        prefix = [self.fields(x) for x in wire.splitlines() if x.startswith("T25 PREFIX 1 ")]
        self.assertEqual([x["hit"] for x in prefix], [0, 1, 0, 0])

    def test_cancel_recovers_and_next_production_request_reaches_eos(self):
        # Cancellation is successful only if the same loaded service can run
        # the next request. Zero stores or a reset internal state alone cannot
        # pass this regression. Returned IDs are an explicit JSON/EOS fixture;
        # the reduced real-model forward work still executes for both requests.
        wire, states = self.run_service(":text 4 hello\n:text 8 hello\n", "recovery-decode")
        self.assertIn("status=accepted", wire)
        self.assertIn("T25 ERROR fffffff5", wire)
        self.assertEqual(wire.count("T25 METRICS "), 1)
        self.assertEqual(wire.count("T25 STREAM 1 ABORT"), 1)
        self.assertNotIn("D27 HALTED", wire)
        self.assertEqual(wire.count("T25 REQUEST 1 "), 2)
        self.assertEqual(wire.count("T25 REQUEST_END 1 "), 1)
        metrics = self.fields(next(x for x in wire.splitlines() if x.startswith("T25 METRICS ")))
        self.assertEqual(metrics["stop"], 1)
        self.assertIn("0002505d", wire)
        self.assertEqual(states[-1]["state"], 3)
        self.assertEqual(states[-1]["stop"], 1)
        self.assertEqual(states[-1]["fixture_model_loads"], 1)
        self.assertEqual(states[-1]["fixture_main_entries"], 1)
        self.assertEqual(states[-1]["legacy_stores"], 0)

    def test_action_prefix_cold_hot_matches_uncached_logits_and_kv(self):
        wire, states = self.run_service(":act 打开灯\n:act 打开灯\n")
        requests = [self.fields(x) for x in wire.splitlines() if x.startswith("T25 REQUEST 1 ")]
        self.assertEqual([x["prefix_hit"] for x in requests], [0, 1])
        self.assertGreater(requests[0]["prefix_tokens"], 0)
        self.assertEqual(states[0], states[1])
        _, cold_states = self.run_service(":prefix 0\n:act 打开灯\n")
        self.assertEqual(states[0], cold_states[-1])
        # This tiny real model cannot emit production EOS. Its incomplete
        # output must never produce LED stores or a successful action receipt.
        actions = [x for x in wire.splitlines() if x.startswith("T27 ACTION 1 ")]
        self.assertEqual(len(actions), 2)
        self.assertTrue(all("status=INCOMPLETE" in x and "writes=0000000000000000" in x for x in actions))
        self.assertNotIn("stage=executing", wire)

    def test_text_action_template_switches_are_cold_and_same_template_reuses(self):
        commands = [":text 2 hello", ":act 打开灯", ":act 关闭灯", ":text 2 hello", ":text 2 world"]
        wire, states = self.run_service("\n".join(commands) + "\n")
        requests = [self.fields(x) for x in wire.splitlines() if x.startswith("T25 REQUEST 1 ")]
        self.assertEqual([x["prefix_hit"] for x in requests], [0, 0, 1, 0, 1])
        for command, state in zip(commands, states):
            _, cold_states = self.run_service(":prefix 0\n" + command + "\n")
            self.assertEqual(state, cold_states[-1], command)

    def test_received_and_phases_follow_real_model_events(self):
        wire, _ = self.run_service(":text 2 hello\n")
        positions = [wire.index(needle) for needle in ("T25 RECEIVED 1 kind=text", "T25 REQUEST 1 ",
                     "stage=prefill", "T25 STREAM 1 BEGIN", "T25 STREAM 1 TEXT", "stage=decode",
                     "T25 TEXT ", "stage=validating", "T25 METRICS ")]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(wire.count("T25 PHASE 1 "), 3)
        self.assertNotIn("stage=executing", wire)

    def test_action_cancel_cannot_execute_and_next_request_completes(self):
        wire, states = self.run_service(":act 打开灯\n:text 8 hello\n", "recovery-decode")
        self.assertIn("T25 RECEIVED 1 kind=action", wire)
        self.assertIn("status=accepted", wire)
        self.assertNotIn("D27 HALTED", wire)
        self.assertEqual(wire.count("T25 REQUEST 1 "), 2)
        self.assertEqual(wire.count("T25 METRICS "), 1)
        self.assertEqual(wire.count("T25 REQUEST_END 1 "), 1)
        self.assertEqual(states[-1]["stop"], 1)
        self.assertEqual(states[-1]["fixture_model_loads"], 1)
        self.assertEqual(states[-1]["fixture_main_entries"], 1)
        self.assertEqual(states[-1]["legacy_stores"], 0)
        for row in (x for x in wire.splitlines() if x.startswith("T27 ACTION 1 ")):
            self.assertNotIn("status=OK", row)
            self.assertEqual(self.fields(row)["writes"], 0)

    def test_direct_led_remains_outside_model_and_requires_readback(self):
        wire, _ = self.run_service(":led 1\n:led?\n:led 0\n")
        self.assertNotIn("T25 REQUEST 1 ", wire)
        self.assertNotIn("T25 RECEIVED 1 ", wire)
        rows = [x for x in wire.splitlines() if x.startswith("T27 LED 1 ")]
        self.assertTrue(all("status=OK" in x for x in rows))
        self.assertEqual([self.fields(x)["state"] for x in rows], [1, 1, 0])
        self.assertEqual([self.fields(x)["writes"] for x in rows], [1, 0, 1])

    def test_action_gate_fixture_eos_executes_once_and_hot_prefix_still_hits(self):
        # Explicit scripted-next-ID fixture; this tests the actual production
        # parser/commit/readback chain, not the model's ability to understand.
        wire, _ = self.run_service(":act 打开灯\n:act 打开灯\n:led?\n", "led-eos")
        self.assertNotIn("T25 ERROR", wire)
        requests = [self.fields(x) for x in wire.splitlines() if x.startswith("T25 REQUEST 1 ")]
        actions = [x for x in wire.splitlines() if x.startswith("T27 ACTION 1 ")]
        self.assertEqual([x["prefix_hit"] for x in requests], [0, 1])
        self.assertEqual(len(actions), 2)
        self.assertTrue(all("status=OK" in x for x in actions))
        self.assertEqual([self.fields(x)["writes"] for x in actions], [1, 1])
        self.assertEqual([self.fields(x)["state"] for x in actions], [1, 1])
        self.assertEqual(wire.count("stage=executing"), 2)

    def test_action_gate_fixture_timeout_at_execution_phase_does_not_store_or_reuse(self):
        wire, _ = self.run_service(":act 打开灯\n:led?\n:act 打开灯\n:led?\n", "led-final-timeout")
        actions = [x for x in wire.splitlines() if x.startswith("T27 ACTION 1 ")]
        requests = [self.fields(x) for x in wire.splitlines() if x.startswith("T25 REQUEST 1 ")]
        reads = [self.fields(x) for x in wire.splitlines() if x.startswith("T27 LED 1 ")]
        self.assertIn("status=TIMEOUT", actions[0])
        self.assertIn("status=OK", actions[1])
        self.assertEqual([self.fields(x)["writes"] for x in actions], [0, 1])
        self.assertEqual([x["state"] for x in reads], [0, 1])
        self.assertEqual([x["prefix_hit"] for x in requests], [0, 0])
        self.assertEqual(wire.count("T25 METRICS "), 1)

    def test_action_gate_fixture_cancel_after_eos_prevents_store_and_revokes_cache(self):
        wire, _ = self.run_service(":act 打开灯\n:led?\n:act 打开灯\n:led?\n", "led-final-cancel")
        actions = [x for x in wire.splitlines() if x.startswith("T27 ACTION 1 ")]
        requests = [self.fields(x) for x in wire.splitlines() if x.startswith("T25 REQUEST 1 ")]
        reads = [self.fields(x) for x in wire.splitlines() if x.startswith("T27 LED 1 ")]
        self.assertIn("status=CANCELLED", actions[0])
        self.assertIn("status=OK", actions[1])
        self.assertEqual([self.fields(x)["writes"] for x in actions], [0, 1])
        self.assertEqual([x["state"] for x in reads], [0, 1])
        self.assertEqual([x["prefix_hit"] for x in requests], [0, 0])

    def test_bank_direct_preserves_unselected_bits_and_release_restores_automatic_ownership(self):
        wire, states = self.run_bank(":ledm 45 45\n:ledm 36 0\n:ledauto 8\n:ledm?\n:ledauto 1\n:led 1\n:ledm?\n")
        rows = [self.fields(x) for x in wire.splitlines() if x.startswith("T27 LED_BANK 1 ")]
        self.assertEqual([(x["mask"], x["values"], x["owned"], x["writes"]) for x in rows],
                         [(45,45,45,1), (36,9,45,1), (8,1,37,1), (45,1,37,0), (1,0,36,1), (45,1,37,0)])
        self.assertEqual(states[-1]["bank_stores"], 4)
        self.assertEqual(states[-1]["legacy_stores"], 1)
        self.assertIn("T27 LED_BANK_CAPABILITIES 1 mask=000000000000002d atomic=1 targets=explicit", wire)

    def test_bank_each_explicit_physical_led_bit_can_be_selected_individually(self):
        for mask in (1, 4, 8, 32):
            with self.subTest(mask=mask):
                wire, states = self.run_bank(f":ledm {mask} {mask}\n:ledauto {mask}\n:ledm?\n")
                rows = [self.fields(x) for x in wire.splitlines() if x.startswith("T27 LED_BANK 1 ")]
                self.assertEqual(rows[0]["values"], mask)
                self.assertEqual(rows[0]["owned"], 1 | mask)
                self.assertEqual(rows[1]["values"], 0)
                self.assertEqual(rows[1]["owned"], 1 & ~mask)
                self.assertEqual(rows[2]["values"], 0)
                self.assertEqual(states[-1]["bank_stores"], 2)

    def test_bank_invalid_masks_values_and_spelling_never_store(self):
        commands = [":ledm 0 0", ":ledm 2 2", ":ledm 16 0", ":ledm 64 0", ":ledm 256 0",
                    ":ledm 45 2", ":ledm 36 8", ":ledm 1 256", ":ledm -1 0", ":ledm 1 -1",
                    ":ledm 4294967296 0", ":ledm 1 4294967296", ":ledm 1", ":ledm 1 1 extra",
                    ":ledauto 0", ":ledauto 2", ":ledauto 4294967296", ":ledauto 1 extra", ":ledm? extra"]
        wire, states = self.run_bank("\n".join(commands) + "\n:ledm?\n")
        rows = [x for x in wire.splitlines() if x.startswith("T27 LED_BANK 1 ")]
        self.assertEqual(len(rows), len(commands) + 1)
        self.assertTrue(all("status=OK" not in x and self.fields(x)["writes"] == 0 for x in rows[:-1]))
        self.assertEqual(self.fields(rows[-1])["values"], 0)
        self.assertEqual(self.fields(rows[-1])["owned"], 1)
        self.assertEqual(states[-1]["bank_stores"], 0)
        self.assertEqual(states[-1]["legacy_stores"], 0)

    def test_legacy_build_refuses_bank_without_any_new_csr_access_or_led0_fallback(self):
        wire, states = self.run_service(":ledm 1 1\n:ledauto 1\n:ledm?\n:actm 1 打开灯\n:led 1\n:led?\n")
        self.assertNotIn("LED_BANK_CAPABILITIES", wire)
        self.assertNotIn("T25 REQUEST 1 ", wire)
        rows = [x for x in wire.splitlines() if x.startswith("T27 LED_BANK 1 ")]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all("status=UNSUPPORTED" in x and self.fields(x)["writes"] == 0 for x in rows))
        self.assertTrue(all(self.fields(x)["values"] == 0xffffffff and self.fields(x)["owned"] == 0xffffffff for x in rows))
        self.assertEqual(states[-1]["bank_stores"], 0)
        self.assertEqual(states[-1]["legacy_stores"], 1)

    def test_bank_identity_or_capability_mismatch_rejects_without_model_or_store(self):
        for mode in ("bank-missing", "bank-bad-caps"):
            with self.subTest(mode=mode):
                wire, states = self.run_bank(":ledm 36 36\n:ledauto 36\n:ledm?\n:actm 36 打开灯\n", mode)
                self.assertNotIn("LED_BANK_CAPABILITIES", wire)
                self.assertNotIn("T25 REQUEST 1 ", wire)
                rows = [x for x in wire.splitlines() if x.startswith("T27 LED_BANK 1 ")]
                self.assertTrue(all("status=STATE" in x and self.fields(x)["writes"] == 0 for x in rows))
                self.assertEqual(states[-1]["bank_stores"], 0)
                self.assertEqual(states[-1]["legacy_stores"], 0)

    def test_bank_invalid_action_target_is_rejected_before_model_dispatch(self):
        commands = [":actm 0 打开灯", ":actm 2 打开灯", ":actm 255 打开灯", ":actm -1 打开灯",
                    ":actm 4294967296 打开灯", ":actm 36", ":actm 36 ", ":actm x 打开灯"]
        wire, states = self.run_bank("\n".join(commands) + "\n:ledm?\n", "led-eos")
        self.assertEqual(wire.count("T25 ERROR"), len(commands))
        self.assertNotIn("T25 REQUEST 1 ", wire)
        self.assertNotIn("T27 ACTION_BANK 1 ", wire)
        self.assertEqual(states[-1]["bank_stores"], 0)
        self.assertEqual(states[-1]["legacy_stores"], 0)

    def test_bank_model_target_is_explicit_and_same_prompt_prefix_reuses_across_masks(self):
        wire, states = self.run_bank(":led 1\n:actm 36 打开灯\n:actm 8 打开灯\n:ledm?\n", "led-eos")
        rows = [x for x in wire.splitlines() if x.startswith("T27 ACTION_BANK 1 ")]
        self.assertTrue(all("status=OK" in x for x in rows))
        self.assertEqual([(self.fields(x)["mask"], self.fields(x)["values"], self.fields(x)["owned"], self.fields(x)["writes"]) for x in rows],
                         [(36,37,37,1), (8,45,45,1)])
        requests = [self.fields(x) for x in wire.splitlines() if x.startswith("T25 REQUEST 1 ")]
        self.assertEqual([x["prefix_hit"] for x in requests], [0, 1])
        self.assertEqual(states[-1]["bank_stores"], 2)
        self.assertEqual(states[-1]["legacy_stores"], 1)

    def test_bank_model_off_only_clears_selected_mask(self):
        wire, states = self.run_bank(":ledm 45 45\n:actm 36 关闭灯\n:ledm?\n", "bank-off-eos")
        action = next(x for x in wire.splitlines() if x.startswith("T27 ACTION_BANK 1 "))
        self.assertIn("status=OK", action)
        self.assertEqual((self.fields(action)["values"], self.fields(action)["owned"], self.fields(action)["writes"]), (9,45,1))
        self.assertEqual(states[-1]["bank_stores"], 2)

    def test_bank_model_multi_step_program_prevalidates_and_uses_one_atomic_store_per_step(self):
        wire, states = self.run_bank(":led 1\n:actm 40 打开灯\n:ledm?\n", "bank-multi-eos")
        action = next(x for x in wire.splitlines() if x.startswith("T27 ACTION_BANK 1 "))
        self.assertIn("status=OK", action)
        self.assertEqual((self.fields(action)["mask"], self.fields(action)["values"], self.fields(action)["owned"], self.fields(action)["writes"]), (40,1,41,2))
        self.assertEqual(states[-1]["bank_stores"], 2)

    def test_bank_model_invalid_later_operation_and_missing_eos_never_store(self):
        for mode, status in (("bank-invalid-eos", "UNSUPPORTED"), ("bank-duplicate-eos", "DUPLICATE"), ("bank-no-eos", "INCOMPLETE")):
            with self.subTest(mode=mode):
                wire, states = self.run_bank(":actm 36 打开灯\n:ledm?\n", mode)
                action = next(x for x in wire.splitlines() if x.startswith("T27 ACTION_BANK 1 "))
                self.assertIn("status=" + status, action)
                self.assertEqual(self.fields(action)["writes"], 0)
                read = next(self.fields(x) for x in wire.splitlines() if x.startswith("T27 LED_BANK 1 "))
                self.assertEqual((read["values"], read["owned"]), (0, 1))
                self.assertEqual(states[-1]["bank_stores"], 0)

    def test_bank_model_final_timeout_or_cancel_prevents_all_selected_stores(self):
        for mode, status in (("led-final-timeout", "TIMEOUT"), ("led-final-cancel", "CANCELLED")):
            with self.subTest(mode=mode):
                wire, states = self.run_bank(":actm 36 打开灯\n:ledm?\n:actm 36 打开灯\n:ledm?\n", mode)
                actions = [x for x in wire.splitlines() if x.startswith("T27 ACTION_BANK 1 ")]
                self.assertIn("status=" + status, actions[0])
                self.assertIn("status=OK", actions[1])
                self.assertEqual([self.fields(x)["writes"] for x in actions], [0, 1])
                reads = [self.fields(x) for x in wire.splitlines() if x.startswith("T27 LED_BANK 1 ")]
                self.assertEqual([(x["values"], x["owned"]) for x in reads], [(0,1), (36,37)])
                requests = [self.fields(x) for x in wire.splitlines() if x.startswith("T25 REQUEST 1 ")]
                self.assertEqual([x["prefix_hit"] for x in requests], [0, 0])
                self.assertEqual(states[-1]["bank_stores"], 1)

    def test_bank_plain_text_even_if_json_never_executes(self):
        wire, states = self.run_bank(":text 3 打开灯\n:ledm?\n", "led-eos")
        self.assertNotIn("T27 ACTION_BANK", wire)
        self.assertNotIn("T27 ACTION 1 ", wire)
        self.assertEqual(states[-1]["bank_stores"], 0)
        self.assertEqual(states[-1]["legacy_stores"], 0)

    def test_bank_failed_readback_reports_issued_store_once_without_retry(self):
        wire, states = self.run_bank(":ledm 36 36\n:ledm?\n", "bank-readback-fail")
        rows = [x for x in wire.splitlines() if x.startswith("T27 LED_BANK 1 ")]
        self.assertIn("status=STATE", rows[0])
        self.assertEqual(self.fields(rows[0])["writes"], 1)
        self.assertEqual(self.fields(rows[1])["values"], 0)
        self.assertEqual(states[-1]["bank_stores"], 1)

    def test_stale_cancel_does_not_affect_current_result(self):
        wire, states = self.run_service(":text 3 hello\n", "stale")
        baseline, base_states = self.run_service(":text 3 hello\n")
        self.assertIn("status=stale", wire)
        self.assertNotIn("T25 ERROR", wire)
        self.assertEqual(states, base_states)

    def test_integer_profile_above_double_exact_range_and_stage_sum(self):
        wire, _ = self.run_service(":ids 3 1 2 3 4 5\n", "integer-clock")
        def parse_groups(raw):
            groups = {}
            for line in raw.splitlines():
                match = re.match(r"T25 PROFILE 1 (\w+) session=[0-9a-f]{16} (.*)", line)
                if match:
                    groups[match[1]] = [(int(t, 16), int(c, 16)) for t, c in re.findall(r"ticks=([0-9a-f]{16}) calls=([0-9a-f]{16})", match[2])]
            return groups
        groups = parse_groups(wire)
        low_clock, _ = self.run_service(":ids 3 1 2 3 4 5\n")
        # Shifting only the absolute clock beyond binary64's exact integer
        # range must leave every measured one-cycle interval unchanged.
        self.assertEqual(groups, parse_groups(low_clock))
        self.assertEqual(set(groups), {"REQUEST", "PREFILL", "DECODE", "CUMULATIVE"})
        self.assertTrue(any(t > 0 for t, _ in groups["REQUEST"]))
        for index in range(8):
            for field in range(2):
                self.assertEqual(groups["REQUEST"][index][field], groups["PREFILL"][index][field] + groups["DECODE"][index][field])

    def test_timeout_configuration_is_explicit_and_bounded(self):
        wire, _ = self.run_service(":timeout 0\n:timeout 86401\n:timeout 600\n:ids 1 1\n")
        self.assertEqual(wire.count("T25 ERROR"), 2)
        request = next(self.fields(x) for x in wire.splitlines() if x.startswith("T25 REQUEST 1 "))
        self.assertEqual(request["timeout_ticks"], 600 * 125000000)

    def test_capture_rejects_uncomputed_ids_wrong_identity_and_failed_forward(self):
        wire, _ = self.run_service("", "capture-contract")
        self.assertIn("PREFIX_CAPTURE_CONTRACT_PASS", wire)

    def test_identity_is_read_only_and_prefix_survives_query(self):
        wire, _ = self.run_service(":text 1 alpha\n:identity\n:text 1 beta\n")
        self.assertEqual(wire.count("T25 MODEL "), 2)
        prefix = [self.fields(x) for x in wire.splitlines() if x.startswith("T25 PREFIX 1 ")]
        self.assertEqual([x["hit"] for x in prefix], [0, 1])

    def test_real_parser_accepts_enhanced_wire_all_chunk_splits(self):
        wire, _ = self.run_service(":text 2 hello\n:text 2 world\n")
        program = r'''
import fs from 'node:fs';import assert from 'node:assert/strict';import {pathToFileURL} from 'node:url';
const {T25Parser}=await import(pathToFileURL(process.argv[1]).href);const raw=Buffer.from(fs.readFileSync(0,'utf8'));
for(const n of [1,2,7,79,65536]){const events=[];const p=new T25Parser(e=>events.push(e));
for(let i=0;i<raw.length;i+=n)p.feed(raw.subarray(i,i+n));p.finish();const r=events.filter(e=>e.type==='result');
assert.equal(r.length,2);assert.ok(r.every(e=>e.complete));assert.equal(r[1].prefix.hit,1);assert.equal(r[1].profiles.REQUEST.length,8);}
'''
        run = subprocess.run(["node", "--input-type=module", "-e", program, str(ROOT / "software/demo_console/static/protocol.js")],
                             input=wire, capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
