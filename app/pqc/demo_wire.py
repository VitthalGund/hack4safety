# demo_wire.py
# Minimal local demo using the same pqcrypto_layer functions.

from pqcrypto_layer import (
    generate_kem_keypair,
    generate_sig_keypair,
    encrypt_payload_with_kem,
    decrypt_payload_with_kem,
    sign_and_package_message,
    verify_packaged_message,
)
import json

def main_demo():
    print("=== Local PQC Wire Demo ===")

    # Server KEM keypair
    srv_pk, srv_sk, _ = generate_kem_keypair()

    # Agent signature keypair
    ag_pk, ag_sk, _ = generate_sig_keypair()

    # Plaintext JSON
    payload = {"case_id": "CR-2025-001", "io_name": "A.Patnaik", "conviction": "Y"}
    msg = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

    # Agent signs
    signed = sign_and_package_message(msg, ag_sk)

    # Encrypt signed bundle for server with AAD
    aad = {"demo": "wire", "key_id": 1}
    enc = encrypt_payload_with_kem(json.dumps(signed, sort_keys=True, separators=(",", ":")).encode(),
                                   srv_pk, aad)

    # Server decrypts
    inner = decrypt_payload_with_kem(srv_sk, enc, aad)
    signed_bundle = json.loads(inner.decode())
    ok, final = verify_packaged_message(signed_bundle, ag_pk, aad)

    print("Verified:", ok)
    print("Recovered JSON:", json.loads(final.decode()))

if __name__ == "__main__":
    main_demo()
