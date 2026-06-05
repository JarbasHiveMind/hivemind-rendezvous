# Deploy

The relay is a single always-on HTTP service. Run it anywhere the intermittent
nodes can reach over HTTP — a small VPS, a Raspberry Pi, or any spare box.

## Run

```bash
hivemind-rendezvous
# Rendezvous server listening on 0.0.0.0:6789
```

Equivalent module form:

```bash
python -m hivemind_rendezvous.server
```

## Configuration

The console script starts with defaults. To customise, call `run_server()`:

```python
from hivemind_rendezvous.server import run_server

run_server(
    host="0.0.0.0",
    port=6789,
    node_pubkey=open("relay_pubkey.pem").read(),
    deposit_rate_limit=60,
    deposit_rate_window=60,
    require_depositor_proof=False,
)
```

| Argument | Default | Description |
| --- | --- | --- |
| `host` | `0.0.0.0` | Bind address. |
| `port` | `6789` | Listen port. |
| `store` | new default store | A `RendezvousStore` instance; one is created if omitted. |
| `node_pubkey` | `""` | Relay RSA pubkey (PEM); served at `/pubkey` and bound into proofs. |
| `deposit_rate_limit` | `60` | Max deposits per client IP per window. |
| `deposit_rate_window` | `60` | Rate-limit window in seconds. |
| `require_depositor_proof` | `False` | Require a verified depositor proof on every deposit. |

## Storage

Pending messages are persisted via `RendezvousStore` (backed by `json-database`),
so the relay survives restarts. Each message carries an expiry; expired messages
are swept on access. The TTL is set per deposit and capped at 7 days.

## TLS

The service speaks plain HTTP. For deployments over untrusted networks, terminate
TLS in front of it (a reverse proxy such as nginx or Caddy) rather than exposing
port 6789 directly. Message payloads are already end-to-end encrypted to the
recipient pubkey; TLS additionally protects the proof exchange and metadata in
transit.

## Pointing nodes at the relay

Each node needs the relay's URL and its `/pubkey`. Fetch the pubkey once:

```bash
curl http://relay.example.org:6789/pubkey
```

Use that pubkey as `server_pubkey` when signing ownership proofs.
