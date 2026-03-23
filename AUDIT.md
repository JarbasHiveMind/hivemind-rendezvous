# Audit — hivemind-rendezvous

## Known Issues / Technical Debt

### AUDIT-001 — No rate limiting on deposit endpoint
**File**: `hivemind_rendezvous/server.py` (entire deposit handler)
**Severity**: Medium
**Detail**: Any node can spam deposits for any target pubkey, filling the store.
**Mitigation path**: Add per-depositing-IP or per-pubkey-fingerprint rate limiting.

### AUDIT-002 — `JsonStorageXDG` holds entire store in memory
**File**: `hivemind_rendezvous/storage.py:47`
**Severity**: Low (PoC scope)
**Detail**: All messages for all mailboxes are loaded into a single in-memory dict on startup.
**Mitigation path**: Migrate to `hivemind-plugin-manager` DB backend when volume warrants it.

### AUDIT-003 — No TLS / HTTPS
**File**: `hivemind_rendezvous/server.py:197`
**Severity**: Medium
**Detail**: `HTTPServer` serves plain HTTP. Deposit metadata (target pubkey fingerprint) is visible to network observers. INTERCOM payloads are E2E-encrypted but metadata leaks.
**Mitigation path**: Wrap with `ssl.wrap_socket` or deploy behind a TLS-terminating proxy.

### AUDIT-004 — No authentication on deposit
**File**: `hivemind_rendezvous/server.py:76`
**Severity**: Low
**Detail**: Any party knowing a target pubkey can deposit a (valid INTERCOM) message. Intended by design for open dead-drop semantics, but could be abused.
**Mitigation path**: Optional depositor proof-of-ownership (symmetric with retrieve).
