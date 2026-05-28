"""Shared fixtures for all test tiers."""
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# Make sure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def rsa_key_pair():
    """Generate a fresh RSA key pair for tests."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return {"private_pem": private_pem, "public_pem": public_pem, "private_key": private_key}


@pytest.fixture
def tmp_key_dir(tmp_path, rsa_key_pair):
    """Write test key pair to a temp directory and return the dir path."""
    (tmp_path / "rsa_private.pem").write_bytes(rsa_key_pair["private_pem"])
    (tmp_path / "rsa_public.pem").write_bytes(rsa_key_pair["public_pem"])
    return tmp_path


@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "test_portal.db")
