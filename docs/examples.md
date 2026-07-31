# Examples

These examples use plain HTTP requests against a running relay at
`http://relay.example.org:6789`.

## Fetch the relay pubkey

```python
import requests

RELAY = "http://relay.example.org:6789"
relay_pubkey = requests.get(f"{RELAY}/pubkey").json()["pubkey"]
```

## Deposit a message for a recipient

The `payload` is a serialized HiveMind `INTERCOM` message encrypted to the
recipient's pubkey. Building and encrypting the envelope is done with the
HiveMind client libraries; here `payload_str` is assumed ready.

```python
import requests

resp = requests.post(f"{RELAY}/deposit", json={
    "payload": payload_str,          # serialized INTERCOM, encrypted to B
    "target_pubkey": recipient_pem,  # recipient's RSA pubkey (PEM)
    "ttl": 604800,                   # optional, max 7 days
})
print(resp.json())   # {"status": "ok", "deposit_id": "..."}
```

## Retrieve your messages

```python
import requests, time
from hivemind_rendezvous.auth import sign_ownership

ts = int(time.time())
signature = sign_ownership(my_private_key, my_pubkey_pem, ts,
                           server_pubkey=relay_pubkey)

resp = requests.post(f"{RELAY}/retrieve", json={
    "pubkey": my_pubkey_pem,
    "timestamp": ts,
    "signature": signature,
})
for msg in resp.json()["messages"]:
    handle(msg)   # decrypt + deserialize with the HiveMind client
```

Retrieved messages are deleted from the relay.

## Deposit with a depositor proof

When the relay runs with `require_depositor_proof=True`, sign a depositor proof
too:

```python
import time
from hivemind_rendezvous.auth import sign_ownership

ts = int(time.time())
dep_sig = sign_ownership(sender_private_key, sender_pubkey_pem, ts,
                         server_pubkey=relay_pubkey)

requests.post(f"{RELAY}/deposit", json={
    "payload": payload_str,
    "target_pubkey": recipient_pem,
    "depositor_pubkey": sender_pubkey_pem,
    "depositor_timestamp": ts,
    "depositor_signature": dep_sig,
})
```

---
[← Deploy](deploy.md) · [Home](index.md)
