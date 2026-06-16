"""Shared cryptographic helpers for the src/ service layer.

Single implementation of the v2 wire-format encryption used by all three
services (evaluation, telemetry, calibration). Previously copy-pasted into
each service module — this is the canonical version.

Wire format (v2):
  [1B = 0x02][4B key_len LE][RSA-encrypted AES key][12B nonce][16B GCM tag][ciphertext]

This is byte-for-byte identical to EncryptorV2 in rait_connector_patches/,
and is decoded by dummy_portal/decryption.py's DecryptionEngine.
"""
import base64
import os
import struct
import uuid as _uuid_mod
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import quote

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    from ..config import Settings


def encrypt_v2(public_key_pem: str, plaintext: bytes) -> str:
    """Encrypt plaintext with RSA-OAEP + AES-256-GCM, v2 wire format.

    Returns a base64-encoded string ready to use as IngestPayload.model_data_logs.
    """
    public_key = serialization.load_pem_public_key(public_key_pem.encode())

    aes_key = os.urandom(32)
    enc_aes_key = public_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    nonce = os.urandom(12)
    ct_with_tag = AESGCM(aes_key).encrypt(nonce, plaintext, None)
    tag = ct_with_tag[-16:]
    ciphertext = ct_with_tag[:-16]

    raw = (
        b"\x02"
        + struct.pack("<I", len(enc_aes_key))
        + enc_aes_key
        + nonce
        + tag
        + ciphertext
    )
    return base64.b64encode(raw).decode()


def build_ingest_key(
    client_id: str,
    model_name: str,
    model_version: str,
    environment: str,
) -> str:
    """Build a unique URL-safe ingest key matching the legacy rait_connector format.

    Format: {client_id}/{url_encoded_model_code}/{datetime_str}/{uuid}
    Matches rait_connector.client.RAITClient._build_key() exactly.
    """
    model_code = quote(f"{model_name} {model_version} ({environment})", safe="")
    dt = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{client_id}/{model_code}/{dt}/{_uuid_mod.uuid4()}"


def build_ingest_payload(
    config: "Settings",
    encrypted: str,
    ts: str,
    log_type: str,
) -> dict:
    """Build the IngestPayload dict accepted by PUT /v1/{key}.

    Args:
        config:    Settings instance providing model identity fields.
        encrypted: Base64-encoded encrypted model_data_logs string.
        ts:        ISO-8601 timestamp string for log_generated_at.
        log_type:  One of "evaluation", "telemetry", "calibration".
    """
    return {
        "model_name": config.model_name,
        "model_version": config.model_version,
        "model_environment": config.model_environment,
        "model_purpose": config.model_purpose,
        "log_generated_at": ts,
        "model_data_logs": encrypted,
        "connector_logs": "",
        "log_type": log_type,
    }
