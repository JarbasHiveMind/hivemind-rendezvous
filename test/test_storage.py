"""Unit tests for hivemind_rendezvous.storage."""

import time
from unittest.mock import patch, MagicMock

import pytest

from hivemind_rendezvous.storage import RendezvousStore, _pubkey_fingerprint


FAKE_PUBKEY_A = "-----BEGIN PUBLIC KEY-----\nFAKEA\n-----END PUBLIC KEY-----"
FAKE_PUBKEY_B = "-----BEGIN PUBLIC KEY-----\nFAKEB\n-----END PUBLIC KEY-----"
FAKE_PAYLOAD = '{"msg_type": "intercom", "payload": {}}'


@pytest.fixture()
def store(tmp_path):
    """Return a RendezvousStore backed by a temp file."""
    with patch("hivemind_rendezvous.storage.xdg_data_home", return_value=str(tmp_path)):
        s = RendezvousStore(store_name="test_rendezvous")
    return s


def test_deposit_and_retrieve(store):
    """Deposited message is returned on retrieve."""
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    messages = store.retrieve(FAKE_PUBKEY_A)
    assert messages == [FAKE_PAYLOAD]


def test_retrieve_deletes_messages(store):
    """Second retrieve returns empty list."""
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    store.retrieve(FAKE_PUBKEY_A)
    assert store.retrieve(FAKE_PUBKEY_A) == []


def test_retrieve_unknown_pubkey(store):
    """Retrieve for a pubkey with no messages returns empty list."""
    assert store.retrieve(FAKE_PUBKEY_B) == []


def test_multiple_deposits(store):
    """Multiple deposits accumulate; all returned on retrieve."""
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD + "1")
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD + "2")
    messages = store.retrieve(FAKE_PUBKEY_A)
    assert len(messages) == 2


def test_ttl_expiry(store):
    """Message with TTL=0 is evicted before retrieval."""
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=0)
    # Force sweep by depositing another message (triggers _sweep internally)
    store.deposit(FAKE_PUBKEY_B, FAKE_PAYLOAD, ttl=3600)
    messages = store.retrieve(FAKE_PUBKEY_A)
    assert messages == []


def test_ttl_capped_at_max(store):
    """TTL above the cap is reduced to _MAX_TTL_SECONDS."""
    from hivemind_rendezvous.storage import _MAX_TTL_SECONDS
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=_MAX_TTL_SECONDS * 10)
    fp = _pubkey_fingerprint(FAKE_PUBKEY_A)
    entry = store._db[fp][0]
    expected_max = time.time() + _MAX_TTL_SECONDS
    assert entry["expires_at"] <= expected_max + 2  # allow 2s clock slack


def test_different_pubkeys_isolated(store):
    """Messages for different pubkeys do not cross."""
    store.deposit(FAKE_PUBKEY_A, "msg_a")
    store.deposit(FAKE_PUBKEY_B, "msg_b")
    assert store.retrieve(FAKE_PUBKEY_A) == ["msg_a"]
    assert store.retrieve(FAKE_PUBKEY_B) == ["msg_b"]


def test_fingerprint_deterministic():
    """Same pubkey always produces the same fingerprint."""
    assert _pubkey_fingerprint(FAKE_PUBKEY_A) == _pubkey_fingerprint(FAKE_PUBKEY_A)
    assert _pubkey_fingerprint(FAKE_PUBKEY_A) != _pubkey_fingerprint(FAKE_PUBKEY_B)
