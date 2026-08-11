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
