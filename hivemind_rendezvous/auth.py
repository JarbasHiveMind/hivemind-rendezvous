"""Proof-of-pubkey-ownership authentication for the rendezvous service.

Stateless, single-round-trip: the client signs ``pubkey + str(timestamp_seconds)``
with its RSA private key.  The server verifies the signature and rejects timestamps
outside a ±60 second window to prevent replay attacks.
"""

import base64
import time
from typing import Union

from poorman_handshake.asymmetric.utils import sign_RSA, verify_RSA


_TIMESTAMP_TOLERANCE_SECONDS: int = 60


def _ownership_message(pubkey: str, timestamp: int) -> bytes:
    """Return the canonical byte string that is signed/verified for ownership proof.

    Args:
        pubkey: PEM-encoded RSA public key of the claiming node.
        timestamp: Unix timestamp (integer seconds).

    Returns:
        The message bytes to sign or verify.
    """
    return (pubkey + str(timestamp)).encode("utf-8")


def sign_ownership(private_key: Union[str, bytes], pubkey: str, timestamp: int) -> str:
    """Produce a base64-encoded ownership proof signature.

    Args:
        private_key: RSA private key (PEM string, bytes, or RsaKey) of the claimer.
        pubkey: PEM-encoded RSA public key of the claimer (used as part of signed message).
        timestamp: Unix timestamp (integer seconds) to embed in the proof.

    Returns:
        Base64-encoded signature string suitable for JSON transport.
    """
    message = _ownership_message(pubkey, timestamp)
    signature_bytes = sign_RSA(private_key, message)
    return base64.b64encode(signature_bytes).decode("utf-8")


def verify_ownership(pubkey: str, timestamp: int, signature: str) -> bool:
    """Verify a proof-of-pubkey-ownership claim.

    Checks both signature validity and timestamp freshness.  A valid proof
    requires:
    1. The signature over ``pubkey + str(timestamp)`` verifies against ``pubkey``.
    2. ``abs(now - timestamp) <= 60`` seconds (replay protection).

    Args:
        pubkey: PEM-encoded RSA public key of the claiming node.
        timestamp: Unix timestamp (integer seconds) embedded in the proof.
        signature: Base64-encoded signature produced by :func:`sign_ownership`.

    Returns:
        ``True`` if the proof is valid and fresh; ``False`` otherwise.
    """
    now = int(time.time())
    if abs(now - timestamp) > _TIMESTAMP_TOLERANCE_SECONDS:
        return False
    try:
        signature_bytes = base64.b64decode(signature)
    except Exception:
        return False
    message = _ownership_message(pubkey, timestamp)
    return verify_RSA(pubkey, message, signature_bytes)
