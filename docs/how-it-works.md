# How it works

hivemind-rendezvous is a neutral HTTP relay that lets two nodes exchange messages
without being online at the same time and without knowing each other's address.

## The dead-drop flow

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

1. Deposit. Node A serializes a HiveMind `INTERCOM` message, encrypts it to
   Node B's public key, and posts it to `/deposit` with `target_pubkey = B.pubkey`.
   The relay stores the opaque blob in a mailbox keyed by that pubkey.
2. Wait. The message sits in the mailbox until retrieved or until its TTL
   expires (default and hard cap: 7 days).
3. Retrieve. Node B comes online and posts an ownership proof to `/retrieve`.
   The relay verifies it, returns every pending message for B's pubkey, and
   deletes them.

## Authentication: proof of pubkey ownership

There is no account or session. To retrieve messages, a node proves it controls
the private key for the pubkey it is claiming:

- The client signs a domain-separated message that binds its own pubkey, the
  relay's pubkey, and a fresh timestamp.
- The relay verifies the signature against the claimed pubkey, checks the
  timestamp is within ±60 seconds (replay protection), and confirms the relay
  pubkey in the proof matches its own (cross-server replay protection).

`sign_ownership()` produces the proof on the client. `verify_ownership()` checks
it on the relay (see [HTTP API](http-api.md)).

## Confidentiality

The relay handles only ciphertext. Senders encrypt the INTERCOM envelope to the
recipient's pubkey before deposit, so the relay never sees plaintext. When a
deposit carries a `recipient_fingerprint`, the relay also checks it matches
`SHA256(target_pubkey)`. This stops a depositor from filing a message encrypted
for a different key into someone else's mailbox.

## Abuse controls

- Per-IP rate limiting on `/deposit` (sliding window; defaults to 60 deposits per
  60 seconds).
- Optional depositor proof (`require_depositor_proof=True`) makes every deposit
  carry a verified depositor ownership proof.
- TTL cap bounds how long any message can linger (7 days max).

---
[Home](index.md) · [HTTP API →](./http-api.md)
