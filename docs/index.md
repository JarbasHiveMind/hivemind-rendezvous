# hivemind-rendezvous

Async store-and-forward dead-drop rendezvous service for HiveMind nodes.

Enables nodes from different, non-simultaneously-connected hives to exchange
[INTERCOM](https://github.com/JarbasHiveMind/hivemind-websocket-client) messages
via a shared rendezvous point — without knowing each other's IP address or
maintaining a simultaneous connection.

## Architecture

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

**No persistent HiveMind session is required.** Proof of RSA pubkey ownership
(signed timestamp) is the only authentication.

## Key Classes and Functions

| Symbol | File | Purpose |
|---|---|---|
| `verify_ownership` | `hivemind_rendezvous/auth.py:44` | Verify signed timestamp proof |
| `sign_ownership` | `hivemind_rendezvous/auth.py:22` | Produce ownership proof (client-side) |
| `RendezvousStore` | `hivemind_rendezvous/storage.py:36` | Persistent mailbox, TTL sweep |
| `run_server` | `hivemind_rendezvous/server.py:197` | Start HTTP server |
| `make_handler` | `hivemind_rendezvous/server.py:175` | Inject store + pubkey into handler |

## HTTP Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/pubkey` | Returns this node's RSA public key (PEM) |
| `POST` | `/deposit` | Store INTERCOM message for a recipient pubkey |
| `POST` | `/retrieve` | Prove ownership and fetch pending messages |

Default port: **6789**.

## Installation

```bash
uv pip install -e hivemind-rendezvous
```

## Running

```bash
uv run python -m hivemind_rendezvous.server
# or
hivemind-rendezvous
```

## Dependencies

- `hivemind-bus-client` — `HiveMessage` serialisation
- `poorman-handshake` — `sign_RSA` / `verify_RSA`
- `json-database` — `JsonStorageXDG` for persistence
