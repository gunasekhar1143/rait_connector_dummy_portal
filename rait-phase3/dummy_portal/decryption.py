"""DecryptionEngine for RSA-OAEP + AES-256-GCM payloads.

Wire format (confirmed from rait_connector/encryption.py source):
  v1: [4B key_len little-endian][encrypted_AES_key][12B nonce][16B GCM tag][ciphertext]
  v2: [1B = 0x02][4B key_len little-endian][encrypted_AES_key][12B nonce][16B GCM tag][ciphertext]

Both formats are base64-encoded before transmission.
"""
import base64
import struct
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class DecryptionError(Exception):
    pass


class DecryptionEngine:
    def __init__(self, private_key) -> None:
        self._private_key = private_key

    @classmethod
    def from_pem_path(cls, path: str) -> "DecryptionEngine":
        pem = Path(path).read_bytes()
        private_key = serialization.load_pem_private_key(pem, password=None)
        if private_key.key_size < 2048:
            raise DecryptionError(f"RSA key size {private_key.key_size} < 2048 bits")
        return cls(private_key)

    def decrypt(self, b64_payload: str) -> bytes:
        try:
            raw = base64.b64decode(b64_payload)
        except Exception as exc:
            raise DecryptionError(f"Base64 decode failed: {exc}") from exc

        if len(raw) < 5:
            raise DecryptionError("Payload too short to be valid")

        if raw[0] == 0x02:
            return self._decrypt_package(raw[1:], version="v2")
        # v1: no version prefix. First byte is low byte of key_len LE uint32.
        # RSA-2048 produces a 256-byte encrypted key, so key_len=256=0x100,
        # first byte is always 0x00 — unambiguous, cannot collide with 0x02.
        return self._decrypt_package(raw, version="v1")

    def _decrypt_package(self, data: bytes, version: str) -> bytes:
        if len(data) < 4:
            raise DecryptionError(f"[{version}] Package too short for key_len field")

        # key_len is little-endian uint32 (confirmed: struct.pack("<I", ...))
        (key_len,) = struct.unpack_from("<I", data, 0)
        offset = 4

        if len(data) < offset + key_len + 12 + 16:
            raise DecryptionError(
                f"[{version}] Package length {len(data)} too short for "
                f"key_len={key_len} + 12B nonce + 16B tag"
            )

        enc_aes_key = data[offset : offset + key_len]
        offset += key_len
        nonce      = data[offset : offset + 12]
        offset += 12
        tag        = data[offset : offset + 16]
        offset += 16
        ciphertext = data[offset:]

        try:
            aes_key = self._private_key.decrypt(
                enc_aes_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
        except Exception as exc:
            raise DecryptionError(f"[{version}] RSA-OAEP decrypt failed: {exc}") from exc

        try:
            # AES-GCM: tag is appended to ciphertext for AESGCM.decrypt()
            plaintext = AESGCM(aes_key).decrypt(nonce, ciphertext + tag, None)
        except Exception as exc:
            raise DecryptionError(f"[{version}] AES-GCM decrypt/auth failed: {exc}") from exc

        return plaintext
