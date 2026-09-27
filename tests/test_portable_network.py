from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import make_cert
import start


class CertificateLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old = (
            make_cert.CERT_DIR,
            make_cert.CA_CERT,
            make_cert.CA_KEY,
            make_cert.SERVER_CERT,
            make_cert.SERVER_KEY,
        )
        make_cert.CERT_DIR = root
        make_cert.CA_CERT = root / "ca.pem"
        make_cert.CA_KEY = root / "ca-key.pem"
        make_cert.SERVER_CERT = root / "cert.pem"
        make_cert.SERVER_KEY = root / "key.pem"

    def tearDown(self) -> None:
        (
            make_cert.CERT_DIR,
            make_cert.CA_CERT,
            make_cert.CA_KEY,
            make_cert.SERVER_CERT,
            make_cert.SERVER_KEY,
        ) = self.old
        self.tmp.cleanup()

    def test_dhcp_change_reissues_server_cert_but_keeps_ca(self) -> None:
        with patch("make_cert.lan_addresses", return_value=["192.168.10.20"]):
            first = make_cert.ensure()
        ca_hash = hashlib.sha256(make_cert.CA_CERT.read_bytes()).hexdigest()
        first_server = make_cert.SERVER_CERT.read_bytes()

        with patch("make_cert.lan_addresses", return_value=["192.168.10.99"]):
            second = make_cert.ensure()

        self.assertEqual(ca_hash, hashlib.sha256(make_cert.CA_CERT.read_bytes()).hexdigest())
        self.assertNotEqual(first_server, make_cert.SERVER_CERT.read_bytes())
        self.assertTrue(second["server_renewed"])
        self.assertFalse(second["ca_replaced"])

        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID

        cert = x509.load_pem_x509_certificate(make_cert.SERVER_CERT.read_bytes())
        san = cert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        ).value
        ips = {str(v) for v in san.get_values_for_type(x509.IPAddress)}
        self.assertIn("192.168.10.99", ips)
        self.assertIn("127.0.0.1", ips)


class FirewallTests(unittest.TestCase):
    def test_rule_is_local_subnet_only(self) -> None:
        result = Mock(returncode=0)
        with (
            patch.object(start.sys, "platform", "win32"),
            patch("start._firewall_rule_exists", side_effect=[False, True]),
            patch("start.subprocess.run", return_value=result) as run,
        ):
            self.assertTrue(start._add_firewall_rule("MTG Hunter LAN", "8765"))

        command = " ".join(str(x) for x in run.call_args.args[0])
        self.assertIn("remoteip=localsubnet", command)
        self.assertIn("localport=8765", command)
        self.assertIn("RunAs", command)


if __name__ == "__main__":
    unittest.main()
