import logging
from typing import Dict, Tuple, Optional
import time

# Import our new production-ready PQC layer
from .pqcrypto_layer import (
    kyber_generate_keypair,
    decrypt_payload_with_kem,
    verify_packaged_message,
    dilithium_generate_keypair,  # Need this for agent registration
)

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class SecureWireServer:

    def __init__(self):
        self.key_id = 1
        self.server_pk, self.server_sk = kyber_generate_keypair()
        log.info(f"Server Initialized: Kyber PK ID: {self.key_id}")

        # We will move agent registration to the PostgreSQL database
        # This is just a temporary cache.
        self.registered_agents: Dict[str, bytes] = {}
        self.audit_log: list = []

    def _convert_hex_to_bytes(self, data_hex: str) -> bytes:
        return bytes.fromhex(data_hex)

    def get_server_public_key(self) -> Tuple[bytes, int]:
        return self.server_pk, self.key_id

    def rotate_keys(self) -> Tuple[bytes, int]:
        """Generates a new Kyber keypair and increments the ID."""
        self.key_id += 1
        self.server_pk, self.server_sk = kyber_generate_keypair()
        log.info(f"SERVER: Keys Rotated. New Key ID: {self.key_id}")
        return self.server_pk, self.key_id

    def register_agent(self, agent_id: str, dilithium_pk_hex: str) -> bool:
        """
        Registers a new agent's Dilithium Public Key.
        TODO: This should save to the PostgreSQL database, not in-memory.
        """
        try:
            dilithium_pk = self._convert_hex_to_bytes(dilithium_pk_hex)
            self.registered_agents[agent_id] = dilithium_pk
            log.info(f"Registered agent {agent_id}")
            return True
        except ValueError:
            log.error(f"Failed to register agent {agent_id}: Invalid hex PK.")
            return False

    def process_secure_message(
        self, secure_package: Dict
    ) -> Tuple[Optional[str], bool]:
        """Handles the full PQC secure wire protocol: Decrypt, Verify."""
        start_time = time.perf_counter()
        agent_id = secure_package.get("agent_id")
        package_key_id_str = secure_package.get("key_id")

        if (
            not agent_id
            or not package_key_id_str
            or agent_id not in self.registered_agents
        ):
            log.warning(
                f"SERVER FAILURE: Agent ID '{agent_id}' or Key ID is missing/invalid, or agent not registered."
            )
            return None, False

        try:
            package_key_id_int = int(package_key_id_str)
        except ValueError:
            log.warning(
                f"SERVER FAILURE: Received key ID '{package_key_id_str}' is not valid."
            )
            return None, False

        if package_key_id_int != self.key_id:
            log.warning(
                f"SERVER FAILURE: Key ID Mismatch! Server ID {self.key_id} vs Agent ID {package_key_id_int}."
            )
            return None, False

        try:
            # Reconstruct AAD
            aad_data = f"AGENT:{agent_id}-KEYID:{package_key_id_str}".encode("utf-8")

            # Convert hex components back to bytes
            encrypted_blob = {
                "kem_ciphertext": self._convert_hex_to_bytes(
                    secure_package["kem_ciphertext"]
                ),
                "aes_nonce": self._convert_hex_to_bytes(secure_package["aes_nonce"]),
                "encrypted_data_with_tag": self._convert_hex_to_bytes(
                    secure_package["encrypted_data_with_tag"]
                ),
            }

            # 2. Decryption (Using the new, correct function signature)
            signed_message_bytes = decrypt_payload_with_kem(
                self.server_sk,  # We only need the secret key
                encrypted_blob,
                aad=aad_data,
            )

            if signed_message_bytes is None:
                log.error(
                    "SERVER FAILURE: Decryption/KEM process failed. (Check AAD, Keys, or Tag)."
                )
                return None, False

            # 3. Verification setup
            verification_package = {
                "message": signed_message_bytes,  # Raw bytes
                "signature": secure_package["signature"],  # Hex string from wire
            }

            agent_pk = self.registered_agents[agent_id]

            # 4. Verify the message signature (Dilithium)
            final_message_bytes, is_verified = verify_packaged_message(
                agent_pk, verification_package
            )

            processing_time_ms = (time.perf_counter() - start_time) * 1000

            if not is_verified:
                log.error("SERVER FAILURE: Dilithium signature verification failed.")
                return None, is_verified

            log_entry = {
                "agent_id": agent_id,
                "verified": is_verified,
                "processing_time_ms": f"{processing_time_ms:.2f}",
            }
            self.audit_log.append(log_entry)

            return final_message_bytes.decode("utf-8"), is_verified

        except Exception as e:
            log.error(
                f"SERVER FAILURE: Unexpected error during message processing: {e}"
            )
            return None, False


pqc_server = SecureWireServer()
