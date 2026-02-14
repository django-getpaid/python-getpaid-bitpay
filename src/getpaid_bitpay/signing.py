"""EC key utilities for BitPay merchant facade authentication.

BitPay uses secp256k1 (Bitcoin's curve) for request signing.
Signed requests include:
- X-Identity header: compressed public key (hex)
- X-Signature header: ECDSA-SHA256 signature of URL+body (DER hex)
"""

import hashlib

from ecdsa import SECP256k1
from ecdsa import SigningKey
from ecdsa.util import sigencode_der


def generate_pem() -> str:
    """Generate a new secp256k1 private key in PEM format."""
    sk = SigningKey.generate(curve=SECP256k1)
    return sk.to_pem().decode("utf-8")


def get_compressed_public_key(pem: str) -> str:
    """Extract compressed public key hex from a PEM private key.

    Returns a 66-character hex string (02/03 prefix + 32-byte x).
    """
    sk = SigningKey.from_pem(pem)
    vk = sk.get_verifying_key()
    # vk.to_string() is the raw 64-byte uncompressed point (x || y)
    raw = vk.to_string()
    x = raw[:32]
    y = raw[32:]
    prefix = b"\x02" if y[-1] % 2 == 0 else b"\x03"
    return (prefix + x).hex()


def sign(message: str, pem: str) -> str:
    """Sign a message with ECDSA-SHA256, return DER-encoded hex.

    The message is the concatenation of the full request URL and
    the JSON body string, encoded as UTF-8.
    """
    sk = SigningKey.from_pem(pem)
    sig = sk.sign(
        message.encode("utf-8"),
        hashfunc=hashlib.sha256,
        sigencode=sigencode_der,
    )
    return sig.hex()
