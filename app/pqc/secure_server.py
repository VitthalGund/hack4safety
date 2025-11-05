# secure_server.py - Core Server Logic for PQC Handling (Mock Version)

import logging
from typing import Dict, Tuple, Optional
import time

# Use the relative import for the MOCK layer
from .pqcrypto_layer import (
    kyber_generate_keypair,
    decrypt_payload_with_kem,
    verify_packaged_message,
    KYBER_PK_SIZE,
    KYBER_SK_SIZE,
)

log = logging.getLogger(__name__)


class SecureWireServer:

    def __init__(self):
        self.key_id = 1
        self.server_pk, self.server_sk = kyber_generate_keypair()
        log.info(
            f"Server Initialized (MOCK): Kyber PK Size: {len(self.server_pk)} bytes. SK Size: {len(self.server_sk)} bytes."
        )
        self.registered_agents: Dict[str, bytes] = {}
        self.audit_log: list = []

    # --- Utility Functions ---
    def _convert_hex_to_bytes(self, data_hex: str) -> bytes:
        return bytes.fromhex(data_hex)

    # --- Key Management ---
    def get_server_public_key(self) -> Tuple[bytes, int]:
        return self.server_pk, self.key_id

    def rotate_keys(self) -> Tuple[bytes, int]:
        """Simulates key rotation by generating a new Kyber keypair and incrementing the ID."""
        self.key_id += 1
        self.server_pk, self.server_sk = kyber_generate_keypair()
        log.info(f"SERVER (MOCK): Keys Rotated. New Key ID: {self.key_id}")
        return self.server_pk, self.key_id

    def register_agent(self, agent_id: str, dilithium_pk_hex: str) -> bool:
        """Registers a new agent's Dilithium Public Key."""
        try:
            dilithium_pk = self._convert_hex_to_bytes(dilithium_pk_hex)
            self.registered_agents[agent_id] = dilithium_pk
            return True
        except ValueError:
            return False

    # --- Message Processing ---
    def process_secure_message(
        self, secure_package: Dict
    ) -> Tuple[Optional[str], bool]:
        """Handles the full PQC secure wire protocol steps: Decrypt, Verify."""
        start_time = time.perf_counter()
        agent_id = secure_package.get("agent_id")
        package_key_id_str = secure_package.get("key_id")

        # 0. Basic Validation
        if (
            not agent_id
            or not package_key_id_str
            or agent_id not in self.registered_agents
        ):
            log.warning(
                f"SERVER FAILURE: Agent ID '{agent_id}' or Key ID is missing/invalid, or agent is not registered."
            )
            return None, False

        # 1. Key ID Check
        try:
            package_key_id_int = int(package_key_id_str)
        except ValueError:
            log.warning(
                f"SERVER FAILURE: Received key ID '{package_key_id_str}' is not a valid integer."
            )
            return None, False

        if package_key_id_int != self.key_id:
            # This failure is EXPECTED during the key rotation demo step
            log.warning(
                f"SERVER FAILURE: Key ID Mismatch! Server is on ID {self.key_id} but agent sent ID {package_key_id_int}."
            )
            return None, False

        try:
            # === CRITICAL: Reconstruct AAD exactly as the agent did (using the string key ID) ===
            aad_data = f"AGENT:{agent_id}-KEYID:{package_key_id_str}".encode("utf-8")
            log.info(
                f"SERVER DEBUG: AAD used for decryption: {aad_data.decode('utf-8')}"
            )

            # Convert hex components back to bytes for the crypto layer
            encrypted_blob = {
                "kem_ciphertext": self._convert_hex_to_bytes(
                    secure_package["kem_ciphertext"]
                ),
                "aes_nonce": self._convert_hex_to_bytes(secure_package["aes_nonce"]),
                "encrypted_data_with_tag": self._convert_hex_to_bytes(
                    secure_package["encrypted_data_with_tag"]
                ),
            }

            # 2. Decryption step: Recover the original signed message bytes
            # NOTE: Updated call to pass self.server_pk for deterministic mock key recovery
            signed_message_bytes = decrypt_payload_with_kem(
                self.server_pk,  # <--- Server's Public Key (used to recover the deterministic key)
                self.server_sk,  # Server's Secret Key (required by function signature)
                encrypted_blob,
                aad=aad_data,
            )

            if signed_message_bytes is None:
                # Failure is already logged in pqcrypto_layer.py (AES-GCM InvalidTag)
                log.error(
                    "SERVER FAILURE: Decryption/KEM process failed. (Check AAD and Keys)."
                )
                return None, False

            # 3. Verification step setup
            verification_package = {
                "message": signed_message_bytes,  # Raw bytes recovered after decryption
                "signature": secure_package[
                    "signature"
                ],  # Original signature (hex string from wire)
            }

            agent_pk = self.registered_agents[agent_id]

            # 4. Verify the message signature (Dilithium)
            final_message_bytes, is_verified = verify_packaged_message(
                agent_pk, verification_package
            )

            # --- Audit and Return ---
            processing_time_ms = (time.perf_counter() - start_time) * 1000

            if not is_verified:
                log.warning("SERVER FAILURE: Dilithium signature verification failed.")
                return None, is_verified

            log_entry = {
                "agent_id": agent_id,
                "key_id": self.key_id,
                "verified": is_verified,
                "payload_size": len(final_message_bytes) if final_message_bytes else 0,
                "processing_time_ms": f"{processing_time_ms:.2f}",
            }
            self.audit_log.append(log_entry)

            # 5. Return the decoded message string and verification status
            return final_message_bytes.decode("utf-8"), is_verified

        except Exception as e:
            log.error(
                f"SERVER FAILURE: Unexpected error during message processing: {e}"
            )
            return None, False


pqc_server = SecureWireServer()
