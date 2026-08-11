"""Unit tests for hivemind_rendezvous.storage."""

import time
from unittest.mock import patch

import pytest

from hivemind_rendezvous.storage import (RendezvousStore, _MAX_TTL_SECONDS,
                                         pubkey_fingerprint)

FAKE_PUBKEY_A = "-----BEGIN PUBLIC KEY-----\nFAKEA\n-----END PUBLIC KEY-----"
FAKE_PUBKEY_B = "-----BEGIN PUBLIC KEY-----\nFAKEB\n-----END PUBLIC KEY-----"
FAKE_PAYLOAD = '{"msg_type": "intercom", "payload": {}}'


@pytest.fixture()
def store(tmp_path):
    """Return a RendezvousStore backed by a temp file."""
    with patch("hivemind_rendezvous.storage.xdg_data_home", return_value=str(tmp_path)):
        return RendezvousStore(store_name="test_rendezvous")


def _payloads(pairs):
    return [payload for _deposit_id, payload in pairs]


def test_deposit_and_collect(store):
    """A deposited message is returned on collect."""
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    assert _payloads(store.collect(FAKE_PUBKEY_A)) == [FAKE_PAYLOAD]


def test_collect_leaves_messages_pending(store):
    """Collect is not destructive: only an ack removes a message.

    A response lost between relay and recipient must cost a redelivery, not
    the message — the recipient is offline by definition, so a destroyed
    message can never be resent.
    """
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    store.collect(FAKE_PUBKEY_A)
    assert _payloads(store.collect(FAKE_PUBKEY_A)) == [FAKE_PAYLOAD]


def test_ack_removes_the_message(store):
    deposit_id = store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    assert store.ack(FAKE_PUBKEY_A, [deposit_id]) == 1
    assert store.collect(FAKE_PUBKEY_A) == []


def test_ack_of_unknown_id_is_a_noop(store):
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    assert store.ack(FAKE_PUBKEY_A, ["no-such-id"]) == 0
    assert len(store.collect(FAKE_PUBKEY_A)) == 1


def test_ack_is_scoped_to_one_mailbox(store):
    deposit_id = store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    assert store.ack(FAKE_PUBKEY_B, [deposit_id]) == 0
    assert len(store.collect(FAKE_PUBKEY_A)) == 1


def test_partial_ack_keeps_the_rest(store):
    first = store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD + "1")
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD + "2")
    store.ack(FAKE_PUBKEY_A, [first])
    assert _payloads(store.collect(FAKE_PUBKEY_A)) == [FAKE_PAYLOAD + "2"]


def test_collect_unknown_pubkey(store):
    assert store.collect(FAKE_PUBKEY_B) == []


def test_multiple_deposits(store):
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD + "1")
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD + "2")
    assert len(store.collect(FAKE_PUBKEY_A)) == 2


def test_deposit_ids_are_unique(store):
    first = store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    second = store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    assert first != second


def test_ttl_expiry(store):
    """An expired message is never handed out, sweep interval or not."""
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=0)
    assert store.collect(FAKE_PUBKEY_A) == []


def test_expiry_is_per_mailbox_not_only_on_sweep(store):
    """Expiry must not depend on the periodic full-store sweep having run.

    The sweep is throttled to keep request cost off total stored volume, so
    freshness has to be enforced when the mailbox is read as well.
    """
    store._sweep_interval = 10_000  # ensure the global sweep cannot run
    store._last_sweep = time.time()
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=0)
    assert store.collect(FAKE_PUBKEY_A) == []


def test_pending_count_ignores_expired(store):
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=0)
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=3600)
    assert store.pending_count(FAKE_PUBKEY_A) == 1


def test_ttl_capped_at_max(store):
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=_MAX_TTL_SECONDS * 10)
    entry = store._db[pubkey_fingerprint(FAKE_PUBKEY_A)][0]
    assert entry["expires_at"] <= time.time() + _MAX_TTL_SECONDS + 2


def test_different_pubkeys_isolated(store):
    store.deposit(FAKE_PUBKEY_A, "msg_a")
    store.deposit(FAKE_PUBKEY_B, "msg_b")
    assert _payloads(store.collect(FAKE_PUBKEY_A)) == ["msg_a"]
    assert _payloads(store.collect(FAKE_PUBKEY_B)) == ["msg_b"]


def test_fingerprint_deterministic():
    assert pubkey_fingerprint(FAKE_PUBKEY_A) == pubkey_fingerprint(FAKE_PUBKEY_A)
    assert pubkey_fingerprint(FAKE_PUBKEY_A) != pubkey_fingerprint(FAKE_PUBKEY_B)
