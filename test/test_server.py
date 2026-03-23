"""Unit tests for hivemind_rendezvous.server HTTP endpoints."""

import json
import time
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from poorman_handshake.asymmetric.utils import create_RSA_key

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_rendezvous.auth import sign_ownership
from hivemind_rendezvous.server import make_handler
from hivemind_rendezvous.storage import RendezvousStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def node_keys():
    """RSA key pair representing the rendezvous node."""
    pub, priv = create_RSA_key(2048)
    return pub, priv


@pytest.fixture(scope="module")
def client_keys():
    """RSA key pair representing the retrieving client."""
    pub, priv = create_RSA_key(2048)
    return pub, priv


@pytest.fixture()
def store(tmp_path):
    with patch("hivemind_rendezvous.storage.xdg_data_home", return_value=str(tmp_path)):
        return RendezvousStore(store_name="srv_test")


def _make_handler(store, node_pubkey):
    return make_handler(store, node_pubkey)


def _call(handler_cls, method: str, path: str, body: dict | None = None):
    """Invoke a handler method and capture the response."""
    body_bytes = json.dumps(body).encode() if body else b""
    request = MagicMock()
    request.makefile.return_value = BytesIO(body_bytes)

    responses = []
    wfile = BytesIO()

    handler = handler_cls.__new__(handler_cls)
    handler.path = path
    handler.headers = {"Content-Length": str(len(body_bytes))}
    handler.rfile = BytesIO(body_bytes)
    handler.wfile = wfile
    handler.send_response = lambda code: responses.append(code)
    handler.send_header = lambda *a: None
    handler.end_headers = lambda: None

    captured = {}

    def _send_json(data, status=200):
        captured["status"] = status
        captured["body"] = data

    handler._send_json = _send_json
    handler._send_error = lambda s, r: captured.update({"status": s, "body": {"status": "error", "reason": r}})
    handler._read_body = lambda: body

    getattr(handler, f"do_{method}")()
    return captured


# ---------------------------------------------------------------------------
# GET /pubkey
# ---------------------------------------------------------------------------

def test_get_pubkey(node_keys, store):
    pub, _ = node_keys
    cls = _make_handler(store, pub)
    result = _call(cls, "GET", "/pubkey")
    assert result["status"] == 200
    assert result["body"]["pubkey"] == pub


def test_get_unknown_path(node_keys, store):
    cls = _make_handler(store, node_keys[0])
    result = _call(cls, "GET", "/unknown")
    assert result["status"] == 404


# ---------------------------------------------------------------------------
# POST /deposit
# ---------------------------------------------------------------------------

def _intercom_payload(client_keys) -> str:
    """Build a minimal serialised INTERCOM HiveMessage."""
    pub, _ = client_keys
    msg = HiveMessage(HiveMessageType.INTERCOM, {"data": "hello"})
    return msg.serialize()


def test_deposit_valid(node_keys, client_keys, store):
    cls = _make_handler(store, node_keys[0])
    body = {
        "payload": _intercom_payload(client_keys),
        "target_pubkey": client_keys[0],
    }
    result = _call(cls, "POST", "/deposit", body)
    assert result["status"] == 200
    assert result["body"]["status"] == "ok"
    assert "deposit_id" in result["body"]


def test_deposit_missing_fields(node_keys, store):
    cls = _make_handler(store, node_keys[0])
    result = _call(cls, "POST", "/deposit", {"payload": "x"})
    assert result["status"] == 400


def test_deposit_non_intercom(node_keys, client_keys, store):
    cls = _make_handler(store, node_keys[0])
    msg = HiveMessage(HiveMessageType.BUS, MagicMock(serialize=lambda: '{}', msg_type="speak"))
    # Use a BUS-type serialised message — server must reject it
    bus_msg = HiveMessage(HiveMessageType.BUS, {"type": "speak", "data": {}, "context": {}})
    body = {
        "payload": bus_msg.serialize(),
        "target_pubkey": client_keys[0],
    }
    result = _call(cls, "POST", "/deposit", body)
    assert result["status"] == 400
    assert result["body"]["reason"] == "payload_must_be_intercom"


# ---------------------------------------------------------------------------
# POST /retrieve
# ---------------------------------------------------------------------------

def test_retrieve_valid(node_keys, client_keys, store):
    cls = _make_handler(store, node_keys[0])
    payload_str = _intercom_payload(client_keys)
    store.deposit(client_keys[0], payload_str)

    ts = int(time.time())
    sig = sign_ownership(client_keys[1], client_keys[0], ts)
    body = {"pubkey": client_keys[0], "timestamp": ts, "signature": sig}
    result = _call(cls, "POST", "/retrieve", body)
    assert result["status"] == 200
    assert result["body"]["status"] == "ok"
    assert payload_str in result["body"]["messages"]


def test_retrieve_invalid_signature(node_keys, client_keys, store):
    cls = _make_handler(store, node_keys[0])
    ts = int(time.time())
    body = {"pubkey": client_keys[0], "timestamp": ts, "signature": "invalidsig=="}
    result = _call(cls, "POST", "/retrieve", body)
    assert result["status"] == 401


def test_retrieve_replay(node_keys, client_keys, store):
    cls = _make_handler(store, node_keys[0])
    ts = int(time.time()) - 61
    sig = sign_ownership(client_keys[1], client_keys[0], ts)
    body = {"pubkey": client_keys[0], "timestamp": ts, "signature": sig}
    result = _call(cls, "POST", "/retrieve", body)
    assert result["status"] == 401
    assert result["body"]["reason"] == "replay_detected"
