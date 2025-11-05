# qrng.py
# Simple QRNG: generate true quantum random bits (simulated by qiskit Aer by default).
# Exposes helpers to get random bytes and seed Python RNGs if needed.

from qiskit import QuantumCircuit
from qiskit_aer import Aer
import math
import os
from typing import Optional

DEFAULT_SHOTS = 1

def _get_backend(simulator_name='qasm_simulator'):
    """
    Uses Aer simulator by default; replace with IBM provider backend if available.
    """
    try:
        backend = Aer.get_backend(simulator_name)
        return backend
    except Exception as e:
        # Fallback to os.urandom if Qiskit is not available
        print(f"Warning: Qiskit Aer backend unavailable: {e}. Falling back to os.urandom.")
        return None

def qrandom_bits(n_bits: int, backend_name: str = 'qasm_simulator') -> str:
    """
    Return a string with n_bits of quantum-random bits, e.g. '010101...'
    If Qiskit backend fails, falls back to Python's cryptographically secure source.
    """
    if n_bits <= 0:
        return ''
        
    backend = _get_backend(backend_name)
    
    if backend is None:
        # Fallback using os.urandom
        n_bytes = math.ceil(n_bits / 8)
        random_bytes = os.urandom(n_bytes)
        # Convert bytes to binary string and truncate to n_bits
        bits = ''.join(format(byte, '08b') for byte in random_bytes)
        return bits[:n_bits]
        
    # Qiskit logic
    bits = ''
    # Use up to 20 qubits per circuit as a safe default
    batch = min(n_bits, 20)
    remaining = n_bits
    
    while remaining > 0:
        q = min(batch, remaining)
        qc = QuantumCircuit(q, q)
        qc.h(range(q))       # put all qubits into superposition
        qc.measure(range(q), range(q))
        
        try:
            job = backend.run(qc, shots=DEFAULT_SHOTS)
            result = job.result()
            counts = result.get_counts()
            # counts keys like '01011' - take the first result since shots=1
            measured = next(iter(counts.keys()))
            # Ensure measured string length equals q (qiskit returns MSB..LSB) - pad if needed
            if len(measured) < q:
                measured = measured.zfill(q)
            bits += measured
            remaining -= q
        except Exception as e:
            print(f"Qiskit execution error: {e}. Falling back to os.urandom for remaining bits.")
            # Fallback to os.urandom for the rest
            remaining_bytes = math.ceil(remaining / 8)
            random_bytes = os.urandom(remaining_bytes)
            fallback_bits = ''.join(format(byte, '08b') for byte in random_bytes)
            bits += fallback_bits[:remaining]
            break
            
    # if we produced extra bits due to byte rounding, truncate
    return bits[:n_bits]

def qrandom_bytes(n_bytes: int, backend_name: str = 'qasm_simulator') -> bytes:
    """
    Return n_bytes of quantum-random bytes.
    """
    if n_bytes <= 0:
        return b''
    # Request 8 * n_bytes of bits
    bits = qrandom_bits(n_bytes * 8, backend_name=backend_name)
    # Convert binary string to integer, then to bytes
    out = int(bits, 2).to_bytes(n_bytes, byteorder='big')
    return out

def qrandom_key_bytes(n_bytes: int) -> bytes:
    """
    Alias for qrandom_bytes, specifically for cryptographic key material.
    """
    # Use os.urandom as a strong fallback if qiskit is not installed or fails
    try:
        return qrandom_bytes(n_bytes)
    except Exception as e:
        print(f"QRNG failure ({e}). Using os.urandom as key source.")
        return os.urandom(n_bytes)

# Example usage (for testing)
if __name__ == '__main__':
    print("--- QRNG Test ---")
    
    # Test bits
    rand_bits = qrandom_bits(16)
    print(f"16 random bits: {rand_bits} (len: {len(rand_bits)})")
    
    # Test bytes (32 bytes = 256 bits)
    rand_bytes = qrandom_key_bytes(32)
    print(f"32 random bytes (AES key size): {rand_bytes.hex()}")
    print(f"32 random bytes (entropy check): {len(set(rand_bytes))}/{len(rand_bytes)} unique bytes")