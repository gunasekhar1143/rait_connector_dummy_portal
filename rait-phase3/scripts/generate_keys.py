#!/usr/bin/env python3
"""Generate RSA-2048 key pair to keys/rsa_private.pem and keys/rsa_public.pem."""
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_DIR = Path(__file__).parent.parent / "keys"


def generate_keys() -> None:
    KEY_DIR.mkdir(exist_ok=True)
    private_path = KEY_DIR / "rsa_private.pem"
    public_path = KEY_DIR / "rsa_public.pem"

    if private_path.exists():
        print(f"Keys already exist at {KEY_DIR}/. Delete them to regenerate.")
        return

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    os.chmod(private_path, 0o600)
    print(f"Generated RSA-2048 key pair in {KEY_DIR}/")
    print(f"  Private: {private_path}")
    print(f"  Public:  {public_path}")


if __name__ == "__main__":
    generate_keys()
