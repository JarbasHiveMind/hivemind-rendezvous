# Examples

Both sides are ordinary HiveMind clients. They connect to the rendezvous node
the same way they connect to any master, with credentials that node issued via
`hivemind-core add-client`.

## Deposit a message for an offline peer

```python
from hivemind_bus_client.client import HiveMessageBusClient
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_rendezvous.client import make_deposit_envelope

# the inner message only the recipient can open
envelope = make_deposit_envelope(recipient_pubkey, "hello from last tuesday",
                                 sign_key=my_private_key)
inner = HiveMessage(HiveMessageType.INTERCOM, payload=envelope)

bus = HiveMessageBusClient(key=access_key, password=password,
                           host="wss://rendezvous.example.org")
bus.connect()
bus.emit(HiveMessage(HiveMessageType.RENDEZVOUS, payload={
    "cmd": "deposit",
    "target_pubkey": recipient_pubkey,
    "payload": inner.serialize(),
}))
```

## Collect your mail

```python
from hivemind_bus_client.decorators import on_rendezvous_message

@on_rendezvous_message
def handle_mail(message):
    if message.payload.get("status") != "ok":
        return
    received = message.payload.get("messages", [])
    for entry in received:
        inner = HiveMessage.deserialize(entry["payload"])
        ...  # decrypt with your private key and act on it

    # only now, once the messages are safely in hand
    if received:
        bus.emit(HiveMessage(HiveMessageType.RENDEZVOUS, payload={
            "cmd": "ack",
            "deposit_ids": [e["deposit_id"] for e in received],
        }))

bus.emit(HiveMessage(HiveMessageType.RENDEZVOUS, payload={"cmd": "collect"}))
```

Ack after the messages are stored or acted on, not before. Everything not
acked is handed out again on the next collect, which is what makes a lost
reply survivable.

## Detecting a node that holds no mail

A node without the package installed, or with `rendezvous.enabled` false,
replies:

```json
{"status": "error", "reason": "not_a_rendezvous_node"}
```

which is distinct from a successful collect returning an empty list. A client
can use that to fall back to another rendezvous point instead of assuming it
has no mail.

---

[← How it works](how-it-works.md) · [Home](index.md)
