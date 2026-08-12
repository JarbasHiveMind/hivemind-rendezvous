"""The rendezvous mailbox, driven by ``RENDEZVOUS`` messages.

A rendezvous node is an ordinary hivemind-core node that happens to hold mail.
Two peers that are never online at the same time both connect to it at their
own convenience: one deposits an INTERCOM message addressed to the other's
public key, the other collects it later.

Everything this module needs from the transport, the hive already provides:

* **Authentication** is the session. hivemind-core hands us the access key the
  connection authenticated with, and that — not anything in the request — is
  the mailbox. A caller cannot ask for someone else's. There is nothing to
  sign, no timestamp to check, and therefore no replay window.

  The address is deliberately the access key and not a public key. A public
  key carries no proof of possession at this layer: it is announced in HELLO
  and is public by design (it is the INTERCOM addressing key), so owning a
  mailbox by naming one would let any admitted client claim any other's mail.
* **Confidentiality** is the link (wss, or the Noise transport on v3). A
  deposited INTERCOM envelope is normally also end-to-end encrypted to the
  recipient, but that is the depositor's doing: accepting only the INTERCOM
  *type* does not make a payload encrypted, and this relay does not pretend to
  verify that it is. What it guarantees is that it never tries to read one.
* **Admission and flood control** are the listener's: an unknown client never
  reaches this code.

Delivery is at-least-once. ``collect`` hands out messages and leaves them
stored; they are dropped only when the recipient acks the deposit ids it
actually received. A duplicate is recoverable, a message deleted before it
arrived is not, and this peer is by definition unreachable for a resend.
"""

import logging
from typing import Any, Dict, Optional

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_rendezvous.storage import MailboxFull, RendezvousStore

logger = logging.getLogger(__name__)

#: One week, matching the store's own cap.
DEFAULT_TTL_SECONDS: int = 7 * 24 * 3600


class RendezvousMailbox:
    """Serves ``RENDEZVOUS`` requests against a :class:`RendezvousStore`.

    Args:
        store: Where mail is kept. A default store is created if omitted.
        max_pending_per_mailbox: Refuse deposits once a mailbox holds this
            many messages. An authenticated peer is not automatically a
            well-behaved one, and an unbounded mailbox is a disk-filling
            attack that also denies the owner their real mail.
    """

    def __init__(self, store: Optional[RendezvousStore] = None,
                 max_pending_per_mailbox: int = 256) -> None:
        """Initialise the mailbox service."""
        self.store = store or RendezvousStore()
        self.max_pending_per_mailbox = max_pending_per_mailbox

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, message: HiveMessage, owner: Optional[str]
               ) -> HiveMessage:
        """Serve one ``RENDEZVOUS`` request and return the reply.

        Args:
            message: The inbound ``RENDEZVOUS`` message.
            owner: The access key the transport authenticated this caller
                with. ``None`` or empty makes every command unserviceable:
                there is no mailbox without a proven identity.

        Returns:
            A ``RENDEZVOUS`` message whose payload carries ``status`` and, on
            success, the command's result.
        """
        payload: Dict[str, Any] = message.payload if isinstance(message.payload, dict) else {}
        cmd = payload.get("cmd")

        if not owner:
            # empty is as unusable as absent, and servicing it would give every
            # identity-less caller the same shared mailbox
            return self._reply("error", reason="no_client_identity")

        if cmd == "deposit":
            return self._deposit(payload)
        if cmd == "collect":
            return self._collect(owner)
        if cmd == "ack":
            return self._ack(owner, payload)
        return self._reply("error", reason="unknown_command")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _deposit(self, payload: Dict[str, Any]) -> HiveMessage:
        """Store a message for a recipient named by mailbox address."""
        target = payload.get("target_key")
        serialized = payload.get("payload")
        if not target or not isinstance(target, str) or not serialized:
            return self._reply("error", reason="missing_fields")
        if not isinstance(serialized, str):
            return self._reply("error", reason="invalid_payload")

        try:
            inner = HiveMessage.deserialize(serialized)
        except Exception as exc:
            logger.warning("deposit: undeserialisable payload: %s", exc)
            return self._reply("error", reason="invalid_payload")

        # Only INTERCOM is accepted, because it is the one type whose payload
        # this relay has no reason to look inside. That is a routing rule, not
        # a confidentiality guarantee — nothing here can tell an encrypted
        # envelope from a cleartext dict, and it does not try.
        if inner.msg_type != HiveMessageType.INTERCOM:
            return self._reply("error", reason="payload_must_be_intercom")

        try:
            deposit_id = self.store.deposit(
                target, serialized,
                ttl=payload.get("ttl", DEFAULT_TTL_SECONDS),
                max_pending=self.max_pending_per_mailbox)
        except ValueError:
            # a non-integer or non-positive ttl is attacker-supplied input,
            # not a server fault: report it instead of raising out of handle()
            return self._reply("error", reason="invalid_ttl")
        except MailboxFull as full:
            return self._reply("error", reason=full.reason)
        return self._reply("ok", deposit_id=deposit_id)

    def _collect(self, owner: str) -> HiveMessage:
        """Return the caller's pending mail, leaving it stored until acked."""
        pending = self.store.collect(owner)
        return self._reply("ok", messages=[
            {"deposit_id": did, "payload": raw} for did, raw in pending
        ])

    def _ack(self, owner: str, payload: Dict[str, Any]) -> HiveMessage:
        """Drop the deposits the caller confirms it received."""
        deposit_ids = payload.get("deposit_ids")
        if not isinstance(deposit_ids, list):
            return self._reply("error", reason="missing_fields")
        removed = self.store.ack(owner, [str(d) for d in deposit_ids])
        return self._reply("ok", removed=removed)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reply(status: str, **fields: Any) -> HiveMessage:
        """Build a ``RENDEZVOUS`` reply carrying *status* and *fields*."""
        return HiveMessage(HiveMessageType.RENDEZVOUS,
                           payload={"status": status, **fields})
