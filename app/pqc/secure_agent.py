# secure_agent.py
# ---------------------------------------------------------------------
# Quantum-Resistant Secure Agent using ML-KEM-768 + ML-DSA-65
# Sends encrypted + signed conviction records to PQC-enabled server
# ---------------------------------------------------------------------

import json, requests, uuid, time
from pqcrypto_layer import (
    generate_sig_keypair,
    encrypt_payload_with_kem,
    sign_and_package_message,
)
from pathlib import Path

API_BASE = "http://127.0.0.1:5000"
DEFAULT_SIG_ALG = "ML-DSA-65"

class SecureAgent:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.sig_pub, self.sig_priv, self.sig_alg = generate_sig_keypair()
        self.kem_pub = None
        self.kem_key_id = None
        print(f"=== Secure PQC Agent Demo ===")
        print(f"Agent ready; {self.sig_alg} public key size: {len(self.sig_pub)} bytes\n")

    # -----------------------------------------------------------------
    # 1️⃣  Setup with the Server
    # -----------------------------------------------------------------
    def setup_with_server(self):
        print(f"--- Agent Setup ({self.agent_id}) ---")
        try:
            # Step 1: Get current server ML-KEM public key
            resp = requests.get(f"{API_BASE}/setup")
            info = resp.json()
            self.kem_pub = bytes.fromhex(info["server_public_key"])
            self.kem_key_id = info["key_id"]
            print(f"✅ Got server Kyber key (Key ID {self.kem_key_id})")

            # Step 2: Register agent's Dilithium public key
            reg_payload = {
                "agent_id": self.agent_id,
                "dilithium_pk_hex": self.sig_pub.hex(),
            }
            reg_resp = requests.post(f"{API_BASE}/register_agent", json=reg_payload)
            if reg_resp.status_code == 200:
                print("✅ Agent public key registered.")
            else:
                print("❌ Registration failed:", reg_resp.text)

        except Exception as e:
            print(f"❌ Setup failed: {e}")

    # -----------------------------------------------------------------
    # 2️⃣  Encrypt + Sign + Send Conviction Record
    # -----------------------------------------------------------------
    def send_secure_conviction_record(self, record: dict):
        try:
            # --- Step 1: Convert record into bytes ---
            rec_bytes = json.dumps(record, separators=(",", ":")).encode("utf-8")

            # --- Step 2: Create AAD (additional authenticated data) ---
            aad = {
                "agent_id": self.agent_id,
                "key_id": self.kem_key_id,
                "ts": int(time.time()),
                "msg_id": str(uuid.uuid4()),
            }

            # --- Step 3: Encrypt using ML-KEM + AES-GCM ---
            enc_package = encrypt_payload_with_kem(
                rec_bytes, self.kem_pub, aad, "ML-KEM-768"
            )

            # --- Step 4: Sign the original plaintext (for authenticity) ---
            signed_bundle = sign_and_package_message(rec_bytes, self.sig_priv, DEFAULT_SIG_ALG)

            # --- Step 5: Prepare flattened package for server ---
            secure_package = {
                "agent_id": self.agent_id,
                "key_id": self.kem_key_id,
                "kem_ciphertext": enc_package.get("kem_ciphertext"),
                "nonce": enc_package.get("nonce"),
                "ciphertext": enc_package.get("ciphertext"),
                "signature": signed_bundle["signature_b64"],
                "aad": aad,
            }

            print(f"[DEBUG] Sending to server ({self.agent_id}, Key {self.kem_key_id})")
            print(json.dumps(secure_package, indent=2)[:600], "...\n")

            # --- Step 6: Transmit ---
            resp = requests.post(f"{API_BASE}/receive_message", json=secure_package)

            if resp.status_code == 200:
                print(f"✅ Record {record.get('Case_Number', '')} SENT successfully!\n")
            else:
                print(f"❌ Send failed: {resp.status_code} {resp.reason} for url: {resp.url}\n")

        except Exception as e:
            print(f"❌ Transmission error: {e}")

# ---------------------------------------------------------------------
# Utility: Load Conviction Records (demo dataset)
# ---------------------------------------------------------------------
def load_conviction_records() -> list:
    # Demo dataset, could be replaced with DB or file input
    return [
        {
            "Case_Number": "DEMO-BAL-1001",
            "Accused_Name": "Somanath Pattnaik",
            "Crime_Type": "Arms Offence",
            "FIR_No": "AUL/23/125",
            "Date_of_Occurrence": "2024-09-30",
        },
        {
            "Case_Number": "DEMO-BAL-1002",
            "Accused_Name": "Nilima Das",
            "Crime_Type": "Narcotics",
            "FIR_No": "BAL/22/337",
            "Date_of_Occurrence": "2024-09-29",
        },
    ]

# ---------------------------------------------------------------------
# Demo Flow
# ---------------------------------------------------------------------
def send_secure_batch(agent: SecureAgent, records: list, title: str):
    print(f"\n--- {title} ({len(records)} records) ---")
    for r in records:
        agent.send_secure_conviction_record(r)
        time.sleep(0.5)

def main_demo():
    agent = SecureAgent("PS-JAYPORE-COURT-LIAISON")
    agent.setup_with_server()

    all_records = load_conviction_records()
    print(f"Loaded {len(all_records)} conviction records for secure transmission.\n")

    # Initial transmission
    send_secure_batch(agent, all_records[:1], f"Initial Transmission (Key ID {agent.kem_key_id})")

    # Rotate server keys
    print("\n🔁 Rotating keys on server...")
    rot_resp = requests.post(f"{API_BASE}/rotate_keys").json()
    print(f"🔑 New Key ID: {rot_resp['new_key_id']}\n")

    # Re-setup after key rotation
    print("🔄 Agent re-setup after rotation...\n")
    agent.setup_with_server()

    # Send again with new key
    send_secure_batch(agent, all_records[1:], f"Post-Rotation Transmission (Key ID {agent.kem_key_id})")

    print("\n=== Demo Complete ===")

# ---------------------------------------------------------------------
if __name__ == "__main__":
    main_demo()
