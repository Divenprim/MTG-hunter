"""Create and maintain the local HTTPS certificate used by phone/tablet mode.

The local CA is persistent. If the PC gets a new LAN address, only the server
certificate is re-issued; the phone does not need a new CA every DHCP change.
"""
from __future__ import annotations

import argparse
import datetime
import ipaddress
import os
import socket
from pathlib import Path

from netutil import lan_addresses

ROOT = Path(__file__).resolve().parent
CERT_DIR = ROOT / "data" / "cert"
CA_CERT = CERT_DIR / "ca.pem"
CA_KEY = CERT_DIR / "ca-key.pem"
SERVER_CERT = CERT_DIR / "cert.pem"
SERVER_KEY = CERT_DIR / "key.pem"


def _new_ca():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "MTG Hunter local CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MTG Hunter"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _write_ca(key, cert) -> None:
    from cryptography.hazmat.primitives import serialization

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    CA_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    CA_KEY.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )


def _load_or_create_ca():
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    if CA_CERT.exists() and CA_KEY.exists():
        try:
            cert = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
            key = serialization.load_pem_private_key(CA_KEY.read_bytes(), password=None)
            return key, cert, False
        except Exception:
            pass

    # Old MTG Hunter releases wrote ca.pem but did not save its private key.
    # Such a CA cannot sign a certificate for a new DHCP address, so replace it
    # once with a persistent CA. This is the only migration that requires the
    # phone to trust the new CA again.
    key, cert = _new_ca()
    _write_ca(key, cert)
    return key, cert, True


def _wanted_names() -> tuple[list[str], list[str]]:
    ips = lan_addresses() or ["127.0.0.1"]
    dns = ["localhost", socket.gethostname()]
    return ips, list(dict.fromkeys(dns))


def _server_cert_is_current(ips: list[str], dns: list[str]) -> bool:
    from cryptography import x509
    from cryptography.x509.oid import ExtensionOID

    if not SERVER_CERT.exists() or not SERVER_KEY.exists():
        return False
    try:
        cert = x509.load_pem_x509_certificate(SERVER_CERT.read_bytes())
        now = datetime.datetime.now(datetime.timezone.utc)
        expiry = cert.not_valid_after_utc
        if expiry <= now + datetime.timedelta(days=14):
            return False
        san = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        ).value
        have_ips = {str(v) for v in san.get_values_for_type(x509.IPAddress)}
        have_dns = set(san.get_values_for_type(x509.DNSName))
        return set(ips + ["127.0.0.1"]).issubset(have_ips) and set(dns).issubset(have_dns)
    except Exception:
        return False


def _issue_server(ca_key, ca_cert, ips: list[str], dns: list[str], days: int = 365) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    names: list[x509.GeneralName] = [x509.DNSName(name) for name in dns]
    for ip in list(dict.fromkeys(ips + ["127.0.0.1"])):
        names.append(x509.IPAddress(ipaddress.ip_address(ip)))

    cert = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, ips[0] if ips else "localhost")
            ])
        )
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    SERVER_CERT.write_bytes(
        cert.public_bytes(serialization.Encoding.PEM)
        + ca_cert.public_bytes(serialization.Encoding.PEM)
    )
    SERVER_KEY.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )


def ensure() -> dict[str, object]:
    ca_key, ca_cert, ca_replaced = _load_or_create_ca()
    ips, dns = _wanted_names()
    renewed = not _server_cert_is_current(ips, dns)
    if renewed:
        _issue_server(ca_key, ca_cert, ips, dns)
    return {
        "ca": str(CA_CERT),
        "cert": str(SERVER_CERT),
        "key": str(SERVER_KEY),
        "ips": ips,
        "dns": dns,
        "server_renewed": renewed,
        "ca_replaced": ca_replaced,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ensure", action="store_true")
    args = parser.parse_args()

    try:
        import cryptography  # noqa: F401
    except ImportError:
        print("Не хватает cryptography.")
        return 1

    made = ensure()
    ips = made["ips"]
    print("HTTPS готов.")
    print("Адреса: " + ", ".join(str(x) for x in ips))
    if made["ca_replaced"]:
        print("Локальный CA создан заново; на телефоне его нужно доверить один раз.")
    if ips:
        print("CA: http://%s:8766/ca.pem" % ips[0])
        print("Приложение: https://%s:8765" % ips[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
