"""Persistent message store for the rendezvous service.

Messages are keyed by the SHA-256 fingerprint of the recipient's public key, so
a full PEM never becomes a dict key. Each mailbox is a list of deposit entries.

Delivery is **at-least-once**. ``collect`` returns pending messages and leaves
them in place; they are removed only when the recipient acknowledges the
deposit ids it actually received. A lost response therefore costs a redelivery
instead of the message. The recipient may see a message twice, which is the
correct trade for a dead-drop: the whole point is that the peer is offline and
unreachable, so a message destroyed in transit can never be resent.

Every public method holds ``_lock``, because the HTTP front end serves requests
on a thread pool and two deposits into one mailbox would otherwise interleave a
read-modify-write.
"""

import hashlib
import threading
import time
import uuid
from typing import Dict, Iterable, List, Tuple

from json_database import JsonStorageXDG
from json_database.xdg_utils import xdg_data_home

_DEFAULT_TTL_SECONDS: int = 7 * 24 * 3600  # 7 days
_MAX_TTL_SECONDS: int = 7 * 24 * 3600

# How often the whole store is walked for expiry. Sweeping every mailbox on
# every request made request cost grow with total stored volume rather than
# with the size of the mailbox being touched.
_SWEEP_INTERVAL_SECONDS: int = 300


def pubkey_fingerprint(pubkey: str) -> str:
    """Return the SHA-256 hex fingerprint of a PEM-encoded public key.

    Args:
        pubkey: PEM-encoded RSA public key string.

    Returns:
        Lowercase hex SHA-256 digest usable as a dict key.
    """
    return hashlib.sha256(pubkey.encode("utf-8")).hexdigest()


class RendezvousStore:
    """Persistent mailbox store backed by :class:`json_database.JsonStorageXDG`.

    Args:
        store_name: Base name of the underlying JSON file.
        sweep_interval: Seconds between full-store expiry sweeps.
    """

    def __init__(self, store_name: str = "rendezvous",
                 sweep_interval: int = _SWEEP_INTERVAL_SECONDS) -> None:
        """Initialise the store, loading any previously persisted messages."""
        self._db: JsonStorageXDG = JsonStorageXDG(
            name=store_name,
            xdg_folder=xdg_data_home(),
            subfolder="hivemind",
        )
        self._lock = threading.RLock()
        self._sweep_interval = sweep_interval
        self._last_sweep: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deposit(self, target_pubkey: str, payload: str,
                ttl: int = _DEFAULT_TTL_SECONDS) -> str:
        """Store a serialised message for *target_pubkey*.

        Args:
            target_pubkey: PEM-encoded RSA public key of the intended recipient.
            payload: Serialised ``HiveMessage`` string.
            ttl: Time-to-live in seconds; capped at one week.

        Returns:
            A UUID string identifying the deposit (``deposit_id``).
        """
        with self._lock:
            self._maybe_sweep()
            fingerprint = pubkey_fingerprint(target_pubkey)
            deposit_id = str(uuid.uuid4())
            mailbox: List[dict] = self._expired_removed(fingerprint)
            mailbox.append({
                "deposit_id": deposit_id,
                "payload": payload,
                "expires_at": time.time() + min(ttl, _MAX_TTL_SECONDS),
            })
            self._db[fingerprint] = mailbox
            self._db.store()
            return deposit_id

    def collect(self, target_pubkey: str) -> List[Tuple[str, str]]:
        """Return pending messages for *target_pubkey* without deleting them.

        The caller must :meth:`ack` the returned deposit ids once the recipient
        has them. Until then the messages stay pending and will be handed out
        again on the next collect.

        Args:
            target_pubkey: PEM-encoded RSA public key of the retrieving node.

        Returns:
            A list of ``(deposit_id, payload)`` pairs, oldest first.
        """
        with self._lock:
            self._maybe_sweep()
            fingerprint = pubkey_fingerprint(target_pubkey)
            mailbox = self._expired_removed(fingerprint)
            if mailbox:
                self._db[fingerprint] = mailbox
                self._db.store()
            return [(e["deposit_id"], e["payload"]) for e in mailbox]

    def ack(self, target_pubkey: str, deposit_ids: Iterable[str]) -> int:
        """Delete acknowledged deposits from *target_pubkey*'s mailbox.

        Unknown ids are ignored: an ack replayed after the entries are already
        gone is a no-op rather than an error, so a client that retries an ack
        it is unsure about cannot be punished for it.

        Args:
            target_pubkey: PEM-encoded RSA public key of the mailbox owner.
            deposit_ids: Deposit ids the recipient confirms it received.

        Returns:
            How many entries were actually removed.
        """
        wanted = set(deposit_ids)
        if not wanted:
            return 0
        with self._lock:
            fingerprint = pubkey_fingerprint(target_pubkey)
            mailbox = self._expired_removed(fingerprint)
            keep = [e for e in mailbox if e["deposit_id"] not in wanted]
            removed = len(mailbox) - len(keep)
            if keep:
                self._db[fingerprint] = keep
            else:
                self._db.pop(fingerprint, None)
            self._db.store()
            return removed

    def pending_count(self, target_pubkey: str) -> int:
        """Return how many live messages are waiting for *target_pubkey*."""
        with self._lock:
            return len(self._expired_removed(pubkey_fingerprint(target_pubkey)))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _expired_removed(self, fingerprint: str) -> List[dict]:
        """Return one mailbox's live entries. Does not persist."""
        now = time.time()
        return [e for e in self._db.get(fingerprint, [])
                if e.get("expires_at", 0) > now]

    def _maybe_sweep(self) -> None:
        """Evict expired entries store-wide, at most once per sweep interval."""
        now = time.time()
        if now - self._last_sweep < self._sweep_interval:
            return
        self._last_sweep = now
        changed = False
        live_by_fp: Dict[str, List[dict]] = {}
        for fingerprint in list(self._db.keys()):
            live = [e for e in self._db[fingerprint]
                    if e.get("expires_at", 0) > now]
            if len(live) != len(self._db[fingerprint]):
                changed = True
                live_by_fp[fingerprint] = live
        for fingerprint, live in live_by_fp.items():
            if live:
                self._db[fingerprint] = live
            else:
                del self._db[fingerprint]
        if changed:
            self._db.store()
