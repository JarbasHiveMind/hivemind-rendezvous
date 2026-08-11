"""The rendezvous mailbox, driven by ``RENDEZVOUS`` messages.

A rendezvous node is an ordinary hivemind-core node that happens to hold mail.
Two peers that are never online at the same time both connect to it at their
own convenience: one deposits an INTERCOM message addressed to the other's
public key, the other collects it later.

Everything this module needs from the transport, the hive already provides:

* **Authentication** is the session. The connection completed a handshake and
  the node's public key was TOFU-pinned at that point, so a caller cannot ask
  for a mailbox — it only ever gets its own. There is nothing to sign, no
  timestamp to check, and therefore no replay window.
* **Confidentiality** is the link (wss, or the Noise transport on v3), on top
  of the end-to-end encryption the deposited INTERCOM envelope already carries.
  The relay never holds a key that can open one.
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

from hivemind_rendezvous.storage import RendezvousStore

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

    def handle(self, message: HiveMessage, owner_pubkey: Optional[str]
               ) -> HiveMessage:
        """Serve one ``RENDEZVOUS`` request and return the reply.

        Args:
            message: The inbound ``RENDEZVOUS`` message.
            owner_pubkey: The calling node's TOFU-pinned public key, as the
                transport authenticated it. ``None`` when the connection has
                no pinned key, which makes every command unserviceable —
                there is no mailbox to name.

        Returns:
            A ``RENDEZVOUS`` message whose payload carries ``status`` and, on
            success, the command's result.
        """
        payload: Dict[str, Any] = message.payload if isinstance(message.payload, dict) else {}
        cmd = payload.get("cmd")

        if owner_pubkey is None:
            return self._reply("error", reason="no_pinned_pubkey")

        if cmd == "deposit":
            return self._deposit(payload)
        if cmd == "collect":
            return self._collect(owner_pubkey)
        if cmd == "ack":
            return self._ack(owner_pubkey, payload)
        return self._reply("error", reason="unknown_command")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _deposit(self, payload: Dict[str, Any]) -> HiveMessage:
        """Store an INTERCOM message for a recipient named by public key."""
        target = payload.get("target_pubkey")
        serialized = payload.get("payload")
        if not target or not serialized:
            return self._reply("error", reason="missing_fields")

        try:
            inner = HiveMessage.deserialize(serialized)
        except Exception as exc:
            logger.warning("deposit: undeserialisable payload: %s", exc)
            return self._reply("error", reason="invalid_payload")

        # Only INTERCOM is accepted. It is the one type that is already
        # end-to-end encrypted to a named public key, so the relay can hold it
        # without ever being able to read it. Anything else would arrive here
        # in a form this node could inspect, which is not what a dead drop is.
        if inner.msg_type != HiveMessageType.INTERCOM:
            return self._reply("error", reason="payload_must_be_intercom")

        if self.store.pending_count(target) >= self.max_pending_per_mailbox:
            return self._reply("error", reason="mailbox_full")

        ttl = int(payload.get("ttl", DEFAULT_TTL_SECONDS))
        deposit_id = self.store.deposit(target, serialized, ttl=ttl)
        return self._reply("ok", deposit_id=deposit_id)

    def _collect(self, owner_pubkey: str) -> HiveMessage:
        """Return the caller's pending mail, leaving it stored until acked."""
        pending = self.store.collect(owner_pubkey)
        return self._reply("ok", messages=[
            {"deposit_id": did, "payload": raw} for did, raw in pending
        ])

    def _ack(self, owner_pubkey: str, payload: Dict[str, Any]) -> HiveMessage:
        """Drop the deposits the caller confirms it received."""
        deposit_ids = payload.get("deposit_ids")
        if not isinstance(deposit_ids, list):
            return self._reply("error", reason="missing_fields")
        removed = self.store.ack(owner_pubkey, [str(d) for d in deposit_ids])
        return self._reply("ok", removed=removed)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reply(status: str, **fields: Any) -> HiveMessage:
        """Build a ``RENDEZVOUS`` reply carrying *status* and *fields*."""
        return HiveMessage(HiveMessageType.RENDEZVOUS,
                           payload={"status": status, **fields})
