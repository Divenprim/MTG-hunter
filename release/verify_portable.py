"""Verify the exact portable directory before it is published."""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def run(package: Path) -> None:
    for name in ("MTG-Hunter.bat", "MTG-Hunter-LAN.bat", "MTG-Hunter-Tablet.bat"):
        launcher = package / name
        if not launcher.exists():
            raise SystemExit("launcher is missing: " + name)
        raw = launcher.read_bytes()
        if any(b > 127 for b in raw):
            raise SystemExit(name + " is not ASCII")
        if raw.count(b"\n") != raw.count(b"\r\n"):
            raise SystemExit(name + " does not use CRLF")

    python = package / "runtime" / "python.exe"
    if not python.exists():
        raise SystemExit("embedded Python is missing")

    env = os.environ.copy()
    env["MTGH_PORTABLE"] = "1"
    checks = [
        "import fastapi, uvicorn, requests, pydantic, PIL, numpy, cv2, cryptography",
        "import start; assert start.PORTABLE; assert start.RUNTIME_PY == __import__('sys').executable",
        "import app.main",
    ]
    for code in checks:
        subprocess.run([str(python), "-c", code], cwd=package, env=env, check=True)

    forbidden = [
        package / ".venv",
        package / "tests",
        package / "data" / "user.sqlite",
        package / "data" / "cards.sqlite",
    ]
    bad = [str(p) for p in forbidden if p.exists()]
    if bad:
        raise SystemExit("forbidden release content: " + ", ".join(bad))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    args = parser.parse_args()
    run(Path(args.package).resolve())
    print("portable release verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
