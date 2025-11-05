# pqcrypto_layer.py
# ---------------------------------------------------------------------
# Quantum-Resistant Crypto Layer built on QuantCrypt
# ML-KEM-768 (FIPS 203) + ML-DSA-65 (FIPS 204)
# ---------------------------------------------------------------------

import base64, json, os
from typing import Dict, Tuple
from quantcrypt.kem import MLKEM_768
from quantcrypt.dss import MLDSA_65
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes

# ---------------------------------------------------------------------
# Helper: Base64 encode/decode
# ---------------------------------------------------------------------
def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")

def _b64d(s: str) -> bytes:
    if s is None:
        raise ValueError("Missing required base64 field")
    return base64.b64decode(s.encode("ascii"))

# ---------------------------------------------------------------------
# 1️⃣  KEM Key Generation (ML-KEM-768)
# ---------------------------------------------------------------------
def generate_kem_keypair() -> Tuple[bytes, bytes, str]:
    kem = MLKEM_768()
    pk, sk = kem.keygen()
    return pk, sk, "ML-KEM-768"

# ---------------------------------------------------------------------
# 2️⃣  Signature Key Generation (ML-DSA-65)
# ---------------------------------------------------------------------
def generate_sig_keypair() -> Tuple[bytes, bytes, str]:
    sig = MLDSA_65()
    pk, sk = sig.keygen()
    return pk, sk, "ML-DSA-65"

# ---------------------------------------------------------------------
# 3️⃣  Encrypt payload with KEM + AES-GCM
# ---------------------------------------------------------------------
def encrypt_payload_with_kem(
    plaintext: bytes, kem_public_key: bytes, aad: Dict, kem_alg: str = "ML-KEM-768"
) -> Dict:
    kem = MLKEM_768()
    ciphertext, shared_secret = kem.encaps(kem_public_key)

    # derive AES-GCM key from shared_secret (32 bytes)
    aes_key = shared_secret[:32]
    aesgcm = AESGCM(aes_key)
    nonce = os.urandom(12)

    aad_bytes = json.dumps(aad, separators=(",", ":")).encode()
    ciphertext_enc = aesgcm.encrypt(nonce, plaintext, aad_bytes)

    return {
        "kem_alg": kem_alg,
        "kem_ciphertext": _b64e(ciphertext),
        "nonce": _b64e(nonce),
        "ciphertext": _b64e(ciphertext_enc),
    }

# ---------------------------------------------------------------------
# 4️⃣  Decrypt payload with KEM + AES-GCM
# ---------------------------------------------------------------------
def decrypt_payload_with_kem(
    kem_private_key: bytes, package: Dict, aad: Dict
) -> bytes:
    kem = MLKEM_768()
    kem_ct = _b64d(package["kem_ciphertext"])
    ciphertext = _b64d(package["ciphertext"])
    nonce = _b64d(package["nonce"])

    # 🔥 FIX: Correct argument order
    shared_secret = kem.decaps(kem_private_key, kem_ct)

    aes_key = shared_secret[:32]
    aesgcm = AESGCM(aes_key)

    aad_bytes = json.dumps(aad, separators=(",", ":")).encode()
    plaintext = aesgcm.decrypt(nonce, ciphertext, aad_bytes)
    return plaintext


# ---------------------------------------------------------------------
# 5️⃣  Sign message (ML-DSA-65)
# ---------------------------------------------------------------------
def sign_and_package_message(message_bytes: bytes, sig_private_key: bytes, sig_alg: str) -> Dict:
    sig = MLDSA_65()
    signature = sig.sign(sig_private_key, message_bytes)
    return {
        "sig_alg": sig_alg,
        "signature_b64": _b64e(signature),
    }

# ---------------------------------------------------------------------
# 6️⃣  Verify message signature
# ---------------------------------------------------------------------
def verify_signed_message(message_bytes: bytes, signature_b64: str, sig_public_key: bytes) -> bool:
    try:
        signature = _b64d(signature_b64)
        sig = MLDSA_65()
        return sig.verify(sig_public_key, message_bytes, signature)
    except Exception:
        return False

# ---------------------------------------------------------------------
# 7️⃣  Optional: Hash utility
# ---------------------------------------------------------------------
def sha3_256(data: bytes) -> str:
    digest = hashes.Hash(hashes.SHA3_256())
    digest.update(data)
    return digest.finalize().hex()

# ---------------------------------------------------------------------
# End of file
# ---------------------------------------------------------------------
