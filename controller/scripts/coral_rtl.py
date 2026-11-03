"""Apply reviewed fixes to fresh Coral RTL imports, with exact source identities."""
import json
from pathlib import Path
import shutil

from evidence import sha256, write_json

ROOT = Path(__file__).resolve().parents[1]
PATCH_DIR = ROOT / "rtl/coral/patches"


def input_paths():
    return ["scripts/coral_rtl.py", "rtl/coral/patches/manifest.json",
            "rtl/coral/patches/static-validation.patch"]


def apply_patches(run, rtl):
    """Never patch the locked checkout or an archived accepted result in place."""
    rtl = Path(rtl).resolve()
    if not rtl.is_relative_to(run.build.resolve()):
        raise ValueError("Coral fixes require a fresh directory inside this run's build")
    spec = json.loads((PATCH_DIR / "manifest.json").read_text())
    # Validate all inputs before changing anything. A new upstream needs review.
    for name, identity in spec["files"].items():
        if not (rtl / name).is_file() or sha256(rtl / name) != identity["before_sha256"]:
            raise ValueError("Coral patch input identity differs: " + name)
    run.execute("coral-patch-" + rtl.name,
                ["patch", "--batch", "--fuzz=0", "-p1", "--input", PATCH_DIR / spec["patch"]],
                30, cwd=rtl)
    archive = run.path / "artifacts/coral-patches" / rtl.name
    archive.mkdir(parents=True)
    for name, identity in spec["files"].items():
        if sha256(rtl / name) != identity["after_sha256"]:
            raise ValueError("Coral patch output identity differs: " + name)
        shutil.copy2(rtl / name, archive / name)
    receipt = dict(files=spec["files"], patch_sha256=sha256(PATCH_DIR / spec["patch"]),
                   upstream_commit=spec["upstream_commit"], input_zip_unchanged=True)
    write_json(archive / "receipt.json", receipt)
    run.manifest.setdefault("coral_rtl_patches", {})[rtl.name] = receipt
    run.flush()
