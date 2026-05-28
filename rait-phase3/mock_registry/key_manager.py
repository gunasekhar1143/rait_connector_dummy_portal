"""RSA key pair generation and loading for Mock Registry."""
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class KeyManager:
    def __init__(self, key_dir: str) -> None:
        self._dir = Path(key_dir)
        self._private_path = self._dir / "rsa_private.pem"
        self._public_path = self._dir / "rsa_public.pem"

    def ensure_keys_exist(self) -> None:
        if self._private_path.exists():
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._private_path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        self._public_path.write_bytes(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    def get_public_key_pem(self) -> str:
        return self._public_path.read_text()
