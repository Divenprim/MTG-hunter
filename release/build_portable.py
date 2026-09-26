"""Build a self-contained Windows release.

Run on Windows with Python 3.12. The resulting directory contains its own
Python runtime and all application dependencies. The user does not install
Python or run pip.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY_DIRS = ("app", "web")
COPY_FILES = (
    "start.py", "build_db.py", "fetch_sets.py", "make_cert.py", "open_browser.py",
    "requirements.txt", "README.md", "LICENSE",
)

LAUNCHERS = {
    "MTG-Hunter.bat": (
        '@echo off\r\n'
        'setlocal\r\n'
        'cd /d "%~dp0"\r\n'
        'set "MTGH_PORTABLE=1"\r\n'
        '"runtime\\python.exe" "start.py" 127.0.0.1 8765\r\n'
        'if errorlevel 1 pause\r\n'
    ),
    "MTG-Hunter-LAN.bat": (
        '@echo off\r\n'
        'setlocal\r\n'
        'cd /d "%~dp0"\r\n'
        'set "MTGH_PORTABLE=1"\r\n'
        '"runtime\\python.exe" "start.py" 0.0.0.0 8765\r\n'
        'if errorlevel 1 pause\r\n'
    ),
    "MTG-Hunter-Tablet.bat": (
        '@echo off\r\n'
        'setlocal\r\n'
        'cd /d "%~dp0"\r\n'
        'set "MTGH_PORTABLE=1"\r\n'
        '"runtime\\python.exe" "start.py" 0.0.0.0 8765 ssl\r\n'
        'if errorlevel 1 pause\r\n'
    ),
}


def ignore_runtime(_path: str, names: list[str]) -> set[str]:
    skip = {"__pycache__"}
    skip.update(n for n in names if n.endswith(".pyc") or n.endswith(".pyo"))
    return skip


def copy_runtime(dst: Path) -> None:
    src = Path(sys.base_prefix)
    if sys.version_info[:2] != (3, 12) or sys.platform != "win32":
        raise SystemExit("portable release must be built on Windows with Python 3.12")
    shutil.copytree(src, dst, ignore=ignore_runtime)

    site = dst / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--disable-pip-version-check", "--no-warn-script-location",
            "--upgrade", "--target", str(site),
            "-r", str(ROOT / "requirements.txt"),
        ],
        check=True,
        cwd=ROOT,
    )


def build(out: Path) -> Path:
    package = out / "MTG-Hunter"
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)

    for name in COPY_DIRS:
        shutil.copytree(
            ROOT / name,
            package / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    for name in COPY_FILES:
        shutil.copy2(ROOT / name, package / name)

    data = package / "data"
    data.mkdir()
    shutil.copy2(ROOT / "data" / "sets.json", data / "sets.json")
    cards_db = ROOT / "data" / "cards.sqlite"
    if cards_db.exists():
        shutil.copy2(cards_db, data / "cards.sqlite")

    copy_runtime(package / "runtime")

    for name, body in LAUNCHERS.items():
        (package / name).write_bytes(body.encode("ascii"))

    for forbidden in (
        ".venv",
        "tests",
        ".git",
        "data/user.sqlite",
        "data/combos.sqlite",
    ):
        if (package / forbidden).exists():
            raise SystemExit("forbidden release content: " + forbidden)

    archive = shutil.make_archive(
        str(out / "MTG-Hunter-Windows-portable"),
        "zip",
        root_dir=out,
        base_dir="MTG-Hunter",
    )
    print(archive)
    return Path(archive)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist")
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    build(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
