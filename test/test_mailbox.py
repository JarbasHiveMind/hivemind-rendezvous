"""Mailbox semantics — at-least-once delivery and mailbox binding."""

import tempfile
import unittest
from unittest.mock import patch

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_rendezvous.mailbox import RendezvousMailbox
from hivemind_rendezvous.storage import RendezvousStore

ALICE = "-----BEGIN PUBLIC KEY-----\nALICE\n-----END PUBLIC KEY-----"
BOB = "-----BEGIN PUBLIC KEY-----\nBOB\n-----END PUBLIC KEY-----"


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
        with patch("hivemind_rendezvous.storage.xdg_data_home",
                   return_value=self._tmp.name):
            store = RendezvousStore(store_name="test_rendezvous")
        self.mailbox = RendezvousMailbox(store=store)

    def deposit(self, target=BOB, payload=None, **kw):
        return self.mailbox.handle(
            _req("deposit", target_pubkey=target,
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
        reply = self.mailbox.handle(_req("collect", pubkey=BOB), ALICE)
        self.assertEqual(reply.payload["messages"], [])

    def test_collect_does_not_delete(self):
        # the whole point: a reply lost in transit must cost a redelivery,
        # not the message, because the peer is offline by definition
        self.deposit()
        self.mailbox.handle(_req("collect"), BOB)
        again = self.mailbox.handle(_req("collect"), BOB)
        self.assertEqual(len(again.payload["messages"]), 1)

    def test_an_unpinned_connection_has_no_mailbox(self):
        reply = self.mailbox.handle(_req("collect"), None)
        self.assertEqual(reply.payload["reason"], "no_pinned_pubkey")


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
