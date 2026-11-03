"""Build on Windows in a dedicated build environment; does not access hardware."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--work", type=Path, default=ROOT / "build")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Build the Windows EXE with Windows Python, not Linux PyInstaller.")
    args.work.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--noupx", "--name", "NexusRV-Assistant-v5",
        "--icon", str(ROOT / "desktop-icon.ico"),
        "--distpath", str(args.output), "--workpath", str(args.work / "pyinstaller"),
        "--specpath", str(args.work),
        "--add-data", str(ROOT / "static") + ":static",
        "--add-data", str(ROOT / "BUNDLE.json") + ":.",
        "--add-data", str(ROOT / "desktop-icon.png") + ":.",
        "--add-data", str(ROOT / "tool_packages") + ":tool_packages",
        "--add-data", str(ROOT / "twinkle_plan.py") + ":.",
        "--hidden-import", "serial", "--hidden-import", "serial.tools.list_ports",
        "--hidden-import", "serial.tools.list_ports_windows", str(ROOT / "desktop.py")],
        cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
