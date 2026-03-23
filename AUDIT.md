# Audit — hivemind-rendezvous

## Known Issues / Technical Debt

### AUDIT-001 — Rate limiting on deposit endpoint ✅ RESOLVED
**File**: `hivemind_rendezvous/server.py:55` (`_RateLimiter`)
**Resolution**: Per-IP sliding-window rate limiter added.  Default: 60 deposits/IP/minute.
Configurable via `make_handler(deposit_rate_limit=N, deposit_rate_window=S)` and
`run_server(deposit_rate_limit=N, deposit_rate_window=S)`.  Excess deposits return HTTP 429.

### AUDIT-002 — `JsonStorageXDG` holds entire store in memory
**File**: `hivemind_rendezvous/storage.py:47`
**Severity**: Low (PoC scope)
**Detail**: All messages for all mailboxes are loaded into a single in-memory dict on startup.
**Mitigation path**: Migrate to `hivemind-plugin-manager` DB backend when volume warrants it.

### AUDIT-003 — No TLS / HTTPS
**File**: `hivemind_rendezvous/server.py` (module docstring)
**Severity**: Medium
**Recommendation**: Deploy behind a TLS-terminating reverse proxy (nginx, Caddy).
See `docs/index.md` for example nginx configuration snippet.
INTERCOM payloads are E2E-encrypted regardless; only deposit metadata (fingerprint)
is exposed to a passive network observer.

### AUDIT-004 — No authentication on deposit ✅ RESOLVED
**File**: `hivemind_rendezvous/server.py:130`
**Resolution**: Optional depositor proof-of-ownership added.  Deposit requests may
include ``depositor_pubkey`` + ``depositor_timestamp`` + ``depositor_signature``; the
server verifies the proof before accepting.  Strict mode (``require_depositor_proof=True``)
rejects all anonymous deposits with HTTP 400.
