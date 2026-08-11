# hivemind-rendezvous

A store-and-forward dead drop for [HiveMind](https://github.com/JarbasHiveMind/HiveMind-core)
nodes that are never online at the same time. One node deposits an encrypted
message addressed to another node's public key; the recipient collects it
whenever it next connects.

A rendezvous node is an ordinary hivemind-core node that holds mail. It speaks
the normal HiveMind protocol over the listener that is already accepting
clients, using the `RENDEZVOUS` message type. There is no second service, no
second port, and no second set of credentials.

## Enable it

Install the package on the node that should hold mail, and switch it on in the
hivemind-core config, the same way [hivemind-presence](https://github.com/JarbasHiveMind/HiveMind-presence)
is enabled:

```bash
pip install hivemind-rendezvous
```

```json
{
  "rendezvous": {
    "enabled": true,
    "max_pending_per_mailbox": 256
  }
}
```

Nodes without the package installed, or with `enabled` false, answer
`RENDEZVOUS` with `not_a_rendezvous_node`. A peer can therefore tell "no mail"
apart from "not a rendezvous node" and move on to one that is.

## How it works

```
Node A (sender)      Rendezvous node        Node B (recipient)
     │                      │                      │
     │-- RENDEZVOUS ------->│                      │
     │   cmd=deposit        │                      │
     │   target=B.pubkey    │   (stored, TTL ≤7d)  │
     │                      │                      │
     │              (time passes)                  │
     │                      │<---- RENDEZVOUS -----│
     │                      │      cmd=collect     │
     │                      │--- messages -------->│
     │                      │<---- RENDEZVOUS -----│
     │                      │      cmd=ack         │
     │                      │  (deleted)           │
```

Three commands, all carried in the `RENDEZVOUS` payload:

| `cmd` | Fields | Reply |
|---|---|---|
| `deposit` | `target_pubkey`, `payload` (a serialised `INTERCOM` message), optional `ttl` | `deposit_id` |
| `collect` | none | `messages`: a list of `{deposit_id, payload}` |
| `ack` | `deposit_ids` | `removed`: how many were deleted |

Only `INTERCOM` may be deposited. It is the one message type already
end-to-end encrypted to a named public key, so the relay can hold it without
ever being able to read it.

## What the hive already provides

The relay has no authentication code of its own, because the connection is
already authenticated:

- **A caller cannot name a mailbox.** `collect` and `ack` operate on the public
  key this connection was TOFU-pinned to during the handshake. Asking for
  another node's mail is not something the wire can express, so there is no
  ownership proof to sign, no timestamp to check, and no replay window.
- **Confidentiality** is the link (`wss`, or the Noise transport on protocol
  v3), on top of the end-to-end encryption the deposited envelope carries.
- **Admission and flood control** belong to the listener. An unknown client
  never reaches the mailbox.

## Delivery

Delivery is **at-least-once**. `collect` returns messages and leaves them
stored; they are deleted only when the recipient acks the deposit ids it
actually received. A reply lost in transit therefore costs a redelivery rather
than the message.

That trade is deliberate. The recipient may occasionally see a message twice,
which it can detect. The alternative — deleting on read — loses the message
permanently whenever a response goes missing, and the peer this system exists
for is, by definition, unreachable for a resend.

Messages expire after seven days.

## Storage

Mail is kept in a `json_database.JsonStorageXDG` file, keyed by the SHA-256
fingerprint of the recipient's public key. Expiry is enforced whenever a
mailbox is read, and the whole store is swept for expired entries at most once
every five minutes, so request cost tracks the mailbox being touched rather
than total stored volume.

The store holds everything in memory. That is fine for the volume a dead drop
between a handful of hives sees, and is the first thing to replace with a
`hivemind-plugin-manager` database backend if that stops being true.

## Docs

- [How it works](docs/how-it-works.md)
- [Examples](docs/examples.md)
