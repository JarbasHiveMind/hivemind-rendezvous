"""Unit tests for hivemind_rendezvous.auth."""

import time
from unittest.mock import patch

import pytest
from poorman_handshake.asymmetric.utils import create_RSA_key

from hivemind_rendezvous.auth import sign_ownership, verify_ownership


@pytest.fixture(scope="module")
def rsa_pair():
    """Return (pubkey_pem, private_key_pem) for testing."""
    pub, priv = create_RSA_key(2048)
    return pub, priv


def test_valid_ownership_proof(rsa_pair):
    """A freshly signed proof must verify successfully."""
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
    """A proof exactly at the 60-second boundary must be accepted."""
    pub, priv = rsa_pair
    ts = int(time.time()) - 59
    sig = sign_ownership(priv, pub, ts)
    assert verify_ownership(pub, ts, sig) is True
