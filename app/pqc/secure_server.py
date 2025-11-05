# secure_server.py
# ---------------------------------------------------------------------
# Quantum-Resistant Secure Server using ML-KEM + ML-DSA (QuantCrypt)
# ---------------------------------------------------------------------

from flask import Flask, request, jsonify
from pqcrypto_layer import (
    generate_kem_keypair,
    decrypt_payload_with_kem,
    verify_signed_message,
)
import traceback, json

app = Flask(__name__)

class SecureWireServer:
    def __init__(self):
        self.kem_pub, self.kem_priv, self.kem_alg = generate_kem_keypair()
        self.key_id = 1
        self.agent_pubkeys = {}  # agent_id -> Dilithium public key
        print(f"[SERVER] Initialized with {self.kem_alg} (Key ID {self.key_id})")

    # -------------------------------------------------------------
    def get_server_public_key(self):
        return {"server_public_key": self.kem_pub.hex(), "key_id": self.key_id}

    # -------------------------------------------------------------
    def register_agent(self, agent_id, dilithium_pk_hex):
        self.agent_pubkeys[agent_id] = bytes.fromhex(dilithium_pk_hex)
        print(f"[SERVER] Registered agent: {agent_id}")

    # -------------------------------------------------------------
    def rotate_keys(self):
        self.kem_pub, self.kem_priv, self.kem_alg = generate_kem_keypair()
        self.key_id += 1
        print(f"[SERVER] 🔑 Rotated {self.kem_alg} keys. New ID: {self.key_id}")
        return self.get_server_public_key()

    # -------------------------------------------------------------
    def process_secure_message(self, package: dict):
        try:
            # --- Validate presence of critical fields ---
            required = ["agent_id", "key_id", "kem_ciphertext", "ciphertext", "nonce", "signature"]
            for field in required:
                if field not in package or not package[field]:
                    raise ValueError(f"❌ Missing required field: {field}")

            agent_id = package["agent_id"]
            kem_ct = package["kem_ciphertext"]
            nonce = package["nonce"]
            ciphertext = package["ciphertext"]
            signature = package["signature"]
            aad = package.get("aad", {})

            if agent_id not in self.agent_pubkeys:
                raise ValueError(f"❌ Unknown agent ID: {agent_id}")

            # --- Decrypt payload ---
            dec_package = {
                "kem_ciphertext": kem_ct,
                "ciphertext": ciphertext,
                "nonce": nonce,
            }

            plaintext = decrypt_payload_with_kem(self.kem_priv, dec_package, aad).decode("utf-8")

            # --- Verify signature ---
            verified = verify_signed_message(plaintext.encode(), signature, self.agent_pubkeys[agent_id])
            if not verified:
                raise ValueError("❌ Signature verification failed")

            print(f"[SERVER] ✅ Verified + decrypted message from {agent_id}")
            print(f"          Preview: {plaintext[:150]}...\n")

            return {"status": "ok"}

        except Exception as e:
            print(f"[SERVER] ❌ Exception while processing message: {e}")
            traceback.print_exc()
            return {"status": "error", "error": str(e)}

# ---------------------------------------------------------------------
# Flask API Routes
# ---------------------------------------------------------------------

server_core = SecureWireServer()

@app.route("/setup", methods=["GET"])
def setup():
    return jsonify(server_core.get_server_public_key())

@app.route("/register_agent", methods=["POST"])
def register_agent():
    data = request.get_json()
    server_core.register_agent(data["agent_id"], data["dilithium_pk_hex"])
    return jsonify({"status": "registered"})

@app.route("/rotate_keys", methods=["POST"])
def rotate_keys():
    new_info = server_core.rotate_keys()
    return jsonify({"new_key_id": new_info["key_id"]})

@app.route("/receive_message", methods=["POST"])
def receive_message():
    package = request.get_json()
    result = server_core.process_secure_message(package)
    if result["status"] == "ok":
        return jsonify(result)
    else:
        return jsonify(result), 400

# ---------------------------------------------------------------------
if __name__ == "__main__":
    print("--- Starting Quantum-Safe Conviction Data Server ---")
    print(f"Server Initialized: ML-KEM PK ID: {server_core.key_id}")
    app.run(debug=True)
