import pytest
import httpx
import json
import time
import uuid
from typing import Dict, Any

# Import PQC crypto layer to create a mock agent
# Make sure this test script is in the 'backend' folder to run
from app.pqc.pqcrypto_layer import (
    generate_sig_keypair,
    encrypt_payload_with_kem,
    sign_and_package_message,
)

# --- CONFIGURATION ---
BASE_URL = "http://127.0.0.1:8000"

DEFAULT_ADMIN = {"username": "admin", "password": "admin_password123"}
# These are the users to be created
ADMIN_USER = {"username": "admin_user", "password": "admin_password123"}
SP_USER = {"username": "sp_balasore", "password": "sp_password123"}
IIC_USER = {"username": "iic_djbalasore", "password": "iic_password123"}
AGENT_ID = "test_agent_001"

# --- FIX: CREATE ONE PERSISTENT KEYPAIR FOR THE TEST AGENT ---
AGENT_SIG_PUB, AGENT_SIG_PRIV, _ = generate_sig_keypair()

# This holds the tokens for all tests
auth_tokens = {}

# This will hold the ID of the case we create
created_case_id = None

# --- TEST DATA ---
# Case 1: Belongs to BALASORE District and DJ-BALASORE PS
CASE_DATA_1 = {
    "Case_Number": "BAL-TEST-001",
    "Police_Station": "DJ-BALASORE",
    "District": "BALASORE",
    "Investigating_Officer": "Test Officer A",
    "Rank": "Inspector",
    "Accused_Name": "Test Accused 1",
    "Sections_of_Law": "IPC 302",
    "Crime_Type": "Heinous",
    "Court_Name": "District Court BALASORE",
    "Date_of_Registration": "2024-01-01",
    "Date_of_Chargesheet": "2024-03-01",
    "Date_of_Judgement": "2025-01-01",
    "Duration_of_Trial_days": 306,
    "Result": "Conviction",
    "Nature_of_Offence": "Heinous",
}

# Case 2: Belongs to CUTTACK District
CASE_DATA_2 = {
    "Case_Number": "CUT-TEST-002",
    "Police_Station": "CDA-CUTTACK",
    "District": "CUTTACK",
    "Investigating_Officer": "Test Officer B",
    "Rank": "ASI",
    "Accused_Name": "Test Accused 2",
    "Sections_of_Law": "IPC 379",
    "Crime_Type": "Non-Heinous",
    "Court_Name": "SDJM Court CUTTACK",
    "Date_of_Registration": "2024-02-01",
    "Date_of_Chargesheet": "2024-04-01",
    "Date_of_Judgement": "2024-10-01",
    "Duration_of_Trial_days": 183,
    "Result": "Acquitted",
    "Nature_of_Offence": "Non-Heinous",
}

# --- Fixtures and Setup ---


@pytest.fixture(scope="session")
def client():
    # Use httpx for sync/async testing
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# Helper to get an auth token
def get_token(client, username, password):
    if username in auth_tokens:
        return auth_tokens[username]

    print(f"\nLogging in as {username}...")
    response = client.post(
        "/api/v1/auth/token", data={"username": username, "password": password}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    auth_tokens[username] = token
    return token


def get_auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# --- TEST SUITE ---


@pytest.mark.run(order=1)
def test_01_server_health(client):
    """Test 1: Check if the server is running."""
    print("--- Test 01: Server Health Check ---")
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "Quantum-Safe Conviction Data Server Running."


@pytest.mark.run(order=2)
def test_02_create_users(client):
    """Test 2: Create Admin, SP, and IIC users."""
    print("--- Test 02: Creating Test Users ---")

    try:
        admin_token = get_token(
            client, DEFAULT_ADMIN["username"], DEFAULT_ADMIN["password"]
        )
        print(
            f"Logged in as default admin '{DEFAULT_ADMIN['username']}' to create test users."
        )
    except AssertionError:
        print("\n" + "=" * 50)
        print("FATAL: Cannot run tests.")
        print("The default admin user login failed.")
        print(
            f"Please check your .env file and ensure DEFAULT_ADMIN_USER='{DEFAULT_ADMIN['username']}'"
        )
        print(
            f"and DEFAULT_ADMIN_PASS='{DEFAULT_ADMIN['password']}' are set and match here."
        )
        print("=" * 50)
        raise

    headers = get_auth_header(admin_token)

    # Create Admin (idempotent, might fail if exists)
    admin_payload = {
        "username": ADMIN_USER["username"],
        "password": ADMIN_USER["password"],
        "full_name": "Test Admin",
        "role": "ADMIN",
    }
    response = client.post(
        "/api/v1/auth/users/create", json=admin_payload, headers=headers
    )
    assert response.status_code in [201, 400]  # Allow "User already registered"

    # Create SP
    sp_payload = {
        "username": SP_USER["username"],
        "password": SP_USER["password"],
        "full_name": "SP Balasore",
        "role": "SP",
        "district": "BALASORE",
    }
    response = client.post(
        "/api/v1/auth/users/create", json=sp_payload, headers=headers
    )
    assert response.status_code in [201, 400]  # Allow "User already registered"

    # Create IIC
    iic_payload = {
        "username": IIC_USER["username"],
        "password": IIC_USER["password"],
        "full_name": "IIC DJ Balasore",
        "role": "IIC",
        "police_station": "DJ-BALASORE",
    }
    response = client.post(
        "/api/v1/auth/users/create", json=iic_payload, headers=headers
    )
    assert response.status_code in [201, 400]


@pytest.mark.run(order=3)
def test_03_login_and_auth_check(client):
    """Test 3: Log in as all created users."""
    print("--- Test 03: Testing Login and /users/me ---")

    # Test Admin login
    admin_token = get_token(client, ADMIN_USER["username"], ADMIN_USER["password"])
    headers = get_auth_header(admin_token)
    response = client.get("/api/v1/auth/users/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["username"] == ADMIN_USER["username"]
    assert response.json()["role"] == "ADMIN"

    # Test SP login
    sp_token = get_token(client, SP_USER["username"], SP_USER["password"])
    headers = get_auth_header(sp_token)
    response = client.get("/api/v1/auth/users/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["district"] == "BALASORE"

    # Test IIC login
    iic_token = get_token(client, IIC_USER["username"], IIC_USER["password"])
    headers = get_auth_header(iic_token)
    response = client.get("/api/v1/auth/users/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["police_station"] == "DJ-BALASORE"


@pytest.mark.run(order=4)
def test_04_admin_pqc_endpoints(client):
    """Test 4: Test PQC endpoints (register agent, rotate keys)."""
    print("--- Test 04: Testing Admin PQC Endpoints ---")
    admin_token = get_token(client, ADMIN_USER["username"], ADMIN_USER["password"])
    headers = get_auth_header(admin_token)

    # 4a: Test /rotate_keys as non-admin (should fail)
    sp_token = get_token(client, SP_USER["username"], SP_USER["password"])
    sp_headers = get_auth_header(sp_token)
    response = client.post("/api/v1/pqc/rotate_keys", headers=sp_headers)
    assert response.status_code == 403  # Forbidden

    # 4b: Test /rotate_keys as admin (should pass)
    response = client.post("/api/v1/pqc/rotate_keys", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "Key rotation successful"

    # 4c: Register a new PQC agent (TODO 3)
    # --- FIX: USE THE PERSISTENT GLOBAL PUBLIC KEY ---
    agent_payload = {"agent_id": AGENT_ID, "dilithium_pk_hex": AGENT_SIG_PUB.hex()}
    response = client.post(
        "/api/v1/pqc/register_agent", json=agent_payload, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "Agent registered successfully"


@pytest.mark.run(order=5)
def test_05_secure_ingestion(client):
    """Test 5: Ingest two new cases via PQC."""
    print("--- Test 05: Testing Secure Case Ingestion ---")
    global created_case_id

    # 5a: Get server's public key (no auth required)
    response = client.get("/api/v1/pqc/setup")
    assert response.status_code == 200
    server_pk_hex = response.json()["server_public_key"]
    key_id = response.json()["key_id"]
    server_pk = bytes.fromhex(server_pk_hex)

    # 5b: Ingest Case 1 (BALASORE)
    # --- FIX: REMOVED LOCAL KEY GENERATION. WE USE THE GLOBAL KEY ---

    case1_id = f"BAL-TEST-{int(time.time())}"
    CASE_DATA_1["Case_Number"] = case1_id
    # --- FIX: SIGN WITH THE PERSISTENT GLOBAL PRIVATE KEY ---
    pkg1 = create_secure_package(CASE_DATA_1, server_pk, key_id, AGENT_SIG_PRIV)

    response = client.post("/api/v1/cases/secure_ingest", json=pkg1)
    assert response.status_code == 200
    assert response.json()["case_number"] == case1_id
    created_case_id = response.json()["mongo_id"]  # Save for later tests

    # 5c: Ingest Case 2 (CUTTACK)
    case2_id = f"CUT-TEST-{int(time.time())}"
    CASE_DATA_2["Case_Number"] = case2_id
    # --- FIX: SIGN WITH THE PERSISTENT GLOBAL PRIVATE KEY ---
    pkg2 = create_secure_package(CASE_DATA_2, server_pk, key_id, AGENT_SIG_PRIV)

    response = client.post("/api/v1/cases/secure_ingest", json=pkg2)
    assert response.status_code == 200
    assert response.json()["case_number"] == case2_id


def create_secure_package(record: dict, server_pk: bytes, key_id: int, agent_sk: bytes):
    """Helper to encrypt and sign a payload."""
    rec_bytes = json.dumps(record, separators=(",", ":")).encode("utf-8")

    aad = {
        "agent_id": AGENT_ID,
        "key_id": key_id,
        "ts": int(time.time()),
        "msg_id": str(uuid.uuid4()),
    }

    enc_package = encrypt_payload_with_kem(rec_bytes, server_pk, aad, "ML-KEM-768")

    signed_bundle = sign_and_package_message(rec_bytes, agent_sk, "ML-DSA-65")

    secure_package = {
        "agent_id": AGENT_ID,
        "key_id": key_id,
        "kem_ciphertext": enc_package.get("kem_ciphertext"),
        "nonce": enc_package.get("nonce"),
        "ciphertext": enc_package.get("ciphertext"),
        "signature": signed_bundle["signature_b64"],
        "aad": aad,
    }
    return secure_package


@pytest.mark.run(order=6)
def test_06_role_based_access_sp(client):
    """Test 6: Test RBAC for SP user (TODO 1 & 2)."""
    print("--- Test 06: Testing Role-Based Access (SP) ---")
    sp_token = get_token(client, SP_USER["username"], SP_USER["password"])
    headers = get_auth_header(sp_token)

    # 6a: Search with no filter. Should ONLY return BALASORE case.
    response = client.get("/api/v1/cases/search", headers=headers)
    assert response.status_code == 200
    results = response.json()
    assert len(results) > 0
    assert all(r["District"] == "BALASORE" for r in results)

    # 6b: Search for CUTTACK (should return 0)
    response = client.get("/api/v1/cases/search?district=CUTTACK", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 0

    # 6c: Get BALASORE case by ID (should pass)
    # This assertion will now pass because test_05 passes and created_case_id is set
    assert created_case_id is not None
    response = client.get(f"/api/v1/cases/{created_case_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["District"] == "BALASORE"

    # 6d: Get CUTTACK case by ID (should fail 403)
    # (Find the Cuttack case first)
    admin_token = get_token(client, ADMIN_USER["username"], ADMIN_USER["password"])
    admin_headers = get_auth_header(admin_token)
    search_resp = client.get(
        "/api/v1/cases/search?district=CUTTACK", headers=admin_headers
    )
    # We must ensure the search finds the case we just ingested
    cuttack_case = next(
        r for r in search_resp.json() if r["Case_Number"].startswith("CUT-TEST-")
    )
    cuttack_case_id = cuttack_case["_id"]

    response = client.get(f"/api/v1/cases/{cuttack_case_id}", headers=headers)
    assert response.status_code == 403  # Forbidden
    assert "Access denied" in response.json()["detail"]


@pytest.mark.run(order=7)
def test_07_role_based_access_iic(client):
    """Test 7: Test RBAC for IIC user (TODO 1)."""
    print("--- Test 07: Testing Role-Based Access (IIC) ---")
    iic_token = get_token(client, IIC_USER["username"], IIC_USER["password"])
    headers = get_auth_header(iic_token)

    # 7a: Search with no filter. Should ONLY return DJ-BALASORE cases.
    response = client.get("/api/v1/cases/search", headers=headers)
    assert response.status_code == 200
    results = response.json()
    assert len(results) > 0
    assert all(r["Police_Station"] == "DJ-BALASORE" for r in results)


@pytest.mark.run(order=8)
def test_08_analytics_endpoints(client):
    """Test 8: Test all analytics endpoints."""
    print("--- Test 08: Testing Analytics Endpoints ---")
    admin_token = get_token(client, ADMIN_USER["username"], ADMIN_USER["password"])
    headers = get_auth_header(admin_token)

    response = client.get(
        "/api/v1/analytics/conviction-rate?group_by=District", headers=headers
    )
    assert response.status_code == 200
    assert len(response.json()) > 0

    response = client.get("/api/v1/analytics/kpi/durations", headers=headers)
    assert response.status_code == 200
    assert "avg_investigation_days" in response.json()

    response = client.get("/api/v1/analytics/trends", headers=headers)
    assert response.status_code == 200

    response = client.get(
        "/api/v1/analytics/performance/ranking?group_by=Investigating_Officer",
        headers=headers,
    )
    # This will now pass once analytics.py is fixed
    assert response.status_code == 200


@pytest.mark.run(order=9)
def test_09_insights_endpoint(client):
    """Test 9: Test the AI insights endpoint."""
    print("--- Test 09: Testing AI Insights Endpoint ---")
    admin_token = get_token(client, ADMIN_USER["username"], ADMIN_USER["password"])
    headers = get_auth_header(admin_token)

    response = client.get("/api/v1/insights/correlation", headers=headers)
    # This might fail if < 20 records are in the DB
    if response.status_code == 400:
        print("Note: AI Insights test skipped (not enough data).")
    else:
        # This will now pass because test_05 ingested both Conviction and Acquitted cases
        assert response.status_code == 200
        assert "factors_promoting_conviction" in response.json()


@pytest.mark.run(order=10)
def test_10_metadata_endpoints(client):
    """Test 10: Test the new metadata/dropdown endpoints."""
    print("--- Test 10: Testing Metadata (Dropdown) Endpoints ---")
    admin_token = get_token(client, ADMIN_USER["username"], ADMIN_USER["password"])
    headers = get_auth_header(admin_token)

    response = client.get("/api/v1/metadata/distinct/District", headers=headers)
    assert response.status_code == 200
    assert "BALASORE" in response.json()
    assert "CUTTACK" in response.json()

    response = client.get("/api/v1/metadata/distinct/Rank", headers=headers)
    assert response.status_code == 200
    assert "Inspector" in response.json()
    assert "ASI" in response.json()


# --- ADD THESE NEW TESTS TO THE END OF YOUR test_full_system.py FILE ---


@pytest.mark.run(order=11)
def test_11_rag_endpoints(client):
    """Test 11: Test the RAG endpoints for legal and case bots."""
    print("--- Test 11: Testing RAG Endpoints ---")

    # We'll use the admin user for RAG queries
    admin_token = get_token(client, ADMIN_USER["username"], ADMIN_USER["password"])
    headers = get_auth_header(admin_token)

    # 11a: Test the /legal bot
    legal_payload = {
        "query": "What is the punishment for theft under BNS?",
        "model_provider": "gemini",  # Use gemini for testing
    }
    response = client.post("/api/v1/rag/legal", headers=headers, json=legal_payload)

    # Handle 503 if RAG service isn't running/configured
    if response.status_code == 503:
        print("Warning: RAG service is not available. Skipping RAG tests.")
        return

    assert response.status_code == 200
    json_res = response.json()
    assert "answer" in json_res
    assert "original_query" in json_res
    assert len(json_res["answer"]) > 10  # Check for a real answer

    # 11b: Test the /cases bot
    case_payload = {
        "query": f"Tell me about case {CASE_DATA_1['Case_Number']}",
        "model_provider": "gemini",
    }
    response = client.post("/api/v1/rag/cases", headers=headers, json=case_payload)
    assert response.status_code == 200
    json_res = response.json()
    assert "answer" in json_res
    assert "retrieved_context" in json_res
    assert len(json_res["retrieved_context"]) > 0


@pytest.mark.run(order=12)
def test_12_update_case_field(client):
    """Test 12: Test updating a field in a case (PUT)."""
    print("--- Test 12: Testing Case Field Update (PUT) ---")

    # Use the IIC user to test RBAC on update
    iic_token = get_token(client, IIC_USER["username"], IIC_USER["password"])
    headers = get_auth_header(iic_token)

    assert created_case_id is not None, "Case ID was not created in test 5"

    new_officer_name = f"Updated IO {int(time.time())}"
    update_payload = {
        "field_name": "Investigating_Officer",
        "field_value": new_officer_name,
    }

    # 12a: Update the field
    response = client.put(
        f"/api/v1/cases/{created_case_id}/field", headers=headers, json=update_payload
    )
    assert response.status_code == 200
    assert response.json()["modified_count"] == 1

    # 12b: Verify the update by fetching the case again
    response = client.get(f"/api/v1/cases/{created_case_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["Investigating_Officer"] == new_officer_name
    print(f"Successfully updated case {created_case_id}.")


@pytest.mark.run(order=13)
def test_13_pqc_status_endpoint(client):
    """Test 13: Test the PQC status endpoint."""
    print("--- Test 13: Testing PQC Status Endpoint ---")

    # This endpoint does not require auth
    response = client.get("/api/v1/pqc/status")
    assert response.status_code == 200
    json_res = response.json()
    assert "system_status" in json_res
    assert "key_management" in json_res
    assert "registered_agents_count" in json_res["key_management"]
    assert json_res["key_management"]["registered_agents_count"] >= 1


@pytest.mark.run(order=14)
def test_14_delete_case(client):
    """Test 14: Test deleting a case (DELETE) with RBAC."""
    print("--- Test 14: Testing Case Deletion (DELETE) ---")

    # 1. Get the Cuttack case ID (needed for RBAC test)
    admin_token = get_token(client, ADMIN_USER["username"], ADMIN_USER["password"])
    admin_headers = get_auth_header(admin_token)
    search_resp = client.get(
        "/api/v1/cases/search?district=CUTTACK", headers=admin_headers
    )
    cuttack_case = next(
        r for r in search_resp.json() if r["Case_Number"].startswith("CUT-TEST-")
    )
    cuttack_case_id = cuttack_case["_id"]

    # 14a: IIC user (DJ-BALASORE) TRIES to delete CUTTACK case (should fail)
    iic_token = get_token(client, IIC_USER["username"], IIC_USER["password"])
    iic_headers = get_auth_header(iic_token)

    response = client.delete(f"/api/v1/cases/{cuttack_case_id}", headers=iic_headers)
    assert response.status_code == 403  # Forbidden
    print("Successfully blocked IIC from deleting case out of jurisdiction.")

    # 14b: SP user (BALASORE) successfully DELETES their own case
    assert created_case_id is not None, "Balasore Case ID not found"

    sp_token = get_token(client, SP_USER["username"], SP_USER["password"])
    sp_headers = get_auth_header(sp_token)

    response = client.delete(f"/api/v1/cases/{created_case_id}", headers=sp_headers)
    assert response.status_code == 200
    assert response.json()["deleted_count"] == 1
    print(f"Successfully deleted case {created_case_id}.")

    # 14c: Verify the case is gone
    response = client.get(f"/api/v1/cases/{created_case_id}", headers=sp_headers)
    assert response.status_code == 404  # Not Found
    print("Verified case is no longer accessible.")
