# hivemind-rendezvous

A store-and-forward dead drop for HiveMind nodes that are never online at the
same time.

A rendezvous node is an ordinary [hivemind-core](https://github.com/JarbasHiveMind/HiveMind-core)
node with this package installed and `rendezvous.enabled` set. It serves the
`RENDEZVOUS` message type over the listener that already accepts clients, so
being a rendezvous point costs no extra port, service or credential.

## Pages

- [How it works](how-it-works.md) — the three commands, delivery semantics, and
  what the hive session already guarantees
- [Examples](examples.md) — depositing and collecting from a satellite

## Quickstart

On the node that should hold mail:

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

Restart hivemind-core. The log line `rendezvous mailbox enabled` confirms it.

---

[Home](index.md) · [How it works →](how-it-works.md)
