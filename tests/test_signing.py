"""Tests for EC key signing utilities."""

import hashlib

from ecdsa import SECP256k1
from ecdsa import SigningKey
from ecdsa.util import sigdecode_der

from getpaid_bitpay.signing import generate_pem
from getpaid_bitpay.signing import get_compressed_public_key
from getpaid_bitpay.signing import sign


class TestGeneratePem:
    def test_returns_pem_string(self):
        pem = generate_pem()
        assert isinstance(pem, str)
        assert pem.startswith("-----BEGIN EC PRIVATE KEY-----")
        assert pem.strip().endswith("-----END EC PRIVATE KEY-----")

    def test_generates_unique_keys(self):
        pem1 = generate_pem()
        pem2 = generate_pem()
        assert pem1 != pem2

    def test_key_is_secp256k1(self):
        pem = generate_pem()
        sk = SigningKey.from_pem(pem)
        assert sk.curve == SECP256k1


class TestGetCompressedPublicKey:
    def test_returns_hex_string(self):
        pem = generate_pem()
        pubkey = get_compressed_public_key(pem)
        assert isinstance(pubkey, str)
        # Compressed key: 1 byte prefix + 32 bytes x = 33 bytes = 66 hex chars
        assert len(pubkey) == 66

    def test_starts_with_02_or_03(self):
        """Compressed keys use 02 (even y) or 03 (odd y) prefix."""
        for _ in range(10):
            pem = generate_pem()
            pubkey = get_compressed_public_key(pem)
            assert pubkey[:2] in ("02", "03")

    def test_deterministic_for_same_key(self):
        pem = generate_pem()
        assert get_compressed_public_key(pem) == get_compressed_public_key(pem)


class TestSign:
    def test_returns_hex_string(self):
        pem = generate_pem()
        sig = sign("hello world", pem)
        assert isinstance(sig, str)
        # DER-encoded ECDSA sig is variable length, typically 140-144 hex chars
        assert len(sig) >= 100

    def test_signature_verifies(self):
        pem = generate_pem()
        message = 'https://test.bitpay.com/invoices{"token":"abc"}'
        sig_hex = sign(message, pem)

        # Verify using ecdsa library directly with SHA-256
        sk = SigningKey.from_pem(pem)
        vk = sk.get_verifying_key()
        sig_bytes = bytes.fromhex(sig_hex)
        assert vk.verify(
            sig_bytes,
            message.encode("utf-8"),
            hashfunc=hashlib.sha256,
            sigdecode=sigdecode_der,
        )

    def test_different_messages_different_sigs(self):
        pem = generate_pem()
        sig1 = sign("message one", pem)
        sig2 = sign("message two", pem)
        assert sig1 != sig2

    def test_different_keys_different_sigs(self):
        pem1 = generate_pem()
        pem2 = generate_pem()
        sig1 = sign("same message", pem1)
        sig2 = sign("same message", pem2)
        assert sig1 != sig2
