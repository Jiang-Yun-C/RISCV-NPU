"""End-to-end T01 acceptance: two fresh builds plus intentional failure runs."""
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from evidence import EvidenceRun, StepFailure, content_id, sha256, write_json
from run_smoke import input_files


def main():
    run = EvidenceRun(ROOT, "T01")
    files = input_files()
    config = json.loads((ROOT / "configs/t01-smoke.json").read_text())
    write_json(run.path / "config.json", config)
    run.manifest.update(test_mode="T01_ACCEPTANCE_DRIVER", seed=config["seed"],
                        source={"sha256": content_id(files), "files": files},
                        config={"sha256": sha256(run.path / "config.json")},
                        checker={"sha256": sha256(Path(__file__))},
                        firmware={"sha256": None, "execution": "NOT_TESTED_T03"}, model=config["model"],
                        invocation=[sys.executable, *sys.argv],
                        qualification={"cpu_firmware_execution": "NOT_TESTED_T03", "pds": "NOT_VALIDATED_NOT_REQUIRED"})
    print(f"T01 acceptance evidence: {run.path}", flush=True)
    code = 1
    try:
        successes = []
        for label in ("a", "b"):
            # The driver must stay outside build/, which clean deliberately deletes.
            run.execute("clean-" + label, [sys.executable, ROOT / "scripts/run_smoke.py", "--clean"], 30, cwd=ROOT)
            previous = set((ROOT / "evidence/T01").glob("*/manifest.json"))
            run.execute("smoke-" + label, ["make", "smoke"], 300, cwd=ROOT)
            created = set((ROOT / "evidence/T01").glob("*/manifest.json")) - previous
            run.check("fresh-result-" + label, len(created) == 1, sorted(str(p) for p in created))
            path = created.pop()
            manifest = json.loads(path.read_text())
            run.check("success-" + label, manifest["status"] == "PASS" and manifest["exit_code"] == 0, str(path))
            run.check("artifact-integrity-" + label,
                      all(sha256(path.parent / f) == digest for f, digest in manifest["artifacts"].items()), str(path))
            successes.append((path, manifest))
        a, b = [manifest for _, manifest in successes]
        run.check("same-inputs", all(a[key]["sha256"] == b[key]["sha256"] for key in ("source", "config", "checker")),
                  "Two invocations of make smoke after make clean")
        run.check("same-firmware", a["firmware"]["sha256"] == b["firmware"]["sha256"],
                  [a["firmware"]["sha256"], b["firmware"]["sha256"]])
        run.check("same-host-result", a["artifacts"]["artifacts/host-result.json"] == b["artifacts"]["artifacts/host-result.json"],
                  "Deterministic C/NumPy input and output")
        run.manifest["successful_runs"] = [str(p.parent.relative_to(ROOT)) for p, _ in successes]
        run.manifest["firmware"] = b["firmware"] | {"from_run": str(successes[-1][0].parent.relative_to(ROOT))}

        wrapper = ("import subprocess,sys; r=subprocess.run(sys.argv[2:]); "
                   "print('observed_exit='+str(r.returncode)); "
                   "sys.exit(0 if r.returncode==int(sys.argv[1]) else 1)")
        failures = []
        for label, overrides, expected in (
            ("invalid-config", {"seed": -1}, 1),
            ("compile-timeout", {"timeouts_seconds": {"probe": 30, "compile": 0.001, "run": 30, "check": 30}}, 124),
        ):
            test_config = config | overrides
            config_path = run.path / (label + ".json")
            write_json(config_path, test_config)
            run_id = run.run_id + "-" + label
            command = [sys.executable, ROOT / "scripts/run_smoke.py", "--config", config_path, "--run-id", run_id]
            run.execute(label, [sys.executable, "-c", wrapper, str(expected), *command], 90, cwd=ROOT)
            path = ROOT / "evidence/T01" / run_id
            manifest = json.loads((path / "manifest.json").read_text())
            run.check(label + "-evidence", manifest["status"] == "FAIL" and manifest["exit_code"] == expected
                      and (path / "failure.txt").is_file()
                      and all(key in manifest for key in ("source", "config", "firmware", "model", "checker", "seed")), str(path))
            if label == "compile-timeout":
                run.check("timeout-log-preserved", "TIMEOUT" in (path / "logs/host-build.stderr.log").read_text(), str(path))
            failures.append({"path": str(path.relative_to(ROOT)), "expected_exit_code": expected})
        run.manifest["expected_failure_runs"] = failures
        # Checkers must reject corrupted copies of real successful products.
        good = successes[-1][0].parent / "artifacts"
        bad_elf = bytearray((good / "smoke.elf").read_bytes())
        bad_elf[18:20] = b"\x03\x00"  # EM_386 instead of EM_RISCV
        (run.path / "bad-machine.elf").write_bytes(bad_elf)
        vcd = (good / "smoke.vcd").read_text()
        (run.path / "truncated.vcd").write_text(vcd.split("#95000")[0])
        for kind, path in (("elf", run.path / "bad-machine.elf"), ("vcd", run.path / "truncated.vcd")):
            command = [sys.executable, ROOT / "tests/smoke/check_smoke.py", kind, path]
            run.execute("reject-bad-" + kind, [sys.executable, "-c", wrapper, "1", *command], 30, cwd=ROOT)
        run.check("source-unchanged", input_files() == files, "Acceptance did not modify source inputs")
        code = 0
    except StepFailure as error:
        code = error.exit_code
        (run.path / "failure.txt").write_text(str(error) + "\n")
    except KeyboardInterrupt:
        code = 130
        (run.path / "failure.txt").write_text("Interrupted\n")
    except Exception:
        (run.path / "failure.txt").write_text(traceback.format_exc())
        run.checks.append({"name": "driver-exception", "status": "FAIL", "detail": "See failure.txt"})
    finally:
        code = run.finish(code)
    print(f"T01 acceptance {run.manifest['status']}: {run.path}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
