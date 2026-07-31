# hivemind-rendezvous

An async store-and-forward dead-drop for [HiveMind](https://github.com/JarbasHiveMind/HiveMind-core)
nodes that are never online at the same time. A sender deposits an encrypted
message addressed to a recipient's public key. The recipient later proves
ownership of that key and collects the message. No simultaneous connection, no
shared IP address, and no persistent HiveMind session.

## Where it sits

Normal HiveMind links are live encrypted WebSocket connections between a satellite
and a [hivemind-core](https://github.com/JarbasHiveMind/HiveMind-core) hub. That
setup needs both ends reachable at once. hivemind-rendezvous fills the gap for
nodes that are only intermittently online: it is a small neutral HTTP relay that
holds [`INTERCOM`](https://github.com/JarbasHiveMind/hivemind-websocket-client)
messages until the recipient comes back to fetch them.

The relay never sees plaintext. Messages are end-to-end encrypted to the
recipient's public key before deposit. The relay only stores opaque blobs keyed by
recipient pubkey, and enforces ownership on retrieval.

## How it works

```
Node A (sender)    Rendezvous node     Node B (recipient)
     │                   │                    │
     │-- POST /deposit -->│                    │
     │   INTERCOM msg     │                    │
     │   target=B.pubkey  │  (stored, TTL ≤7d) │
     │                   │                    │
     │           (time passes)                │
     │                   │<-- POST /retrieve --│
     │                   │    sign(B.privkey)  │
     │                   │-- messages -------->│
     │                   │   (deleted)         │
```

Authentication is proof of RSA pubkey ownership: to retrieve messages, a node
signs a fresh timestamp with its private key. The relay verifies the signature
against the claimed pubkey and checks the timestamp freshness (replay window),
then returns and deletes the pending messages.

## Prerequisites

- Python 3.10+
- An RSA identity for each node (handled by HiveMind / `poorman-handshake`).
- A reachable host to run the relay: a small VPS, a Pi, or any always-on box the
  intermittent nodes can reach over HTTP.

## Install

```bash
pip install hivemind-rendezvous
```

From source:

```bash
git clone https://github.com/JarbasHiveMind/hivemind-rendezvous
cd hivemind-rendezvous
pip install -e .
```

## Quickstart

Run the relay on an always-on host:

```bash
hivemind-rendezvous
# Rendezvous server listening on 0.0.0.0:6789
```

That is the whole relay. Senders `POST /deposit` an INTERCOM message addressed to
a recipient pubkey. Recipients `POST /retrieve` with an ownership proof to collect
them. See [HTTP API](docs/http-api.md) for the request bodies and
[examples](docs/examples.md) for deposit/retrieve snippets.

## Configuration

`run_server()` takes these arguments (defaults shown):

| Argument | Default | Description |
| --- | --- | --- |
| `host` | `0.0.0.0` | Bind address. |
| `port` | `6789` | Listen port. |
| `node_pubkey` | `""` | This relay's own RSA pubkey (PEM), served at `/pubkey`. |
| `deposit_rate_limit` | `60` | Max deposits per client IP per window. |
| `deposit_rate_window` | `60` | Rate-limit window in seconds. |
| `require_depositor_proof` | `False` | Require a valid depositor ownership proof on every deposit. |

Message TTL is set per deposit (`ttl` field, default and hard cap 7 days).

## Documentation

See [`docs/`](docs/index.md):

- [How it works](docs/how-it-works.md): the deposit/retrieve flow and authentication.
- [HTTP API](docs/http-api.md): endpoints, request/response bodies, error codes.
- [Deploy](docs/deploy.md): running and configuring the relay.
- [Examples](docs/examples.md): deposit and retrieve from a client.

## Related projects

- [HiveMind-core](https://github.com/JarbasHiveMind/HiveMind-core): the hub these
  nodes normally connect to.
- [hivemind-websocket-client](https://github.com/JarbasHiveMind/hivemind-websocket-client):
  defines the `INTERCOM` message this relay carries.

## License

Apache-2.0
