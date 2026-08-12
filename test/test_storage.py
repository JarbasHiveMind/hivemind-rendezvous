"""Unit tests for hivemind_rendezvous.storage."""

import time
from unittest.mock import patch

import pytest

from hivemind_rendezvous.storage import (MailboxFull, RendezvousStore,
                                         _MAX_TTL_SECONDS, address_fingerprint)

FAKE_PUBKEY_A = "-----BEGIN PUBLIC KEY-----\nFAKEA\n-----END PUBLIC KEY-----"
FAKE_PUBKEY_B = "-----BEGIN PUBLIC KEY-----\nFAKEB\n-----END PUBLIC KEY-----"
FAKE_PAYLOAD = '{"msg_type": "intercom", "payload": {}}'


@pytest.fixture()
def store(tmp_path):
    """Return a RendezvousStore backed by a temp file."""
    return RendezvousStore(store_name="test_rendezvous", data_dir=str(tmp_path))


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


def test_a_non_positive_ttl_is_refused(store):
    """Storing an already-expired message and reporting success is silent loss.

    This previously returned a deposit id for mail that could never be
    collected, and the old test asserted that as intended behaviour.
    """
    with pytest.raises(ValueError):
        store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=0)
    with pytest.raises(ValueError):
        store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=-1)


def test_ttl_expiry(store):
    """An expired message is never handed out, sweep interval or not."""
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=1)
    time.sleep(1.1)
    assert store.collect(FAKE_PUBKEY_A) == []


def test_expiry_is_per_mailbox_not_only_on_sweep(store):
    """Expiry must not depend on the periodic full-store sweep having run.

    The sweep is throttled to keep request cost off total stored volume, so
    freshness has to be enforced when the mailbox is read as well.
    """
    store._sweep_interval = 10_000  # ensure the global sweep cannot run
    store._last_sweep = time.time()
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=1)
    time.sleep(1.1)
    assert store.collect(FAKE_PUBKEY_A) == []


def test_pending_count_ignores_expired(store):
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=1)
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=3600)
    time.sleep(1.1)
    assert store.pending_count(FAKE_PUBKEY_A) == 1


def test_ttl_capped_at_max(store):
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD, ttl=_MAX_TTL_SECONDS * 10)
    entry = store._db[address_fingerprint(FAKE_PUBKEY_A)][0]
    assert entry["expires_at"] <= time.time() + _MAX_TTL_SECONDS + 2


def test_different_pubkeys_isolated(store):
    store.deposit(FAKE_PUBKEY_A, "msg_a")
    store.deposit(FAKE_PUBKEY_B, "msg_b")
    assert _payloads(store.collect(FAKE_PUBKEY_A)) == ["msg_a"]
    assert _payloads(store.collect(FAKE_PUBKEY_B)) == ["msg_b"]


def test_fingerprint_deterministic():
    assert address_fingerprint(FAKE_PUBKEY_A) == address_fingerprint(FAKE_PUBKEY_A)
    assert address_fingerprint(FAKE_PUBKEY_A) != address_fingerprint(FAKE_PUBKEY_B)


# ---------------------------------------------------------------------------
# The properties a sequential test cannot see
# ---------------------------------------------------------------------------

def test_the_pending_limit_holds_under_concurrency(tmp_path):
    """The limit must be decided under the same lock as the write.

    Checking it in the caller and writing afterwards is check-then-act: N
    concurrent depositors overshoot by up to N-1, which makes the bound
    advisory rather than real.
    """
    import threading
    store = RendezvousStore(store_name="conc", data_dir=str(tmp_path))
    limit = 10
    accepted = []
    barrier = threading.Barrier(20)

    def _dep():
        barrier.wait()
        try:
            accepted.append(store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD,
                                          max_pending=limit))
        except MailboxFull:
            pass

    threads = [threading.Thread(target=_dep) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert store.pending_count(FAKE_PUBKEY_A) <= limit, (
        f"limit={limit} but mailbox holds {store.pending_count(FAKE_PUBKEY_A)}")
    assert len(accepted) <= limit


def test_a_failed_write_does_not_destroy_the_store(tmp_path):
    """A truncate-in-place write loses every mailbox when it fails mid-way,
    and the next read sees a valid empty store — mail gone, no error."""
    store = RendezvousStore(store_name="durable", data_dir=str(tmp_path))
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    store.deposit(FAKE_PUBKEY_B, FAKE_PAYLOAD)

    with patch("hivemind_rendezvous.storage.json.dump",
               side_effect=OSError("No space left on device")):
        with pytest.raises(OSError):
            store.deposit(FAKE_PUBKEY_A, "another")

    reopened = RendezvousStore(store_name="durable", data_dir=str(tmp_path))
    assert len(reopened.collect(FAKE_PUBKEY_A)) == 1
    assert len(reopened.collect(FAKE_PUBKEY_B)) == 1


def test_no_temp_files_are_left_behind_after_a_failed_write(tmp_path):
    import os
    store = RendezvousStore(store_name="tmpclean", data_dir=str(tmp_path))
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    with patch("hivemind_rendezvous.storage.json.dump",
               side_effect=OSError("boom")):
        with pytest.raises(OSError):
            store.deposit(FAKE_PUBKEY_A, "x")
    assert [f for f in os.listdir(tmp_path) if f.startswith(".rendezvous-")] == []


def test_an_unreadable_store_is_set_aside_not_silently_dropped(tmp_path):
    import os
    store = RendezvousStore(store_name="corrupt", data_dir=str(tmp_path))
    store.deposit(FAKE_PUBKEY_A, FAKE_PAYLOAD)
    with open(store.path, "w") as f:
        f.write("{ this is not json")

    reopened = RendezvousStore(store_name="corrupt", data_dir=str(tmp_path))
    assert reopened.collect(FAKE_PUBKEY_A) == []
    salvaged = [f for f in os.listdir(tmp_path) if ".corrupt-" in f]
    assert salvaged, "the unreadable store must be kept for inspection"


def test_the_mailbox_count_is_bounded(tmp_path):
    from hivemind_rendezvous import storage as st
    store = RendezvousStore(store_name="many", data_dir=str(tmp_path))
    with patch.object(st, "MAX_MAILBOXES", 5):
        for i in range(5):
            store.deposit(f"target-{i}", FAKE_PAYLOAD)
        with pytest.raises(MailboxFull) as excinfo:
            store.deposit("one-too-many", FAKE_PAYLOAD)
    assert excinfo.value.reason == "too_many_mailboxes"


def test_an_oversized_payload_is_refused(tmp_path):
    from hivemind_rendezvous.storage import MAX_PAYLOAD_BYTES
    store = RendezvousStore(store_name="big", data_dir=str(tmp_path))
    with pytest.raises(MailboxFull) as excinfo:
        store.deposit(FAKE_PUBKEY_A, "x" * (MAX_PAYLOAD_BYTES + 1))
    assert excinfo.value.reason == "payload_too_large"
