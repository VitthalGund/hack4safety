# secure_server.py
# ---------------------------------------------------------------------
# Quantum-Resistant Secure Server using ML-KEM + ML-DSA (QuantCrypt)
# ---------------------------------------------------------------------

# Remove Flask imports, use relative import for pqcrypto_layer
from app.pqc.pqcrypto_layer import (
    generate_kem_keypair,
    decrypt_payload_with_kem,
    verify_signed_message,
)
import traceback
import json
import logging

log = logging.getLogger(__name__)


class SecureWireServer:
    def __init__(self):
        self.kem_pub, self.kem_priv, self.kem_alg = generate_kem_keypair()
        self.key_id = 1
        # self.agent_pubkeys = {}  <-- REMOVED (Moved to DB)
        log.info(f"[SERVER] Initialized with {self.kem_alg} (Key ID {self.key_id})")

    # -------------------------------------------------------------
    def get_server_public_key(self):
        return {"server_public_key": self.kem_pub.hex(), "key_id": self.key_id}

    # -------------------------------------------------------------
    # def register_agent(self, agent_id, dilithium_pk_hex): <-- REMOVED
    #     This logic is now in pqc_endpoints.py

    # -------------------------------------------------------------
    def rotate_keys(self):
        self.kem_pub, self.kem_priv, self.kem_alg = generate_kem_keypair()
        self.key_id += 1
        log.info(f"[SERVER] 🔑 Rotated {self.kem_alg} keys. New ID: {self.key_id}")
        return self.get_server_public_key()

    # -------------------------------------------------------------
    # --- MODIFIED: Must now be given the agent's key ---
    def process_secure_message(self, package: dict, agent_pubkey: bytes):
        try:
            # --- Validate presence of critical fields ---
            required = [
                "agent_id",
                "key_id",
                "kem_ciphertext",
                "ciphertext",
                "nonce",
                "signature",
            ]
            for field in required:
                if field not in package or not package[field]:
                    raise ValueError(f"❌ Missing required field: {field}")

            agent_id = package["agent_id"]
            kem_ct = package["kem_ciphertext"]
            nonce = package["nonce"]
            ciphertext = package["ciphertext"]
            signature = package["signature"]
            aad = package.get("aad", {})

            # --- Decrypt payload ---
            dec_package = {
                "kem_ciphertext": kem_ct,
                "ciphertext": ciphertext,
                "nonce": nonce,
            }

            plaintext = decrypt_payload_with_kem(
                self.kem_priv, dec_package, aad
            ).decode("utf-8")

            # --- Verify signature ---
            # Use the provided agent_pubkey
            verified = verify_signed_message(
                plaintext.encode(), signature, agent_pubkey
            )
            if not verified:
                raise ValueError("❌ Signature verification failed")

            log.info(f"[SERVER] ✅ Verified + decrypted message from {agent_id}")
            log.info(f"          Preview: {plaintext[:150]}...\n")

            # --- FIX: Return plaintext for saving to DB ---
            return {"status": "ok", "plaintext": plaintext}

        except Exception as e:
            log.error(f"[SERVER] ❌ Exception while processing message: {e}")
            traceback.print_exc()
            return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------
# Create the singleton instance that all API routers will import
# ---------------------------------------------------------------------
server_core = SecureWireServer()
