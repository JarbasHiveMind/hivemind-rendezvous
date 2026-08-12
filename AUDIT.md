# Audit — hivemind-rendezvous

## Resolved by moving onto the HiveMind protocol

The service used to be a standalone HTTP relay with an authentication scheme of
its own. Serving `RENDEZVOUS` over an authenticated hive session removed the
code those findings were about, rather than patching it.

- **AUDIT-001 / AUDIT-004 — deposit rate limiting and depositor authentication.**
  Admission is the listener's job now. An unknown client never reaches the
  mailbox, so there is no anonymous deposit to throttle or authenticate.
- **AUDIT-003 — no TLS.** The transport is the hive link: `wss`, or the Noise
  transport on protocol v3.
- **Replay window.** The old ownership proof stayed valid for its whole ±60s
  tolerance, so an observer could replay a captured proof to collect and thereby
  delete another node's mail. There is no proof any more: the mailbox is the
  pinned key of the connection, and a request cannot name one.
- **Delete-before-ack.** `retrieve` deleted messages as it returned them, so a
  lost response destroyed the mail permanently. Delivery is now at-least-once:
  `collect` leaves messages pending until the recipient acks them.

## Known issues / technical debt

### AUDIT-002 — the store is held in memory
**File**: `hivemind_rendezvous/storage.py`
**Severity**: Low
**Detail**: `JsonStorageXDG` loads every mailbox into one dict and rewrites the
whole file on each change. Fine at dead-drop volume between a few hives.
**Mitigation path**: move to a `hivemind-plugin-manager` database backend when
volume warrants it.

### AUDIT-005 — a mailbox owner cannot enumerate without collecting
**File**: `hivemind_rendezvous/mailbox.py`
**Severity**: Low
**Detail**: There is no "how much mail is waiting" command, so a client with a
small buffer has to take the whole mailbox in one reply. `max_pending_per_mailbox`
bounds it, but the bound is the relay's, not the client's.
**Mitigation path**: a `peek` command returning counts, or a `limit` field on
`collect`.


## Found by adversarial review, 2026-08-12 — all fixed in this pass

An adversarial review of the claims in the README refuted three of six and
found the rest of these. They are recorded because the tests that were green at
the time detected none of them.

- **AUDIT-006 — the mailbox limit was advisory.** `pending_count` then
  `deposit` took the lock twice, so N concurrent depositors overshot the limit
  by up to N-1 (measured: 40 pending against a limit of 10). The limit is now
  decided inside `deposit`, under the write lock.
- **AUDIT-007 — a malformed `ttl` escaped the handler.** `int(payload["ttl"])`
  sat outside the guard, so `"abc"`, `None`, `[1]` and `1e400` raised out of
  `handle()`, which is documented to always return a reply. Now reported as
  `invalid_ttl`.
- **AUDIT-008 — `ttl<=0` returned a success receipt for a dead message.** The
  old test asserted that as intended behaviour. Non-positive TTLs are refused.
- **AUDIT-009 — writes were not atomic.** `json_database` truncates in place,
  so a full disk or a kill mid-write emptied *every* mailbox, and the next
  start read a valid, empty store with no error. Writes now go to a temp file,
  fsync, then `os.replace`; an unreadable store is set aside rather than
  silently discarded.
- **AUDIT-010 — no size or count caps.** A single 20 MB deposit was accepted;
  at 256 messages that is 5 GB in one mailbox, and mailbox count was unbounded.
  Now `MAX_PAYLOAD_BYTES` and `MAX_MAILBOXES`.
- **AUDIT-011 — `client.py` documented a control that did not exist.** It
  described a `recipient_fingerprint` binding "enforced by
  `hivemind_rendezvous.server`" — a module that had been deleted. The paragraph
  is gone; the module now states plainly that the relay enforces nothing about
  encryption.
- **AUDIT-012 — "only INTERCOM, so the relay cannot read it" was a
  non-sequitur.** The check is on message type; nothing makes an INTERCOM
  payload encrypted, and a cleartext dict was accepted and stored verbatim.
  The claim is corrected in code comments and docs rather than papered over.

Still open: per-request cost scales with total store size, because the whole
store is re-serialised on every write. Acceptable at dead-drop volume, and the
reason the sweep throttle buys less than its comment claims.
