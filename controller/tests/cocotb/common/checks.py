import hashlib
import json
from collections import Counter
from pathlib import Path


class Checks:
    def __init__(self):
        self.counts = Counter()
        self.first_failure = None

    def require(self, condition, category, detail):
        self.counts[category] += 1
        if not condition:
            self.first_failure = {"category": category, "detail": detail}
            raise AssertionError(f"{category}: {detail}")

    def equal(self, actual, expected, category, detail):
        self.require(actual == expected, category, {"item": detail, "actual": actual, "expected": expected})

    def save(self, path, **metadata):
        Path(path).write_text(json.dumps({"schema_version": 1, "status": "FAIL" if self.first_failure else "PASS",
            "check_count": sum(self.counts.values()), "categories": dict(self.counts),
            "first_failure": self.first_failure, **metadata}, indent=2)+"\n")


def digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
