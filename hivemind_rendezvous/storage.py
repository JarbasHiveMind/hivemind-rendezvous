"""Persistent mailbox store for the rendezvous service.

Mail is keyed by the SHA-256 fingerprint of the recipient's mailbox address, so
a raw address never becomes a filename or a dict key.

Delivery is **at-least-once**. ``collect`` returns pending messages and leaves
them in place; they are removed only when the recipient acknowledges the
deposit ids it actually received. A lost response costs a redelivery instead of
the message, which is the right trade for a peer that is offline by definition
and cannot be asked to resend.

Two properties are load-bearing and easy to get wrong:

* **Writes are atomic.** The store is serialised to a temporary file in the
  same directory, fsynced, and then ``os.replace``d over the real one. A
  truncate-in-place write loses *every* mailbox if the process dies or the disk
  fills mid-write, and the reader that follows sees a valid, empty store — mail
  gone with no error anywhere.
* **Limits are enforced under the same lock as the write.** Checking a limit in
  the caller and writing afterwards is a check-then-act race: N concurrent
  depositors overshoot it by up to N-1, so the bound is advisory rather than
  real. ``deposit`` therefore takes ``max_pending`` and decides while holding
  the lock.
"""

import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
from typing import Dict, Iterable, List, Optional, Tuple

from json_database.xdg_utils import xdg_data_home
from ovos_utils.log import LOG

_DEFAULT_TTL_SECONDS: int = 7 * 24 * 3600
_MAX_TTL_SECONDS: int = 7 * 24 * 3600

# How often the whole store is walked for expiry.
_SWEEP_INTERVAL_SECONDS: int = 300

#: Largest single deposit accepted, in bytes. A mailbox bounded only by message
#: count is not bounded at all: 256 messages of 20 MB is 5 GB.
MAX_PAYLOAD_BYTES: int = 256 * 1024

#: Largest number of distinct mailboxes held at once. The address of a mailbox
#: is chosen by the depositor, so without this one peer can create them without
#: limit.
MAX_MAILBOXES: int = 4096


class MailboxFull(Exception):
    """Raised when a deposit would exceed a limit. Carries a machine-readable
    ``reason`` so the caller can report which limit was hit."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def address_fingerprint(address: str) -> str:
    """Return the SHA-256 hex fingerprint of a mailbox address."""
    return hashlib.sha256(address.encode("utf-8")).hexdigest()


class RendezvousStore:
    """Persistent mailbox store with atomic writes.

    Args:
        store_name: Base name of the JSON file under the XDG data dir.
        sweep_interval: Seconds between full-store expiry sweeps.
        data_dir: Override the directory (tests).
    """

    def __init__(self, store_name: str = "rendezvous",
                 sweep_interval: int = _SWEEP_INTERVAL_SECONDS,
                 data_dir: Optional[str] = None) -> None:
        """Initialise the store, loading any previously persisted mail."""
        folder = data_dir or os.path.join(xdg_data_home(), "hivemind")
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, f"{store_name}.json")
        self._lock = threading.RLock()
        self._sweep_interval = sweep_interval
        self._last_sweep: float = 0.0
        self._db: Dict[str, List[dict]] = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> Dict[str, List[dict]]:
        """Read the store, tolerating absence but never silently losing mail.

        A corrupt file is moved aside rather than discarded: coming up with an
        empty store and no trace is how mail disappears without anyone
        noticing.
        """
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("store is not an object")
            return data
        except Exception:
            salvage = f"{self.path}.corrupt-{int(time.time())}"
            try:
                os.replace(self.path, salvage)
            except OSError:
                LOG.exception("could not set aside the unreadable store")
            LOG.error("rendezvous store was unreadable and was moved to %s; "
                      "starting empty", salvage)
            return {}

    def _persist(self) -> None:
        """Write the store atomically. Caller holds ``_lock``."""
        folder = os.path.dirname(self.path)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".rendezvous-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._db, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except Exception:
            # Leave the previous file untouched. A failed write must not be
            # the reason every mailbox disappears.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deposit(self, target: str, payload: str,
                ttl: int = _DEFAULT_TTL_SECONDS,
                max_pending: Optional[int] = None) -> str:
        """Store a message for *target*.

        Args:
            target: Mailbox address of the recipient.
            payload: Serialised ``HiveMessage`` string.
            ttl: Seconds until expiry; must be positive, capped at one week.
            max_pending: Refuse if the mailbox already holds this many live
                messages. Checked under the same lock as the write.

        Returns:
            A UUID string identifying the deposit.

        Raises:
            ValueError: ``ttl`` is not a positive integer.
            MailboxFull: a limit would be exceeded.
        """
        try:
            ttl = int(ttl)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("ttl must be an integer")
        if ttl <= 0:
            # Accepting it would return a deposit id for a message that is
            # already expired — a success receipt for silent loss.
            raise ValueError("ttl must be positive")

        if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise MailboxFull("payload_too_large")

        with self._lock:
            self._maybe_sweep()
            fingerprint = address_fingerprint(target)
            mailbox = self._expired_removed(fingerprint)
            if max_pending is not None and len(mailbox) >= max_pending:
                raise MailboxFull("mailbox_full")
            if fingerprint not in self._db and len(self._db) >= MAX_MAILBOXES:
                raise MailboxFull("too_many_mailboxes")

            deposit_id = str(uuid.uuid4())
            mailbox.append({
                "deposit_id": deposit_id,
                "payload": payload,
                "expires_at": time.time() + min(ttl, _MAX_TTL_SECONDS),
            })
            self._db[fingerprint] = mailbox
            self._persist()
            return deposit_id

    def collect(self, target: str) -> List[Tuple[str, str]]:
        """Return pending messages for *target* without deleting them."""
        with self._lock:
            self._maybe_sweep()
            fingerprint = address_fingerprint(target)
            mailbox = self._expired_removed(fingerprint)
            if mailbox != self._db.get(fingerprint, []):
                self._db[fingerprint] = mailbox
                self._persist()
            return [(e["deposit_id"], e["payload"]) for e in mailbox]

    def ack(self, target: str, deposit_ids: Iterable[str]) -> int:
        """Delete acknowledged deposits from *target*'s mailbox.

        Unknown ids are ignored, so a client that retries an ack it is unsure
        about is never punished for it.
        """
        wanted = set(deposit_ids)
        if not wanted:
            return 0
        with self._lock:
            fingerprint = address_fingerprint(target)
            mailbox = self._expired_removed(fingerprint)
            keep = [e for e in mailbox if e["deposit_id"] not in wanted]
            removed = len(mailbox) - len(keep)
            if keep:
                self._db[fingerprint] = keep
            else:
                self._db.pop(fingerprint, None)
            self._persist()
            return removed

    def pending_count(self, target: str) -> int:
        """Return how many live messages are waiting for *target*."""
        with self._lock:
            return len(self._expired_removed(address_fingerprint(target)))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _expired_removed(self, fingerprint: str) -> List[dict]:
        """One mailbox's live entries. Does not persist.

        A missing ``expires_at`` counts as expired: fail closed rather than
        keep an entry forever because it was written wrong.
        """
        now = time.time()
        return [e for e in self._db.get(fingerprint, [])
                if e.get("expires_at", 0) > now]

    def _maybe_sweep(self) -> None:
        """Evict expired entries store-wide, at most once per interval."""
        now = time.time()
        if now - self._last_sweep < self._sweep_interval:
            return
        self._last_sweep = now
        changed = False
        for fingerprint in list(self._db.keys()):
            live = [e for e in self._db[fingerprint]
                    if e.get("expires_at", 0) > now]
            if len(live) != len(self._db[fingerprint]):
                changed = True
                if live:
                    self._db[fingerprint] = live
                else:
                    del self._db[fingerprint]
        if changed:
            self._persist()
