# pqcrypto_layer.py - MOCK Post-Quantum Cryptography Layer

import os
import secrets
import logging
from typing import Dict, Tuple, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
import sys
import hashlib  # <--- USED FOR DETERMINISTIC KEY MOCK

# NOTE: Mocking qrng.py fallback for stability
try:
    # Attempt to import for use if available
    from .qrng import qrandom_key_bytes
except ImportError:
    # Fallback to os.urandom if qrng.py is not set up
    logging.warning("Falling back to os.urandom for key generation.")

    def qrandom_key_bytes(n):
        return os.urandom(n)


# --- Mock Constants (Simulating Real PQC Sizes) ---
KYBER_PK_SIZE = 800
KYBER_SK_SIZE = 1184
KYBER_CT_SIZE = 768
KYBER_SYM_KEY_SIZE = 32  # AES-256 Key Size
DILITHIUM_PK_SIZE = 1312
DILITHIUM_SK_SIZE = 2416
DILITHIUM_SIG_SIZE = 2420
AES_GCM_NONCE_SIZE = 12


# --- Kyber KEM Primitives (Mocking PQC Operations) ---
def kyber_generate_keypair() -> Tuple[bytes, bytes]:
    """Generates a mock Kyber key pair."""
    return qrandom_key_bytes(KYBER_PK_SIZE), qrandom_key_bytes(KYBER_SK_SIZE)


def kyber_encapsulate(public_key: bytes) -> Tuple[bytes, bytes]:
    """
    Mock Kyber encapsulation: Generates a ciphertext (KEM CT) and a shared secret key (K).
    AGENT SIDE FIX: Shared key is derived deterministically from the public key hash.
    """
    # MOCK FIX: Derive shared key deterministically from the public key hash
    shared_secret_key = hashlib.sha256(public_key).digest()[:KYBER_SYM_KEY_SIZE]

    # 2. Generate the ciphertext blob
    ciphertext_blob = qrandom_key_bytes(KYBER_CT_SIZE)

    # Debug print for agent side
    logging.info(
        f"[Encrypt] KEM shared secret (first 16 bytes): {shared_secret_key[:16].hex()}"
    )

    return ciphertext_blob, shared_secret_key


# --- Dilithium Signature Primitives (Mocking PQC Operations) ---
def dilithium_generate_keypair() -> Tuple[bytes, bytes]:
    """Generates a mock Dilithium key pair."""
    return qrandom_key_bytes(DILITHIUM_PK_SIZE), qrandom_key_bytes(DILITHIUM_SK_SIZE)


def dilithium_sign(secret_key: bytes, message: bytes) -> bytes:
    """Mock Dilithium signing operation."""
    return qrandom_key_bytes(DILITHIUM_SIG_SIZE)


def dilithium_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Mock Dilithium verification operation."""
    # Simulates verification: 99.9% success rate
    return secrets.randbelow(1000) != 0


# --- Composite PQC + Symmetric Encryption Wire Functions ---


def encrypt_payload_with_kem(
    server_pk: bytes, plaintext_bytes: bytes, aad: bytes = b""
) -> Dict[str, bytes]:
    """AGENT SIDE: Uses Kyber KEM and AES-256 GCM."""
    kem_ciphertext, shared_key = kyber_encapsulate(server_pk)
    aesgcm = AESGCM(shared_key)
    nonce = qrandom_key_bytes(AES_GCM_NONCE_SIZE)
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext_bytes, aad)

    return {
        "kem_ciphertext": kem_ciphertext,
        "aes_nonce": nonce,
        "encrypted_data_with_tag": ciphertext_with_tag,
    }


def decrypt_payload_with_kem(
    server_pk: bytes,
    server_sk: bytes,
    encrypted_blob: Dict[str, bytes],
    aad: bytes = b"",
) -> Optional[bytes]:
    """
    SERVER SIDE: Decapsulates Kyber, recovers shared secret, and decrypts the payload.
    NOTE: server_sk is included for consistency, but server_pk is used for key recovery mock.
    """
    try:
        # MOCK FIX: Recover the shared key using the server's PK (as the agent used the PK for encapsulation)
        shared_key_recovered = hashlib.sha256(server_pk).digest()[:KYBER_SYM_KEY_SIZE]

        aesgcm = AESGCM(shared_key_recovered)

        # Decrypt the combined ciphertext + tag
        plaintext_bytes = aesgcm.decrypt(
            encrypted_blob["aes_nonce"], encrypted_blob["encrypted_data_with_tag"], aad
        )
        return plaintext_bytes

    except InvalidTag:
        # CRITICAL DEBUG LINE: Catches AAD Mismatch or Wrong Key
        logging.error(
            "SERVER CRYPTO ERROR: AES-GCM authentication tag is invalid (AAD mismatch or wrong key/data)."
        )
        return None
    except Exception as e:
        logging.error(
            f"SERVER CRYPTO ERROR: Unexpected error in KEM/AES-GCM process: {e}"
        )
        return None


def sign_and_package_message(agent_sk: bytes, message: bytes) -> Dict[str, bytes]:
    """
    AGENT SIDE: Signs the raw message with Dilithium.
    Returns: {message (original bytes), signature}
    """
    signature = dilithium_sign(agent_sk, message)
    return {"message": message, "signature": signature}


def verify_packaged_message(
    agent_pk: bytes, package: Dict
) -> Tuple[Optional[bytes], bool]:
    """
    SERVER SIDE: Verifies the Dilithium signature on the message.
    """

    # The package signature is a hex string from the transmission format. Convert back to bytes.
    try:
        signature_bytes = bytes.fromhex(package["signature"])
    except ValueError:
        logging.error("Verification ERROR: Signature is not valid hex.")
        return None, False

    is_verified = dilithium_verify(
        agent_pk,
        package["message"],  # This is the raw message bytes recovered after decryption
        signature_bytes,
    )

    if is_verified:
        return package["message"], True
    else:
        # NOTE: Dilithium verify mock has a small chance of failing even with correct data.
        logging.warning("Verification ERROR: Dilithium verification failed.")
        return None, False
