# FAQ — hivemind-rendezvous

## What is hivemind-rendezvous?

An HTTP service that acts as a dead drop: Node A deposits an INTERCOM message
keyed by Node B's RSA public key; Node B retrieves it later by proving it owns
that key. Messages are deleted on delivery.

## Is there rate limiting on deposits?

Yes. A per-IP sliding-window limiter is applied to `POST /deposit` (default: 60
requests/IP/minute).  Excess requests receive HTTP 429 `rate_limit_exceeded`.
Tune via `make_handler(deposit_rate_limit=N, deposit_rate_window=S)`.

## Can depositors be authenticated?

Yes. Include `depositor_pubkey`, `depositor_timestamp`, and `depositor_signature`
in the deposit body.  The server verifies the depositor's proof-of-ownership via
the same `verify_ownership` mechanism used for retrieval.

Enable strict mode (all deposits must be authenticated) with
`make_handler(require_depositor_proof=True)` — anonymous deposits return HTTP 400.

## Is the server TLS-protected?

The server speaks plain HTTP. Deploy behind a TLS-terminating reverse proxy
(nginx, Caddy) in production.  INTERCOM payloads are RSA-encrypted E2E regardless.

## How does proof-of-ownership work?

The client signs `pubkey + str(timestamp_seconds)` with its RSA private key and
sends the base64 signature alongside the timestamp.  The server verifies the
signature and rejects timestamps older than 60 seconds (replay protection).
No server-side challenge state is required — `sign_ownership` / `verify_ownership`
in `hivemind_rendezvous/auth.py`.

## Why must the payload be INTERCOM?

RENDEZVOUS is designed as an async transport for INTERCOM messages — RSA-encrypted
end-to-end payloads.  The rendezvous node cannot read the INTERCOM content.
Depositing BUS or other types is rejected with HTTP 400.

## Where are messages stored?

`JsonStorageXDG` at `~/.local/share/hivemind/rendezvous.json`.  Keys are SHA-256
fingerprints of recipient pubkeys; values are lists of deposit entries with
`expires_at` timestamps.

## What is the default TTL?

7 days.  Clients may request shorter TTLs; the server caps at 7 days.

## What happens when the server restarts?

Messages persisted by `JsonStorageXDG` survive restarts.  Expired messages are
swept on the next deposit or retrieve.

## Does the rendezvous node learn the INTERCOM content?

No. It stores and forwards the serialised `HiveMessage` opaquely.  It does see
the target pubkey fingerprint and deposit metadata.

## What port does the server use?

Default: **6789**.  Override by calling `run_server(port=...)`.

## How does this relate to HiveMessageType.RENDEZVOUS?

`HiveMessageType.RENDEZVOUS` is reserved in `hivemind-websocket-client` but not
dispatched over the WebSocket protocol.  This package is the standalone HTTP
implementation of the rendezvous concept.
