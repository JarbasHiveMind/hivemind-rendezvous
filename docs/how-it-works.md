# How it works

Two nodes that are never online together both connect to a third node at their
own convenience. One leaves a message, the other picks it up.

## The three commands

Every request is a `RENDEZVOUS` message whose payload carries a `cmd`. Every
reply is a `RENDEZVOUS` message carrying `status`, and on failure a `reason`.

### deposit

| Field | Required | Meaning |
|---|---|---|
| `target_key` | yes | PEM public key of the recipient |
| `payload` | yes | a serialised `INTERCOM` message |
| `ttl` | no | seconds until expiry; capped at seven days |

Replies with `deposit_id`.

Only `INTERCOM` is accepted. It is the one message type already end-to-end
encrypted to a named public key, so the relay can hold it without being able
to read it. Anything else would arrive in a form the relay could inspect,
which is not what a dead drop is.

### collect

Takes no fields. Replies with `messages`, a list of `{deposit_id, payload}`.

The request cannot name a mailbox. It returns the mail belonging to the public
key this connection was pinned to at handshake time.

### ack

Takes `deposit_ids`. Replies with `removed`.

## Delivery is at-least-once

`collect` does not delete. Messages stay pending until acked, so a reply lost
between relay and recipient costs a redelivery rather than the message.

The recipient may therefore see a message twice and should be able to tolerate
that. The alternative, deleting on read, loses the message permanently whenever
a response goes missing — and the peer this system exists for is by definition
unreachable for a resend.

An ack for an id that is already gone is a no-op, so a client that retries an
ack it is unsure about is never punished for it.

## What the session already guarantees

There is no authentication code in this package. The connection is
authenticated before the mailbox sees it:

- **Identity.** hivemind-core pins each client's public key on first handshake
  (TOFU) and rejects a later mismatch. The mailbox is addressed by that pinned
  key, never by anything in the request, so collecting another node's mail is
  not expressible on the wire.
- **Confidentiality.** The link is `wss`, or the Noise transport on protocol
  v3, over an envelope that is already end-to-end encrypted.
- **Admission.** An unknown client never reaches this code.

This is the reason the service has no signed timestamps, no replay cache and
no rate limiter of its own: with a session, none of those problems exist.

## Limits

`max_pending_per_mailbox` (default 256) bounds one mailbox. An authenticated
peer is not automatically a well-behaved one, and an unbounded mailbox both
fills the disk and denies the owner their real mail.

Messages expire after seven days. Expiry is enforced when a mailbox is read;
the whole store is swept at most once every five minutes so that request cost
tracks the mailbox being touched, not total stored volume.

---

[← Home](index.md) · [Home](index.md) · [Examples →](examples.md)
