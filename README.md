# hivemind-rendezvous

An async store-and-forward dead-drop rendezvous service for HiveMind nodes. Enables two nodes from different, non-simultaneously-connected hives to exchange INTERCOM messages via a shared rendezvous point — without knowing each other's IP address or maintaining a simultaneous connection.

## How it works

Node A deposits an INTERCOM message keyed by Node B's RSA public key at a rendezvous server. The message is stored with a TTL (default 7 days) and deleted on retrieval (at-most-once delivery). Node B later proves it owns the target key via a signed timestamp, retrieves the message, and the server deletes it. The rendezvous node never sees plaintext — INTERCOM payloads are end-to-end RSA-encrypted; the node handles only the opaque serialized message and the recipient's pubkey fingerprint.

```
Node A (sender)    Rendezvous node     Node B (recipient)
     |                   |                    |
     |-- POST /deposit -->|                    |
     |   INTERCOM msg     |                    |
     |   target=B.pubkey  |  (stored, TTL 7d)  |
     |                   |                    |
     |           (time passes)                |
     |                   |<-- POST /retrieve --|
     |                   |    sign(B.privkey)  |
     |                   |-- messages -------->|
     |                   |   (deleted)         |
```

## Installation

```bash
pip install hivemind-rendezvous
```

Or in development mode:

```bash
pip install -e .
```

## Quick Start

### Start the server

```bash
hivemind-rendezvous
```

The server listens on `0.0.0.0:6789` by default and stores messages at `~/.local/share/hivemind/rendezvous.json`.

### Programmatic usage

```python
from hivemind_rendezvous.server import run_server
from hivemind_rendezvous.storage import RendezvousStore
from poorman_handshake.asymmetric.utils import create_RSA_key

# Create keys
server_pubkey, server_privkey = create_RSA_key(2048)
node_b_pubkey, node_b_privkey = create_RSA_key(2048)

# Create store and start server
store = RendezvousStore(store_name="my_rendezvous")
run_server(port=6789, store=store, node_pubkey=server_pubkey)
```

## Public API

### `RendezvousStore`

Persistent mailbox store backed by `JsonStorageXDG` (at `~/.local/share/hivemind/rendezvous.json`).

```python
from hivemind_rendezvous.storage import RendezvousStore

store = RendezvousStore(store_name="rendezvous")

# Deposit a message
deposit_id = store.deposit(
    target_pubkey=node_b_pubkey_pem,
    payload=serialized_intercom_message,
    ttl=604800  # 7 days (optional; capped at 7 days)
)

# Retrieve messages (deletes them immediately)
messages = store.retrieve(target_pubkey=node_b_pubkey_pem)  # List[str]
```

### `make_handler` and `run_server`

Factory function to create a bound HTTP handler and blocking server entrypoint.

```python
from hivemind_rendezvous.server import make_handler, run_server
from hivemind_rendezvous.storage import RendezvousStore

store = RendezvousStore()
handler_cls = make_handler(
    store=store,
    node_pubkey=server_pubkey_pem,
    deposit_rate_limit=60,            # max deposits per IP per window
    deposit_rate_window=60,           # window in seconds
    require_depositor_proof=False     # enforce depositor authentication?
)

# Or use run_server directly
run_server(
    host="0.0.0.0",
    port=6789,
    store=store,
    node_pubkey=server_pubkey_pem,
    deposit_rate_limit=60,
    deposit_rate_window=60,
    require_depositor_proof=False
)
```

### `sign_ownership` and `verify_ownership`

Stateless proof-of-pubkey-ownership authentication.

```python
from hivemind_rendezvous.auth import sign_ownership, verify_ownership
import time

# Client-side: produce ownership proof
timestamp = int(time.time())
signature = sign_ownership(
    private_key=my_private_key,
    pubkey=my_pubkey_pem,
    timestamp=timestamp,
    server_pubkey=server_pubkey_pem  # binds proof to this server
)

# Server-side: verify ownership proof
is_valid = verify_ownership(
    pubkey=claimed_pubkey_pem,
    timestamp=timestamp,
    signature=signature,
    server_pubkey=my_server_pubkey_pem
)  # Returns True if signature is valid and timestamp is fresh (±60s)
```

## HTTP Endpoints

All endpoints speak JSON. Requests use `POST` (except `/pubkey`), and responses include a `"status"` field (`"ok"` or `"error"`).

### `GET /pubkey`

Returns this rendezvous node's RSA public key (PEM).

**Response:**
```json
{
  "pubkey": "-----BEGIN RSA PUBLIC KEY-----\n..."
}
```

### `POST /deposit`

Store an INTERCOM message for a recipient pubkey.

**Request body:**
```json
{
  "payload": "<serialized HiveMessage>",
  "target_pubkey": "<recipient RSA pubkey PEM>",
  "ttl": 604800,                          // optional; seconds (capped at 7 days)
  "depositor_pubkey": "...",              // optional; prove who is depositing
  "depositor_timestamp": 1234567890,      // optional
  "depositor_signature": "base64..."      // optional
}
```

**Validation:**
- `payload` must deserialize to a `HiveMessageType.INTERCOM` message.
- If provided, the `depositor_*` fields must form a valid ownership proof.
- If `require_depositor_proof=True` (server config), all three `depositor_*` fields are mandatory.
- Per-IP rate limiting (default 60 deposits/minute) prevents mailbox flooding; excess requests return HTTP 429.

**Success response (HTTP 200):**
```json
{
  "status": "ok",
  "deposit_id": "<UUID>"
}
```

**Error responses:**
- `400 missing_fields` — `payload` or `target_pubkey` not provided.
- `400 invalid_payload` — `payload` does not deserialize.
- `400 payload_must_be_intercom` — `payload` is not an INTERCOM message.
- `400 depositor_proof_required` — Strict mode enabled but no depositor proof supplied.
- `401 invalid_depositor_signature` — Depositor proof verification failed.
- `429 rate_limit_exceeded` — Too many deposits from this IP in the current window.
- `500 storage_error` — Internal storage failure.

### `POST /retrieve`

Prove ownership of a pubkey and retrieve pending messages (deleted on retrieval).

**Request body:**
```json
{
  "pubkey": "<your RSA public key PEM>",
  "timestamp": 1234567890,                // Unix seconds
  "signature": "base64..."                // ownership proof from sign_ownership()
}
```

**Success response (HTTP 200):**
```json
{
  "status": "ok",
  "messages": ["<serialized HiveMessage 1>", "<serialized HiveMessage 2>", ...]
}
```

**Error responses:**
- `400 missing_fields` — Missing `pubkey`, `timestamp`, or `signature`.
- `401 replay_detected` — Timestamp is not within ±60 seconds of now.
- `401 invalid_signature` — Signature verification failed.

## Configuration

### Rate Limiting

Per-IP sliding-window rate limiting is applied to `POST /deposit` to prevent mailbox flooding. Configure via `make_handler()`:

```python
make_handler(
    store=store,
    node_pubkey=node_pubkey,
    deposit_rate_limit=60,      # max deposits per IP
    deposit_rate_window=60      # per this many seconds
)
```

Default: 60 deposits per IP per minute.

### Depositor Authentication

To require that all deposits include a valid depositor proof-of-ownership:

```python
make_handler(
    store=store,
    node_pubkey=node_pubkey,
    require_depositor_proof=True  # enforce depositor authentication
)
```

When enabled, deposits without valid `depositor_pubkey`, `depositor_timestamp`, and `depositor_signature` are rejected with HTTP 400.

### TLS / HTTPS

This server speaks plain HTTP. Deploy behind a TLS-terminating reverse proxy (nginx, Caddy, etc.) in production:

**nginx example:**
```nginx
location / {
    proxy_pass http://127.0.0.1:6789;
}
```

INTERCOM payloads are RSA-encrypted end-to-end, so the server doesn't see plaintext regardless of transport layer security.

## HiveMind Integration

`hivemind-rendezvous` implements the rendezvous concept reserved as `HiveMessageType.RENDEZVOUS` in the HiveMind protocol. It is an offline-transport backend for nodes that cannot hold a live WebSocket session. Combined with `hivemind-bus-client` for INTERCOM serialization, it completes the async-messaging side of distributed HiveMind mesh networks.

## Message Storage

Messages are stored in the filesystem at `~/.local/share/hivemind/rendezvous.json` (customizable via `store_name` parameter). Each mailbox is identified by the SHA-256 fingerprint of the recipient's public key. Expired messages are evicted lazily on every `deposit()` and `retrieve()` call — no background cleanup task is needed.

## Dependencies

- `hivemind-bus-client` — `HiveMessage` / `HiveMessageType` serialization.
- `poorman-handshake` — RSA signing and verification (`sign_RSA`, `verify_RSA`).
- `json-database` — Persistent storage via `JsonStorageXDG`.

## Development & Testing

Install with dev dependencies:

```bash
pip install -e '.[dev]'
```

Run tests:

```bash
pytest tests/ -v
```

Run coverage:

```bash
pytest tests/ --cov=hivemind_rendezvous --cov-report=html
```

## License

Apache License 2.0
