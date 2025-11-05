import oqs
import os
import logging
from typing import Dict, Tuple, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag


def qrandom_key_bytes(n_bytes: int) -> bytes:
    """
    Returns cryptographically secure random bytes.
    [This is a production-ready replacement for the qrng.py logic]
    """
    return os.urandom(n_bytes)


# --- PQC Algorithm Definitions ---
# Using NIST standardized algorithms
KYBER_ALG = "Kyber-768"
DILITHIUM_ALG = "Dilithium-3"

# --- Constants (Real Sizes) ---
AES_GCM_NONCE_SIZE = 12
AES_GCM_KEY_SIZE = 32  # Kyber-768 provides a 32-byte (256-bit) shared secret

# --- Kyber KEM Primitives (Production) ---


def kyber_generate_keypair() -> Tuple[bytes, bytes]:
    """Generates a real Kyber-768 key pair."""
    with oqs.KeyEncapsulation(KYBER_ALG) as kem:
        public_key = kem.generate_keypair()
        secret_key = kem.export_secret_key()
        return public_key, secret_key


def kyber_encapsulate(public_key: bytes) -> Tuple[bytes, bytes]:
    """
    Real Kyber encapsulation.
    Generates a ciphertext (KEM CT) and a shared secret key (K).
    """
    with oqs.KeyEncapsulation(KYBER_ALG) as kem:
        ciphertext, shared_secret = kem.encap_secret(public_key)
        return ciphertext, shared_secret


def kyber_decapsulate(secret_key: bytes, ciphertext: bytes) -> bytes:
    """
    Real Kyber decapsulation.
    Recovers the shared secret key (K) from the KEM CT.
    """
    with oqs.KeyEncapsulation(KYBER_ALG, secret_key) as kem:
        shared_secret = kem.decap_secret(ciphertext)
        return shared_secret


# --- Dilithium Signature Primitives (Production) ---


def dilithium_generate_keypair() -> Tuple[bytes, bytes]:
    """Generates a real Dilithium-3 key pair."""
    with oqs.Signature(DILITHIUM_ALG) as sig:
        public_key = sig.generate_keypair()
        secret_key = sig.export_secret_key()
        return public_key, secret_key


def dilithium_sign(secret_key: bytes, message: bytes) -> bytes:
    """Real Dilithium signing operation."""
    with oqs.Signature(DILITHIUM_ALG, secret_key) as sig:
        signature = sig.sign(message)
        return signature


def dilithium_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Real Dilithium verification operation."""
    with oqs.Signature(DILITHIUM_ALG) as sig:
        is_valid = sig.verify(message, signature, public_key)
        return is_valid


# --- Composite PQC + Symmetric Encryption Wire Functions ---


def encrypt_payload_with_kem(
    server_pk: bytes, plaintext_bytes: bytes, aad: bytes = b""
) -> Dict[str, bytes]:
    """
    AGENT SIDE: Uses Kyber KEM and AES-256 GCM.
    This is cryptographically sound.
    """
    # 1. Generate a shared key and the KEM ciphertext
    kem_ciphertext, shared_key = kyber_encapsulate(server_pk)

    # 2. Encrypt the data using the shared key
    aesgcm = AESGCM(shared_key)
    nonce = qrandom_key_bytes(AES_GCM_NONCE_SIZE)
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext_bytes, aad)

    return {
        "kem_ciphertext": kem_ciphertext,
        "aes_nonce": nonce,
        "encrypted_data_with_tag": ciphertext_with_tag,
    }


def decrypt_payload_with_kem(
    server_sk: bytes, encrypted_blob: Dict[str, bytes], aad: bytes = b""
) -> Optional[bytes]:
    """
    SERVER SIDE: Decapsulates Kyber, recovers shared secret, and decrypts.
    """
    try:
        # 1. Recover the shared key using the server's secret key
        shared_key_recovered = kyber_decapsulate(
            server_sk, encrypted_blob["kem_ciphertext"]
        )

        # 2. Decrypt the data using the recovered shared key
        aesgcm = AESGCM(shared_key_recovered)
        plaintext_bytes = aesgcm.decrypt(
            encrypted_blob["aes_nonce"], encrypted_blob["encrypted_data_with_tag"], aad
        )
        return plaintext_bytes

    except (InvalidTag, oqs.OQSError):
        logging.error(
            "SERVER CRYPTO ERROR: AES-GCM tag invalid or KEM decapsulation failed."
        )
        return None
    except Exception as e:
        logging.error(f"SERVER CRYPTO ERROR: Unexpected error: {e}")
        return None


def sign_and_package_message(agent_sk: bytes, message: bytes) -> Dict[str, bytes]:
    """
    AGENT SIDE: Signs the raw message with Dilithium.
    """
    signature = dilithium_sign(agent_sk, message)
    return {"message": message, "signature": signature}


def verify_packaged_message(
    agent_pk: bytes, package: Dict
) -> Tuple[Optional[bytes], bool]:
    """
    SERVER SIDE: Verifies the Dilithium signature.
    [This is modified from your original to fix a hex-conversion bug]
    """
    try:
        # The signature from the agent is raw bytes, but if it comes
        # from a JSON payload, it might be hex. We'll assume the
        # secure_server.py logic will handle hex-to-bytes conversion.
        signature_bytes = package["signature"]
        if isinstance(signature_bytes, str):
            signature_bytes = bytes.fromhex(signature_bytes)

    except ValueError:
        logging.error("Verification ERROR: Signature is not valid hex.")
        return None, False

    is_verified = dilithium_verify(
        agent_pk, package["message"], signature_bytes  # Raw message bytes
    )

    if is_verified:
        return package["message"], True
    else:
        logging.warning("Verification ERROR: Dilithium signature check failed.")
        return None, False
