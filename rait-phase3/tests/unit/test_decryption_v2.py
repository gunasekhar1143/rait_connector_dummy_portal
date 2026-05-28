"""Tests for DecryptionEngine: v1 and v2 roundtrips using actual rait_connector Encryptor."""
import base64
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

# Ensure rait_connector is importable from the venv
_VENV = Path(__file__).parent.parent.parent.parent / "venv" / "Lib" / "site-packages"
if str(_VENV) not in sys.path:
    sys.path.insert(0, str(_VENV))

from rait_connector.encryption import Encryptor

from dummy_portal.decryption import DecryptionEngine, DecryptionError
from rait_connector_patches.encryptor_v2 import EncryptorV2


PLAINTEXT = b"hello Phase 3 portal"


def _make_encryptor(public_pem: bytes) -> Encryptor:
    return Encryptor(public_key=public_pem)


def _make_engine(private_key) -> DecryptionEngine:
    return DecryptionEngine(private_key)


class TestV1Roundtrip:
    def test_basic_roundtrip(self, rsa_key_pair):
        enc = _make_encryptor(rsa_key_pair["public_pem"])
        engine = _make_engine(rsa_key_pair["private_key"])

        encrypted_bytes = enc.encrypt(PLAINTEXT)
        b64 = base64.b64encode(encrypted_bytes).decode()

        result = engine.decrypt(b64)
        assert result == PLAINTEXT

    def test_first_byte_is_not_version(self, rsa_key_pair):
        enc = _make_encryptor(rsa_key_pair["public_pem"])
        encrypted_bytes = enc.encrypt(PLAINTEXT)
        # v1 payload must NOT start with 0x02
        assert encrypted_bytes[0] != 0x02


class TestV2Roundtrip:
    def test_v2_roundtrip(self, rsa_key_pair):
        enc = EncryptorV2(public_key=rsa_key_pair["public_pem"])
        engine = _make_engine(rsa_key_pair["private_key"])

        encrypted_bytes = enc.encrypt(PLAINTEXT)
        assert encrypted_bytes[0] == 0x02, "v2 payload must start with 0x02"

        b64 = base64.b64encode(encrypted_bytes).decode()
        result = engine.decrypt(b64)
        assert result == PLAINTEXT

    def test_v2_version_byte_stripped(self, rsa_key_pair):
        enc = EncryptorV2(public_key=rsa_key_pair["public_pem"])
        engine = _make_engine(rsa_key_pair["private_key"])

        encrypted_bytes = enc.encrypt(b"test data")
        b64 = base64.b64encode(encrypted_bytes).decode()
        result = engine.decrypt(b64)
        assert result == b"test data"


class TestDecryptionErrors:
    def test_invalid_base64_raises(self, rsa_key_pair):
        engine = _make_engine(rsa_key_pair["private_key"])
        with pytest.raises(DecryptionError, match="Base64 decode failed"):
            engine.decrypt("!!!not-valid-base64!!!")

    def test_truncated_payload_raises(self, rsa_key_pair):
        engine = _make_engine(rsa_key_pair["private_key"])
        with pytest.raises(DecryptionError):
            engine.decrypt(base64.b64encode(b"\x01\x02").decode())

    def test_wrong_key_raises(self, rsa_key_pair):
        from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
        other_key = _rsa.generate_private_key(public_exponent=65537, key_size=2048)

        enc = _make_encryptor(rsa_key_pair["public_pem"])
        engine = DecryptionEngine(other_key)  # wrong private key

        b64 = base64.b64encode(enc.encrypt(PLAINTEXT)).decode()
        with pytest.raises(DecryptionError):
            engine.decrypt(b64)
