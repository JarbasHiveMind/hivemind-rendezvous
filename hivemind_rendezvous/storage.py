"""Persistent message store for the rendezvous service.

Messages are keyed by SHA-256 fingerprint of the recipient's public key to avoid
storing full PEM strings as dict keys.  Each mailbox is a list of deposit entries.
TTL is checked on every deposit and retrieve; expired messages are evicted lazily.
"""

import hashlib
import time
import uuid
from typing import List

from json_database import JsonStorageXDG
from json_database.xdg_utils import xdg_data_home


_DEFAULT_TTL_SECONDS: int = 7 * 24 * 3600  # 7 days
_MAX_TTL_SECONDS: int = 7 * 24 * 3600


def _pubkey_fingerprint(pubkey: str) -> str:
    """Return the SHA-256 hex fingerprint of a PEM-encoded public key.

    Args:
        pubkey: PEM-encoded RSA public key string.

    Returns:
        Lowercase hex SHA-256 digest usable as a dict key.
    """
    return hashlib.sha256(pubkey.encode("utf-8")).hexdigest()


class RendezvousStore:
    """Persistent mailbox store backed by :class:`json_database.JsonStorageXDG`.

    Each mailbox is identified by the SHA-256 fingerprint of the recipient's
    RSA public key.  Messages are stored with an ``expires_at`` Unix timestamp;
    expired messages are evicted on every read and write.

    Args:
        store_name: Base name of the underlying JSON file (default: ``"rendezvous"``).
    """

    def __init__(self, store_name: str = "rendezvous") -> None:
        """Initialise the store, loading any previously persisted messages."""
        self._db: JsonStorageXDG = JsonStorageXDG(
            name=store_name,
            xdg_folder=xdg_data_home(),
            subfolder="hivemind",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deposit(self, target_pubkey: str, payload: str,
                ttl: int = _DEFAULT_TTL_SECONDS) -> str:
        """Store a serialised INTERCOM message for *target_pubkey*.

        Args:
            target_pubkey: PEM-encoded RSA public key of the intended recipient.
            payload: Serialised :class:`hivemind_bus_client.message.HiveMessage` string.
            ttl: Time-to-live in seconds; capped at :data:`_MAX_TTL_SECONDS`.

        Returns:
            A UUID string identifying the deposit (``deposit_id``).
        """
        ttl = min(ttl, _MAX_TTL_SECONDS)
        fingerprint = _pubkey_fingerprint(target_pubkey)
        deposit_id = str(uuid.uuid4())
        entry = {
            "deposit_id": deposit_id,
            "payload": payload,
            "expires_at": time.time() + ttl,
        }
        self._sweep()
        mailbox: List[dict] = self._db.get(fingerprint, [])
        mailbox.append(entry)
        self._db[fingerprint] = mailbox
        self._db.store()
        return deposit_id

    def retrieve(self, target_pubkey: str) -> List[str]:
        """Return and delete all pending messages for *target_pubkey*.

        Messages are deleted immediately upon retrieval (at-most-once delivery).

        Args:
            target_pubkey: PEM-encoded RSA public key of the retrieving node.

        Returns:
            List of serialised :class:`hivemind_bus_client.message.HiveMessage`
            strings; empty list if no messages are waiting.
        """
        self._sweep()
        fingerprint = _pubkey_fingerprint(target_pubkey)
        mailbox: List[dict] = self._db.pop(fingerprint, [])
        if mailbox:
            self._db.store()
        return [entry["payload"] for entry in mailbox]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sweep(self) -> None:
        """Evict all entries whose ``expires_at`` is in the past.

        Called automatically before every deposit and retrieve so no explicit
        background task is needed.
        """
        now = time.time()
        changed = False
        for fingerprint in list(self._db.keys()):
            live = [e for e in self._db[fingerprint] if e.get("expires_at", 0) > now]
            if len(live) != len(self._db[fingerprint]):
                changed = True
                if live:
                    self._db[fingerprint] = live
                else:
                    del self._db[fingerprint]
        if changed:
            self._db.store()
