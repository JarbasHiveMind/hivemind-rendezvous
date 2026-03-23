"""Unit tests for hivemind_rendezvous.server HTTP endpoints."""

import json
import time
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from poorman_handshake.asymmetric.utils import create_RSA_key

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_rendezvous.auth import sign_ownership
from hivemind_rendezvous.server import make_handler, _RateLimiter
from hivemind_rendezvous.storage import RendezvousStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def node_keys():
    pub, priv = create_RSA_key(2048)
    return pub, priv


@pytest.fixture(scope="module")
def client_keys():
    pub, priv = create_RSA_key(2048)
    return pub, priv


@pytest.fixture(scope="module")
def depositor_keys():
    pub, priv = create_RSA_key(2048)
    return pub, priv


@pytest.fixture()
def store(tmp_path):
    with patch("hivemind_rendezvous.storage.xdg_data_home", return_value=str(tmp_path)):
        return RendezvousStore(store_name="srv_test")


def _call(handler_cls, method: str, path: str, body: dict | None = None,
          client_ip: str = "127.0.0.1"):
    """Invoke a handler method and capture the response."""
    body_bytes = json.dumps(body).encode() if body else b""
    captured = {}

    handler = handler_cls.__new__(handler_cls)
    handler.path = path
    handler.headers = {"Content-Length": str(len(body_bytes))}
    handler.rfile = BytesIO(body_bytes)
    handler.client_address = (client_ip, 12345)
    handler._send_json = lambda data, status=200: captured.update({"status": status, "body": data})
    handler._send_error = lambda s, r: captured.update({"status": s, "body": {"status": "error", "reason": r}})
    handler._read_body = lambda: body

    getattr(handler, f"do_{method}")()
    return captured


def _intercom_payload() -> str:
    msg = HiveMessage(HiveMessageType.INTERCOM, {"data": "hello"})
    return msg.serialize()


# ---------------------------------------------------------------------------
# GET /pubkey
# ---------------------------------------------------------------------------

def test_get_pubkey(node_keys, store):
    pub, _ = node_keys
    cls = make_handler(store, pub)
    result = _call(cls, "GET", "/pubkey")
    assert result["status"] == 200
    assert result["body"]["pubkey"] == pub


def test_get_unknown_path(node_keys, store):
    cls = make_handler(store, node_keys[0])
    result = _call(cls, "GET", "/unknown")
    assert result["status"] == 404


# ---------------------------------------------------------------------------
# POST /deposit — basic
# ---------------------------------------------------------------------------

def test_deposit_valid(node_keys, client_keys, store):
    cls = make_handler(store, node_keys[0])
    body = {"payload": _intercom_payload(), "target_pubkey": client_keys[0]}
    result = _call(cls, "POST", "/deposit", body)
    assert result["status"] == 200
    assert result["body"]["status"] == "ok"
    assert "deposit_id" in result["body"]


def test_deposit_missing_fields(node_keys, store):
    cls = make_handler(store, node_keys[0])
    result = _call(cls, "POST", "/deposit", {"payload": "x"})
    assert result["status"] == 400


def test_deposit_non_intercom(node_keys, client_keys, store):
    cls = make_handler(store, node_keys[0])
    bus_msg = HiveMessage(HiveMessageType.BUS, {"type": "speak", "data": {}, "context": {}})
    body = {"payload": bus_msg.serialize(), "target_pubkey": client_keys[0]}
    result = _call(cls, "POST", "/deposit", body)
    assert result["status"] == 400
    assert result["body"]["reason"] == "payload_must_be_intercom"


# ---------------------------------------------------------------------------
# POST /deposit — rate limiting (AUDIT-001)
# ---------------------------------------------------------------------------

def test_deposit_rate_limit_blocks_excess(node_keys, client_keys, store):
    """After limit is exceeded, next request is throttled."""
    cls = make_handler(store, node_keys[0], deposit_rate_limit=2, deposit_rate_window=60)
    body = {"payload": _intercom_payload(), "target_pubkey": client_keys[0]}
    _call(cls, "POST", "/deposit", body, client_ip="10.0.0.1")
    _call(cls, "POST", "/deposit", body, client_ip="10.0.0.1")
    result = _call(cls, "POST", "/deposit", body, client_ip="10.0.0.1")
    assert result["status"] == 429
    assert result["body"]["reason"] == "rate_limit_exceeded"


def test_deposit_rate_limit_per_ip(node_keys, client_keys, store):
    """Rate limit is per-IP; different IPs have independent quotas."""
    cls = make_handler(store, node_keys[0], deposit_rate_limit=1, deposit_rate_window=60)
    body = {"payload": _intercom_payload(), "target_pubkey": client_keys[0]}
    r1 = _call(cls, "POST", "/deposit", body, client_ip="10.0.0.2")
    r2 = _call(cls, "POST", "/deposit", body, client_ip="10.0.0.3")
    assert r1["status"] == 200
    assert r2["status"] == 200


# ---------------------------------------------------------------------------
# POST /deposit — depositor proof (AUDIT-004)
# ---------------------------------------------------------------------------

def test_deposit_with_valid_depositor_proof(node_keys, client_keys, depositor_keys, store):
    """Deposit with a valid depositor proof is accepted."""
    cls = make_handler(store, node_keys[0])
    ts = int(time.time())
    sig = sign_ownership(depositor_keys[1], depositor_keys[0], ts)
    body = {
        "payload": _intercom_payload(),
        "target_pubkey": client_keys[0],
        "depositor_pubkey": depositor_keys[0],
        "depositor_timestamp": ts,
        "depositor_signature": sig,
    }
    result = _call(cls, "POST", "/deposit", body)
    assert result["status"] == 200


def test_deposit_with_invalid_depositor_proof_rejected(node_keys, client_keys, depositor_keys, store):
    """Deposit with a bad depositor signature is rejected with 401."""
    cls = make_handler(store, node_keys[0])
    ts = int(time.time())
    body = {
        "payload": _intercom_payload(),
        "target_pubkey": client_keys[0],
        "depositor_pubkey": depositor_keys[0],
        "depositor_timestamp": ts,
        "depositor_signature": "invalidsig==",
    }
    result = _call(cls, "POST", "/deposit", body)
    assert result["status"] == 401
    assert result["body"]["reason"] == "invalid_depositor_signature"


def test_deposit_require_proof_mode_blocks_anonymous(node_keys, client_keys, store):
    """With require_depositor_proof=True, anonymous deposits are rejected."""
    cls = make_handler(store, node_keys[0], require_depositor_proof=True)
    body = {"payload": _intercom_payload(), "target_pubkey": client_keys[0]}
    result = _call(cls, "POST", "/deposit", body)
    assert result["status"] == 400
    assert result["body"]["reason"] == "depositor_proof_required"


def test_deposit_require_proof_mode_accepts_valid(node_keys, client_keys, depositor_keys, store):
    """With require_depositor_proof=True, valid proof is accepted."""
    cls = make_handler(store, node_keys[0], require_depositor_proof=True)
    ts = int(time.time())
    sig = sign_ownership(depositor_keys[1], depositor_keys[0], ts)
    body = {
        "payload": _intercom_payload(),
        "target_pubkey": client_keys[0],
        "depositor_pubkey": depositor_keys[0],
        "depositor_timestamp": ts,
        "depositor_signature": sig,
    }
    result = _call(cls, "POST", "/deposit", body)
    assert result["status"] == 200


# ---------------------------------------------------------------------------
# POST /retrieve
# ---------------------------------------------------------------------------

def test_retrieve_valid(node_keys, client_keys, store):
    cls = make_handler(store, node_keys[0])
    payload_str = _intercom_payload()
    store.deposit(client_keys[0], payload_str)

    ts = int(time.time())
    sig = sign_ownership(client_keys[1], client_keys[0], ts)
    body = {"pubkey": client_keys[0], "timestamp": ts, "signature": sig}
    result = _call(cls, "POST", "/retrieve", body)
    assert result["status"] == 200
    assert result["body"]["status"] == "ok"
    assert payload_str in result["body"]["messages"]


def test_retrieve_invalid_signature(node_keys, client_keys, store):
    cls = make_handler(store, node_keys[0])
    ts = int(time.time())
    body = {"pubkey": client_keys[0], "timestamp": ts, "signature": "invalidsig=="}
    result = _call(cls, "POST", "/retrieve", body)
    assert result["status"] == 401


def test_retrieve_replay(node_keys, client_keys, store):
    cls = make_handler(store, node_keys[0])
    ts = int(time.time()) - 61
    sig = sign_ownership(client_keys[1], client_keys[0], ts)
    body = {"pubkey": client_keys[0], "timestamp": ts, "signature": sig}
    result = _call(cls, "POST", "/retrieve", body)
    assert result["status"] == 401
    assert result["body"]["reason"] == "replay_detected"


# ---------------------------------------------------------------------------
# _RateLimiter unit tests
# ---------------------------------------------------------------------------

def test_rate_limiter_allows_within_limit():
    rl = _RateLimiter(limit=3, window=60)
    assert rl.is_allowed("a") is True
    assert rl.is_allowed("a") is True
    assert rl.is_allowed("a") is True


def test_rate_limiter_blocks_over_limit():
    rl = _RateLimiter(limit=2, window=60)
    rl.is_allowed("b")
    rl.is_allowed("b")
    assert rl.is_allowed("b") is False


def test_rate_limiter_independent_keys():
    rl = _RateLimiter(limit=1, window=60)
    assert rl.is_allowed("x") is True
    assert rl.is_allowed("y") is True


def test_rate_limiter_window_expiry():
    """Timestamps outside the window are evicted; counter resets."""
    rl = _RateLimiter(limit=1, window=1)
    rl.is_allowed("z")
    # Manually age the timestamp so it falls outside the window
    rl._buckets["z"][0] = time.time() - 2
    assert rl.is_allowed("z") is True
