"""Сделать сертификат, чтобы страница открывалась по https с планшета.

Зачем это вообще нужно. Камеру браузер даёт только на защищённом соединении:
по адресу http://192.168.1.50:8765 ни Safari, ни Chrome не покажут ни одного
кадра — и никак это не обойти, это правило самого браузера, а не настройка.
Поэтому для сканера с планшета нужен https, а значит сертификат.

Сертификат делается свой, на этом компьютере, и никуда не отправляется. Их
здесь два:

  * ca.pem   -- корневой, его один раз ставят на планшет;
  * cert.pem + key.pem -- для самого сервера, на адреса этого компьютера.

    .venv/Scripts/python.exe make_cert.py

Перевыпускать надо, если компьютер сменил адрес в сети (или раз в год).
"""

import datetime
import ipaddress
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CERT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cert")


def _addresses() -> list[str]:
    from app.main import lan_addresses          # noqa: PLC0415
    found = lan_addresses()
    return found or ["127.0.0.1"]


def build(days: int = 825) -> dict[str, str]:
    """Корневой сертификат и серверный на все адреса этой машины."""
    from cryptography import x509                            # noqa: PLC0415
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    os.makedirs(CERT_DIR, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    host = socket.gethostname()
    ips = _addresses()

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "MTG Hunter local CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MTG Hunter"),
    ])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days * 2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True,
            crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    names: list[x509.GeneralName] = [x509.DNSName("localhost"), x509.DNSName(host)]
    for ip in ips + ["127.0.0.1"]:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, ips[0]),
        ]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        # Safari не доверяет сертификатам длиннее 825 дней, каким бы своим он
        # ни был: срок здесь не формальность.
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([
            x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    paths = {
        "ca": os.path.join(CERT_DIR, "ca.pem"),
        "cert": os.path.join(CERT_DIR, "cert.pem"),
        "key": os.path.join(CERT_DIR, "key.pem"),
    }
    with open(paths["ca"], "wb") as fh:
        fh.write(ca.public_bytes(serialization.Encoding.PEM))
    with open(paths["cert"], "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))
        fh.write(ca.public_bytes(serialization.Encoding.PEM))
    with open(paths["key"], "wb") as fh:
        fh.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()))
    paths["ips"] = ", ".join(ips)
    return paths


if __name__ == "__main__":
    try:
        import cryptography                               # noqa: F401
    except ImportError:
        print("Не хватает библиотеки: .venv/Scripts/python.exe -m pip install cryptography")
        raise SystemExit(1)

    made = build()
    ips = made["ips"].split(", ")
    print("Сертификаты готовы:")
    print("  " + made["ca"])
    print("  " + made["cert"])
    print()
    print("Дальше на планшете, один раз:")
    print("  1. Откройте http://%s:8766/ca.pem — файл скачается." % ips[0])
    print("     (этот адрес поднимает run-ssl.bat рядом с основным)")
    print("  2. Настройки → Профиль загружен → Установить.")
    print("  3. Настройки → Основные → Об этом устройстве → Доверие сертификатам")
    print("     → включите «MTG Hunter local CA».")
    print("  4. Откройте https://%s:8765 — камера заработает." % ips[0])
