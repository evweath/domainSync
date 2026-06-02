#!/usr/bin/env python3
"""
Generate self-signed TLS certificates for localhost.
Cross-platform replacement for the openssl CLI call in setup_macos.sh.
Usage: python generate_certs.py
"""
import datetime
import ipaddress
from pathlib import Path

ROOT = Path(__file__).parent
CERT = ROOT / 'certs' / 'cert.pem'
KEY = ROOT / 'certs' / 'key.pem'


def generate() -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.datetime.now(datetime.timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName('localhost'),
                x509.IPAddress(ipaddress.IPv4Address('127.0.0.1')),
            ]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    CERT.parent.mkdir(parents=True, exist_ok=True)
    KEY.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f'Certificates written to {CERT.parent}/')


if __name__ == '__main__':
    generate()
