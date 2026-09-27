"""End-to-end smoke test for the exact portable directory.

Runs on Windows CI after the release directory has been assembled. It checks
offline assets and actually starts both LAN HTTP and tablet HTTPS servers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REQUIRED = (
    "MTG-Hunter.bat",
    "MTG-Hunter-LAN.bat",
    "MTG-Hunter-Tablet.bat",
    "start.py",
    "netutil.py",
    "build_db.py",
    "build_art.py",
    "make_cert.py",
    "app/main.py",
    "app/cards.py",
    "app/artscan.py",
    "app/ocr.py",
    "web/index.html",
    "data/sets.json",
    "data/cards.sqlite",
    "data/combos.sqlite",
    "data/art_hashes.sqlite",
    "runtime/python.exe",
)


def opener(context: ssl.SSLContext | None = None) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers)


def get(url: str, context: ssl.SSLContext | None = None, timeout: float = 3.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mtg-hunter-release-smoke"})
    with opener(context).open(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError("%s -> HTTP %s" % (url, resp.status))
        return resp.read()


def wait_json(url: str, context: ssl.SSLContext | None = None) -> dict:
    last: Exception | None = None
    for _ in range(60):
        try:
            return json.loads(get(url, context=context, timeout=2.0))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.5)
    raise RuntimeError("server did not become ready at %s: %s" % (url, last))


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def lan_ips(package: Path, python: Path) -> list[str]:
    code = "import json; from netutil import lan_addresses; print(json.dumps(lan_addresses()))"
    raw = subprocess.check_output([str(python), "-c", code], cwd=package, text=True)
    return list(json.loads(raw.strip() or "[]"))


def verify_real_portable_prepare(package: Path, python: Path) -> None:
    env = os.environ.copy()
    env["MTGH_PORTABLE"] = "1"
    subprocess.run(
        [
            str(python),
            "-c",
            (
                "import start;"
                "assert start.PORTABLE;"
                "start.prepare();"
                "print('portable prepare passed')"
            ),
        ],
        cwd=package,
        env=env,
        check=True,
    )
    subprocess.run(
        [
            str(python),
            "-c",
            (
                "import start;"
                "assert start.PORTABLE;"
                "args=start.prepare_ssl();"
                "assert '--ssl-keyfile' in args and '--ssl-certfile' in args;"
                "print('portable ssl prepare passed')"
            ),
        ],
        cwd=package,
        env=env,
        check=True,
    )


def verify_databases(package: Path, python: Path) -> None:
    subprocess.run([str(python), "build_db.py", "--check"], cwd=package, check=True)
    subprocess.run(
        [
            str(python),
            "-c",
            "from app.combos import ComboDB; assert ComboDB().ready; print(ComboDB().status())",
        ],
        cwd=package,
        check=True,
    )
    subprocess.run(
        [
            str(python),
            "-c",
            (
                "from app.artscan import status,printings_to_hash;"
                "s=status();n=len(printings_to_hash('all'));"
                "print(s,'target',n);"
                "assert s['built'] and s.get('complete') and s['scope']=='all';"
                "assert s['hashed']>=int(n*0.995)"
            ),
        ],
        cwd=package,
        check=True,
    )


def run_http_smoke(package: Path, python: Path, ips: list[str]) -> None:
    port = "18765"
    env = os.environ.copy()
    env.update({"MTGH_HOST": "0.0.0.0", "MTGH_PORT": port, "MTGH_SCHEME": "http"})
    proc = subprocess.Popen(
        [str(python), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port],
        cwd=package,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        status = wait_json("http://127.0.0.1:%s/api/status" % port)
        assert status["db"]["built"]
        if ips:
            lan = wait_json("http://%s:%s/api/status" % (ips[0], port))
            assert lan["db"]["built"]
            assert lan["lan"]["open"]
    finally:
        stop(proc)


def run_https_smoke(package: Path, python: Path, ips: list[str]) -> None:
    subprocess.run([str(python), "make_cert.py", "--ensure"], cwd=package, check=True)
    ca = package / "data" / "cert" / "ca.pem"
    ca_hash = hashlib.sha256(ca.read_bytes()).hexdigest()
    # A second ensure must not replace the CA.
    subprocess.run([str(python), "make_cert.py", "--ensure"], cwd=package, check=True)
    assert hashlib.sha256(ca.read_bytes()).hexdigest() == ca_hash

    port = "18766"
    env = os.environ.copy()
    env.update({"MTGH_HOST": "0.0.0.0", "MTGH_PORT": port, "MTGH_SCHEME": "https"})
    proc = subprocess.Popen(
        [
            str(python), "-m", "uvicorn", "app.main:app",
            "--host", "0.0.0.0", "--port", port,
            "--ssl-keyfile", "data/cert/key.pem",
            "--ssl-certfile", "data/cert/cert.pem",
        ],
        cwd=package,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    context = ssl.create_default_context(cafile=str(ca))
    try:
        local = wait_json("https://127.0.0.1:%s/api/status" % port, context=context)
        assert local["db"]["built"]
        if ips:
            lan = wait_json("https://%s:%s/api/status" % (ips[0], port), context=context)
            assert lan["db"]["built"]
    finally:
        stop(proc)


def run_ca_page_smoke(package: Path, python: Path) -> None:
    port = "18767"
    code = "from app.main import _serve_ca; _serve_ca(%s)" % port
    proc = subprocess.Popen(
        [str(python), "-c", code],
        cwd=package,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        last: Exception | None = None
        for _ in range(30):
            try:
                page = get("http://127.0.0.1:%s/" % port)
                cert = get("http://127.0.0.1:%s/ca.pem" % port)
                assert b"MTG Hunter" in page
                assert b"BEGIN CERTIFICATE" in cert
                return
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(0.3)
        raise RuntimeError("CA setup page did not start: %s" % last)
    finally:
        stop(proc)


def run(package: Path) -> None:
    missing = [name for name in REQUIRED if not (package / name).exists()]
    if missing:
        raise SystemExit("missing required portable content: " + ", ".join(missing))

    python = package / "runtime" / "python.exe"
    subprocess.run(
        [str(python), "-m", "compileall", "-q", "app", "start.py", "make_cert.py", "netutil.py"],
        cwd=package,
        check=True,
    )
    verify_databases(package, python)
    verify_real_portable_prepare(package, python)
    ips = lan_ips(package, python)
    print("LAN addresses:", ips)
    run_http_smoke(package, python, ips)
    run_https_smoke(package, python, ips)
    run_ca_page_smoke(package, python)
    print("portable end-to-end smoke passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    args = parser.parse_args()
    run(Path(args.package).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
