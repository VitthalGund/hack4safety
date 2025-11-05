# api_server.py
# ---------------------------------------------------------------------
# Flask API for Quantum-Safe Conviction Data Server
# ---------------------------------------------------------------------

from flask import Flask, request, jsonify
from secure_server import SecureWireServer

app = Flask(__name__)
server_core = SecureWireServer()

# -------------------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    return "✅ Quantum-Safe Conviction Data Server running."

# -------------------------------------------------------------
@app.route("/setup", methods=["GET"])
def setup():
    """Returns server's ML-KEM public key and key ID"""
    info = server_core.get_server_public_key()
    return jsonify(info), 200

# -------------------------------------------------------------
@app.route("/register_agent", methods=["POST"])
def register_agent():
    """Register agent’s Dilithium (ML-DSA) public key"""
    data = request.get_json()
    if not data or "agent_id" not in data or "dilithium_pk_hex" not in data:
        return jsonify({"error": "Missing required fields"}), 400
    try:
        server_core.register_agent(data["agent_id"], data["dilithium_pk_hex"])
        return jsonify({"status": "registered", "agent_id": data["agent_id"]}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------------------------------------------
@app.route("/receive_message", methods=["POST"])
def receive_message():
    """Receive encrypted and signed conviction record"""
    package = request.get_json()
    if not package:
        return jsonify({"error": "Invalid JSON"}), 400
    result = server_core.process_secure_message(package)
    if result["status"] == "ok":
        return jsonify(result), 200
    else:
        return jsonify(result), 400

# -------------------------------------------------------------
@app.route("/rotate_keys", methods=["POST"])
def rotate_keys():
    """Force rotation of ML-KEM server keys"""
    try:
        new_info = server_core.rotate_keys()
        return jsonify({
            "status": "rotated",
            "new_key_id": new_info["key_id"],
            "new_public_key": new_info["server_public_key"][:32] + "..."
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------------------------------------------
if __name__ == "__main__":
    print("--- Starting Quantum-Safe Conviction Data Server ---")
    app.run(debug=True, host="127.0.0.1", port=5000)
