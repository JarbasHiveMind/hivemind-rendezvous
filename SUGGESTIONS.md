# Suggestions — hivemind-rendezvous

## SUG-001 — Migrate storage to hivemind-plugin-manager DB
Replace `JsonStorageXDG` with the `hivemind-plugin-manager` database backend for
proper multi-process access, query support, and scalability.

## SUG-002 — Optional depositor proof-of-ownership
Mirror the retrieve proof on the deposit side: require the sender to prove it owns
_some_ keypair (not necessarily the recipient's). Deters anonymous spam.

## SUG-003 — Notify sender on retrieval
Optionally accept a callback URL on deposit; POST a delivery receipt when the
recipient retrieves the message.

## SUG-004 — Federation between rendezvous nodes
Allow rendezvous nodes to gossip deposits so a sender can deposit at any
rendezvous node and the recipient can retrieve from any other.
