# FAQ — hivemind-rendezvous

## What is hivemind-rendezvous?

A dead drop for nodes that are never online at the same time. Node A deposits
an INTERCOM message addressed to Node B's public key; Node B collects it the
next time it connects. The relay is an ordinary hivemind-core node with this
package installed, serving the `RENDEZVOUS` message type.

## Is it a separate service?

No. It runs inside hivemind-core, on the listener that already accepts clients.
No extra port, no extra process, no extra credentials. Enable it like
hivemind-presence: install the package and set `rendezvous.enabled`.

## How does the relay know whose mailbox to open?

By the public key hivemind-core pinned for that connection during the handshake.
A `collect` or `ack` request carries no mailbox address, so asking for another
node's mail is not something the protocol can express.

## Is there an ownership proof to sign?

No, and that is the point. The earlier HTTP version needed a signed timestamp
because it had no session. That proof stayed valid for its whole tolerance
window, so anyone who observed one could replay it and empty the victim's
mailbox. An authenticated session removes the problem instead of narrowing it.

## Is there rate limiting?

Admission is hivemind-core's job — an unknown client never reaches the mailbox.
The mailbox adds one limit of its own, `max_pending_per_mailbox` (default 256),
because an authenticated peer is not automatically a well-behaved one.

## Can the relay read my messages?

No. Only `INTERCOM` may be deposited, and it is already end-to-end encrypted to
the recipient's public key before it leaves the sender. The relay stores an
opaque blob. It also never sees it in clear on the wire, since the hive link is
`wss` or the v3 Noise transport.

## What happens if my connection drops mid-collect?

Nothing is lost. `collect` does not delete; messages are removed only when you
`ack` their deposit ids. Anything unacked is handed out again next time.

## So I can receive the same message twice?

Yes, and you should tolerate it. That is the deliberate trade: at-least-once
delivery costs an occasional duplicate, which you can detect, while
delete-on-read costs the whole message whenever a reply goes missing — and the
peer this exists for cannot be asked to resend.

## How long are messages kept?

Seven days, and a deposit cannot ask for longer. Expiry is checked whenever a
mailbox is read, so an expired message is never handed out even if the periodic
store-wide sweep has not run yet.

## Where is mail stored?

In a `json_database.JsonStorageXDG` file, keyed by the SHA-256 fingerprint of
the recipient's public key, so a full PEM never becomes a dict key. The store
is held in memory; see AUDIT-002.

## What happens if I send RENDEZVOUS to a node that is not a rendezvous point?

It replies `{"status": "error", "reason": "not_a_rendezvous_node"}`. That is
deliberately distinct from a successful collect that returns no messages, so a
client can tell "no mail" from "wrong node" and fail over.

## Does this need a hivemind-core change?

Yes. Core routes `RENDEZVOUS` to the mailbox and binds it at startup. Before
that landed, `RENDEZVOUS` fell through to the empty unknown-message stub, which
is where it had sat since the type was reserved in 2021.
