"""Unit tests for hivemind_rendezvous.auth."""

import time

import pytest
from poorman_handshake.asymmetric.utils import create_RSA_key

from hivemind_rendezvous.auth import sign_ownership, verify_ownership


@pytest.fixture(scope="module")
def rsa_pair():
    """Return (pubkey_pem, private_key_pem) for testing."""
    pub, priv = create_RSA_key(2048)
    return pub, priv


@pytest.fixture(scope="module")
def server_pubkey():
    pub, _ = create_RSA_key(2048)
    return pub


# ---------------------------------------------------------------------------
# Basic validity (no server_pubkey — backward-compat default "")
# ---------------------------------------------------------------------------

def test_valid_ownership_proof(rsa_pair):
    """A freshly signed proof must verify successfully (no server binding)."""
    pub, priv = rsa_pair
    ts = int(time.time())
    sig = sign_ownership(priv, pub, ts)
    assert verify_ownership(pub, ts, sig) is True


def test_wrong_pubkey_rejected(rsa_pair):
    """A proof signed by one key must not verify against a different key."""
    pub, priv = rsa_pair
    other_pub, _ = create_RSA_key(2048)
    ts = int(time.time())
    sig = sign_ownership(priv, pub, ts)
    assert verify_ownership(other_pub, ts, sig) is False


def test_replay_rejected(rsa_pair):
    """A proof with a timestamp older than 60 seconds must be rejected."""
    pub, priv = rsa_pair
    ts = int(time.time()) - 61
    sig = sign_ownership(priv, pub, ts)
    assert verify_ownership(pub, ts, sig) is False


def test_future_timestamp_rejected(rsa_pair):
    """A proof with a future timestamp beyond tolerance must be rejected."""
    pub, priv = rsa_pair
    ts = int(time.time()) + 61
    sig = sign_ownership(priv, pub, ts)
    assert verify_ownership(pub, ts, sig) is False


def test_tampered_signature_rejected(rsa_pair):
    """A corrupted base64 signature must be rejected gracefully."""
    pub, _ = rsa_pair
    ts = int(time.time())
    assert verify_ownership(pub, ts, "not-valid-base64!!!") is False


def test_boundary_timestamp_accepted(rsa_pair):
    """A proof exactly at the 59-second boundary must be accepted."""
    pub, priv = rsa_pair
    ts = int(time.time()) - 59
    sig = sign_ownership(priv, pub, ts)
    assert verify_ownership(pub, ts, sig) is True


# ---------------------------------------------------------------------------
# Server pubkey binding (Fix 1 & 2)
# ---------------------------------------------------------------------------

def test_server_bound_proof_verifies(rsa_pair, server_pubkey):
    """A proof bound to a specific server verifies when the same server_pubkey is used."""
    pub, priv = rsa_pair
    ts = int(time.time())
    sig = sign_ownership(priv, pub, ts, server_pubkey=server_pubkey)
    assert verify_ownership(pub, ts, sig, server_pubkey=server_pubkey) is True


def test_server_bound_proof_wrong_server_rejected(rsa_pair, server_pubkey):
    """A proof bound to server A must not verify at server B (cross-server replay)."""
    pub, priv = rsa_pair
    other_server_pub, _ = create_RSA_key(2048)
    ts = int(time.time())
    sig = sign_ownership(priv, pub, ts, server_pubkey=server_pubkey)
    assert verify_ownership(pub, ts, sig, server_pubkey=other_server_pub) is False


def test_server_bound_proof_vs_unbound_rejected(rsa_pair, server_pubkey):
    """A server-bound proof must not verify when server_pubkey is omitted (default '')."""
    pub, priv = rsa_pair
    ts = int(time.time())
    sig = sign_ownership(priv, pub, ts, server_pubkey=server_pubkey)
    assert verify_ownership(pub, ts, sig) is False  # server_pubkey="" != server_pubkey


def test_unbound_proof_vs_server_bound_rejected(rsa_pair, server_pubkey):
    """An unbound proof must not verify when server_pubkey is supplied."""
    pub, priv = rsa_pair
    ts = int(time.time())
    sig = sign_ownership(priv, pub, ts)  # server_pubkey=""
    assert verify_ownership(pub, ts, sig, server_pubkey=server_pubkey) is False


# ---------------------------------------------------------------------------
# Domain separation (Fix 1)
# ---------------------------------------------------------------------------

def test_domain_separation_from_raw_message(rsa_pair):
    """Signature over raw (pubkey+timestamp) without domain prefix must not verify."""
    import base64
    from poorman_handshake.asymmetric.utils import sign_RSA
    pub, priv = rsa_pair
    ts = int(time.time())
    # Sign the raw string without the domain prefix (pre-fix format)
    raw_msg = (pub + str(ts)).encode("utf-8")
    raw_sig = base64.b64encode(sign_RSA(priv, raw_msg)).decode()
    assert verify_ownership(pub, ts, raw_sig) is False
