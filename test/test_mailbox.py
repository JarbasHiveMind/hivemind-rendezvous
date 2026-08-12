"""Mailbox semantics — at-least-once delivery and mailbox binding."""

import tempfile
import unittest
from unittest.mock import patch

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_rendezvous.mailbox import RendezvousMailbox
from hivemind_rendezvous.storage import RendezvousStore

# mailbox addresses are access keys, not public keys
ALICE = "alice-access-key"
BOB = "bob-access-key"


def _intercom(text="hi"):
    return HiveMessage(HiveMessageType.INTERCOM,
                       payload={"ciphertext": text}).serialize()


def _req(cmd, **fields):
    return HiveMessage(HiveMessageType.RENDEZVOUS,
                       payload={"cmd": cmd, **fields})


class _MailboxTest(unittest.TestCase):
    def setUp(self):
        # JsonStorageXDG writes to the real XDG data dir and persists across
        # runs, so the store is pointed at a temp dir the test owns
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        store = RendezvousStore(store_name="test_rendezvous",
                                data_dir=self._tmp.name)
        self.mailbox = RendezvousMailbox(store=store)

    def deposit(self, target=BOB, payload=None, **kw):
        return self.mailbox.handle(
            _req("deposit", target_key=target,
                 payload=payload or _intercom(), **kw), ALICE)


class TestDeposit(_MailboxTest):

    def test_deposit_returns_an_id(self):
        reply = self.deposit()
        self.assertEqual(reply.payload["status"], "ok")
        self.assertTrue(reply.payload["deposit_id"])

    def test_only_intercom_is_accepted(self):
        plain = HiveMessage(HiveMessageType.BUS, payload={"type": "speak"}).serialize()
        reply = self.deposit(payload=plain)
        self.assertEqual(reply.payload["reason"], "payload_must_be_intercom")

    def test_undeserialisable_payload_is_refused(self):
        reply = self.deposit(payload="not a serialised message")
        self.assertEqual(reply.payload["reason"], "invalid_payload")

    def test_missing_fields_are_refused(self):
        reply = self.mailbox.handle(_req("deposit"), ALICE)
        self.assertEqual(reply.payload["reason"], "missing_fields")

    def test_a_full_mailbox_is_refused(self):
        self.mailbox.max_pending_per_mailbox = 2
        self.deposit()
        self.deposit()
        self.assertEqual(self.deposit().payload["reason"], "mailbox_full")


class TestCollect(_MailboxTest):

    def test_collect_returns_what_was_deposited(self):
        self.deposit()
        reply = self.mailbox.handle(_req("collect"), BOB)
        self.assertEqual(len(reply.payload["messages"]), 1)

    def test_a_caller_only_ever_sees_its_own_mailbox(self):
        # the request cannot name a mailbox, so Alice asking after depositing
        # for Bob gets her own (empty) box, not his
        self.deposit()
        reply = self.mailbox.handle(_req("collect", target_key=BOB, pubkey=BOB), ALICE)
        self.assertEqual(reply.payload["messages"], [])

    def test_collect_does_not_delete(self):
        # the whole point: a reply lost in transit must cost a redelivery,
        # not the message, because the peer is offline by definition
        self.deposit()
        self.mailbox.handle(_req("collect"), BOB)
        again = self.mailbox.handle(_req("collect"), BOB)
        self.assertEqual(len(again.payload["messages"]), 1)

    def test_a_connection_without_identity_has_no_mailbox(self):
        reply = self.mailbox.handle(_req("collect"), None)
        self.assertEqual(reply.payload["reason"], "no_client_identity")

    def test_an_empty_identity_is_refused_too(self):
        # servicing "" would hand every identity-less caller one shared mailbox
        reply = self.mailbox.handle(_req("collect"), "")
        self.assertEqual(reply.payload["reason"], "no_client_identity")


class TestAck(_MailboxTest):

    def test_ack_removes_only_the_acked_ids(self):
        first = self.deposit().payload["deposit_id"]
        self.deposit()
        reply = self.mailbox.handle(_req("ack", deposit_ids=[first]), BOB)
        self.assertEqual(reply.payload["removed"], 1)
        left = self.mailbox.handle(_req("collect"), BOB)
        self.assertEqual(len(left.payload["messages"]), 1)

    def test_a_replayed_ack_is_harmless(self):
        did = self.deposit().payload["deposit_id"]
        self.mailbox.handle(_req("ack", deposit_ids=[did]), BOB)
        again = self.mailbox.handle(_req("ack", deposit_ids=[did]), BOB)
        self.assertEqual(again.payload["removed"], 0)

    def test_one_node_cannot_ack_anothers_mail(self):
        did = self.deposit().payload["deposit_id"]
        self.mailbox.handle(_req("ack", deposit_ids=[did]), ALICE)
        still_there = self.mailbox.handle(_req("collect"), BOB)
        self.assertEqual(len(still_there.payload["messages"]), 1)

    def test_ack_without_ids_is_refused(self):
        reply = self.mailbox.handle(_req("ack"), BOB)
        self.assertEqual(reply.payload["reason"], "missing_fields")


class TestUnknownCommand(_MailboxTest):

    def test_unknown_command_is_named(self):
        reply = self.mailbox.handle(_req("purge"), BOB)
        self.assertEqual(reply.payload["reason"], "unknown_command")


if __name__ == "__main__":
    unittest.main()


class TestHostileInput(_MailboxTest):
    """handle() is documented to always return a RENDEZVOUS reply. Anything
    that escapes it lands in hivemind-core's message loop instead."""

    def _deposit_ttl(self, ttl):
        return self.mailbox.handle(
            _req("deposit", target_key=BOB, payload=_intercom(), ttl=ttl), ALICE)

    def test_a_non_numeric_ttl_is_reported_not_raised(self):
        self.assertEqual(self._deposit_ttl("abc").payload["reason"], "invalid_ttl")

    def test_a_null_ttl_is_reported_not_raised(self):
        self.assertEqual(self._deposit_ttl(None).payload["reason"], "invalid_ttl")

    def test_a_list_ttl_is_reported_not_raised(self):
        self.assertEqual(self._deposit_ttl([1]).payload["reason"], "invalid_ttl")

    def test_an_overflowing_ttl_is_reported_not_raised(self):
        self.assertEqual(self._deposit_ttl(1e400).payload["reason"], "invalid_ttl")

    def test_a_dead_on_arrival_ttl_is_refused(self):
        # returning ok for a message that is already expired is a success
        # receipt for silent loss
        self.assertEqual(self._deposit_ttl(0).payload["reason"], "invalid_ttl")
        self.assertEqual(self._deposit_ttl(-99999).payload["reason"], "invalid_ttl")

    def test_an_oversized_payload_is_refused(self):
        from hivemind_rendezvous.storage import MAX_PAYLOAD_BYTES
        big = HiveMessage(HiveMessageType.INTERCOM,
                          payload={"ciphertext": "x" * (MAX_PAYLOAD_BYTES + 1024)}).serialize()
        reply = self.mailbox.handle(
            _req("deposit", target_key=BOB, payload=big), ALICE)
        self.assertEqual(reply.payload["reason"], "payload_too_large")

    def test_a_non_string_target_is_refused(self):
        reply = self.mailbox.handle(
            _req("deposit", target_key={"not": "a string"}, payload=_intercom()), ALICE)
        self.assertEqual(reply.payload["reason"], "missing_fields")
