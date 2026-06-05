# HTTP API

The relay is a plain HTTP/JSON service. Default bind: `0.0.0.0:6789`.

## `GET /pubkey`

Return this relay's RSA public key (PEM). Clients need it to bind their ownership
proof to this specific relay.

**Response 200**

```json
{ "pubkey": "-----BEGIN PUBLIC KEY-----\n..." }
```

## `POST /deposit`

Store an `INTERCOM` message for a recipient pubkey.

**Request body**

| Field | Required | Description |
| --- | --- | --- |
| `payload` | yes | Serialised HiveMessage; must be `INTERCOM` type. |
| `target_pubkey` | yes | PEM-encoded recipient RSA public key. |
| `ttl` | no | Seconds until expiry. Default and cap: `604800` (7 days). |
| `depositor_pubkey` | conditional | PEM depositor pubkey (required if the relay runs with `require_depositor_proof`). |
| `depositor_timestamp` | conditional | Unix timestamp of the depositor proof. |
| `depositor_signature` | conditional | Base64 depositor ownership proof. |

**Response 200**

```json
{ "status": "ok", "deposit_id": "<id>" }
```

**Errors**

| Status | `error` | Cause |
| --- | --- | --- |
| 400 | `missing_fields` | `payload` or `target_pubkey` absent. |
| 400 | `invalid_payload` | `payload` failed to deserialise. |
| 400 | `payload_must_be_intercom` | Message was not `INTERCOM` type. |
| 400 | `depositor_proof_required` | Proof required but not supplied. |
| 400 | `recipient_fingerprint_mismatch` | Envelope was encrypted for a different key. |
| 401 | `invalid_depositor_signature` | Depositor proof failed verification. |
| 429 | `rate_limit_exceeded` | Per-IP deposit rate limit hit. |
| 500 | `storage_error` | Relay failed to persist the message. |

## `POST /retrieve`

Prove ownership of a pubkey and fetch (and delete) its pending messages.

**Request body**

| Field | Required | Description |
| --- | --- | --- |
| `pubkey` | yes | PEM-encoded RSA public key being claimed. |
| `timestamp` | yes | Unix timestamp embedded in the proof. |
| `signature` | yes | Base64 ownership proof from `sign_ownership()`. |

**Response 200**

```json
{ "status": "ok", "messages": ["<serialised INTERCOM>", "..."] }
```

Returned messages are deleted from the mailbox.

**Errors**

| Status | `error` | Cause |
| --- | --- | --- |
| 400 | `missing_fields` | `pubkey`, `timestamp`, or `signature` absent. |
| 401 | `replay_detected` | Timestamp outside the ±60 s window. |
| 401 | `invalid_signature` | Proof failed verification. |

## Ownership proof helpers

Client-side, build the proof with `sign_ownership()`; the relay checks it with
`verify_ownership()`.

```python
from hivemind_rendezvous.auth import sign_ownership
import time

ts = int(time.time())
signature = sign_ownership(my_private_key, my_pubkey_pem, ts,
                           server_pubkey=relay_pubkey_pem)
# POST {"pubkey": my_pubkey_pem, "timestamp": ts, "signature": signature}
```

The signed message is domain-separated and binds the claimer pubkey, the relay
pubkey, and the timestamp — so a proof cannot be replayed at another relay.
