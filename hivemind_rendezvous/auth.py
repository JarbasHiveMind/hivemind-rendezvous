"""Proof-of-pubkey-ownership authentication for the rendezvous service.

Stateless, single-round-trip: the client signs a domain-separated message:

    ``b"hivemind-rendezvous-v1\\x00" + pubkey_bytes + b"\\x00"
      + server_pubkey_bytes + b"\\x00" + timestamp_bytes``

The server verifies the signature and rejects timestamps outside a ±60 second
window to prevent replay attacks.  Binding the server's own pubkey into the
signed message prevents cross-server replay: a valid proof issued to one
rendezvous node cannot be replayed at another.
"""

import base64
import time
from typing import Union

from poorman_handshake.asymmetric.utils import sign_RSA, verify_RSA


_TIMESTAMP_TOLERANCE_SECONDS: int = 60
_DOMAIN: bytes = b"hivemind-rendezvous-v1\x00"


def _ownership_message(pubkey: str, timestamp: int, server_pubkey: str = "") -> bytes:
    """Return the canonical byte string that is signed/verified for ownership proof.

    The message is domain-separated and binds the server's public key to prevent
    cross-server replay attacks.

    Format (bytes, null-delimited fields):
    ``DOMAIN || claimer_pubkey || 0x00 || server_pubkey || 0x00 || timestamp_decimal``

    Args:
        pubkey: PEM-encoded RSA public key of the claiming node.
        timestamp: Unix timestamp (integer seconds).
        server_pubkey: PEM-encoded RSA public key of the rendezvous server.
            Empty string when server identity binding is not used (legacy / testing).

    Returns:
        The message bytes to sign or verify.
    """
    return (
        _DOMAIN
        + pubkey.encode("utf-8") + b"\x00"
        + server_pubkey.encode("utf-8") + b"\x00"
        + str(timestamp).encode("utf-8")
    )


def sign_ownership(private_key: Union[str, bytes], pubkey: str, timestamp: int,
                   server_pubkey: str = "") -> str:
    """Produce a base64-encoded ownership proof signature.

    Args:
        private_key: RSA private key (PEM string, bytes, or RsaKey) of the claimer.
        pubkey: PEM-encoded RSA public key of the claimer.
        timestamp: Unix timestamp (integer seconds) to embed in the proof.
        server_pubkey: PEM-encoded RSA public key of the rendezvous server.
            Binds the proof to a specific server — must match the value used
            by the server in :func:`verify_ownership`.

    Returns:
        Base64-encoded signature string suitable for JSON transport.
    """
    message = _ownership_message(pubkey, timestamp, server_pubkey)
    signature_bytes = sign_RSA(private_key, message)
    return base64.b64encode(signature_bytes).decode("utf-8")


def verify_ownership(pubkey: str, timestamp: int, signature: str,
                     server_pubkey: str = "") -> bool:
    """Verify a proof-of-pubkey-ownership claim.

    Checks both signature validity and timestamp freshness.  A valid proof
    requires:

    1. The signature over the domain-separated message verifies against
       ``pubkey``.
    2. ``abs(now - timestamp) <= 60`` seconds (replay protection).
    3. ``server_pubkey`` in the signed message matches the value passed here
       (cross-server replay protection).

    Args:
        pubkey: PEM-encoded RSA public key of the claiming node.
        timestamp: Unix timestamp (integer seconds) embedded in the proof.
        signature: Base64-encoded signature produced by :func:`sign_ownership`.
        server_pubkey: PEM-encoded RSA public key of the rendezvous server
            that was used when signing.  Must be supplied by the server itself.

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
    message = _ownership_message(pubkey, timestamp, server_pubkey)
    return verify_RSA(pubkey, message, signature_bytes)
