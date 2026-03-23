"""HTTP rendezvous server.

Exposes three endpoints:

``GET  /pubkey``     — return this node's RSA public key (PEM).
``POST /deposit``    — store an INTERCOM message for a recipient pubkey.
``POST /retrieve``   — prove pubkey ownership and fetch pending messages.

The server has no persistent HiveMind session; proof-of-pubkey-ownership is the
only authentication mechanism (see :mod:`hivemind_rendezvous.auth`).
"""

import json
import logging
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_rendezvous.auth import verify_ownership, sign_ownership
from hivemind_rendezvous.storage import RendezvousStore

logger = logging.getLogger(__name__)

_DEFAULT_HOST: str = "0.0.0.0"
_DEFAULT_PORT: int = 6789


class RendezvousHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the rendezvous service.

    Class attributes set by :func:`make_handler`:

    Attributes:
        store: Shared :class:`~hivemind_rendezvous.storage.RendezvousStore` instance.
        node_pubkey: PEM-encoded RSA public key of this rendezvous node.
    """

    store: RendezvousStore
    node_pubkey: str

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 — method name required by stdlib
        """Handle GET requests."""
        if self.path == "/pubkey":
            self._send_json({"pubkey": self.node_pubkey})
        else:
            self._send_error(404, "not_found")

    def do_POST(self) -> None:  # noqa: N802
        """Handle POST requests."""
        body = self._read_body()
        if body is None:
            return
        if self.path == "/deposit":
            self._handle_deposit(body)
        elif self.path == "/retrieve":
            self._handle_retrieve(body)
        else:
            self._send_error(404, "not_found")

    # ------------------------------------------------------------------
    # Endpoint implementations
    # ------------------------------------------------------------------

    def _handle_deposit(self, body: dict) -> None:
        """Validate and store a deposit request.

        Expected body fields:
        - ``payload`` (str): Serialised HiveMessage; must be INTERCOM type.
        - ``target_pubkey`` (str): PEM-encoded recipient RSA public key.
        - ``ttl`` (int, optional): Seconds until expiry (default/cap: 7 days).
        """
        payload_str: Optional[str] = body.get("payload")
        target_pubkey: Optional[str] = body.get("target_pubkey")
        ttl: int = int(body.get("ttl", 604800))

        if not payload_str or not target_pubkey:
            self._send_error(400, "missing_fields")
            return

        try:
            msg = HiveMessage.deserialize(payload_str)
        except Exception as exc:
            logger.warning("deposit: failed to deserialise payload: %s", exc)
            self._send_error(400, "invalid_payload")
            return

        if msg.msg_type != HiveMessageType.INTERCOM:
            self._send_error(400, "payload_must_be_intercom")
            return

        try:
            deposit_id = self.store.deposit(target_pubkey, payload_str, ttl=ttl)
        except Exception as exc:
            logger.error("deposit: storage error: %s", exc)
            self._send_error(500, "storage_error")
            return

        self._send_json({"status": "ok", "deposit_id": deposit_id})

    def _handle_retrieve(self, body: dict) -> None:
        """Verify ownership proof and return pending messages.

        Expected body fields:
        - ``pubkey`` (str): PEM-encoded RSA public key of the claimer.
        - ``timestamp`` (int): Unix timestamp embedded in the proof.
        - ``signature`` (str): Base64-encoded ownership proof signature.
        """
        pubkey: Optional[str] = body.get("pubkey")
        timestamp: Optional[int] = body.get("timestamp")
        signature: Optional[str] = body.get("signature")

        if not pubkey or timestamp is None or not signature:
            self._send_error(400, "missing_fields")
            return

        now = int(time.time())
        if abs(now - int(timestamp)) > 60:
            self._send_error(401, "replay_detected")
            return

        if not verify_ownership(pubkey, int(timestamp), signature):
            self._send_error(401, "invalid_signature")
            return

        messages = self.store.retrieve(pubkey)
        self._send_json({"status": "ok", "messages": messages})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_body(self) -> Optional[dict]:
        """Read and JSON-decode the request body.

        Returns:
            Parsed dict, or ``None`` if the body is missing or malformed
            (a 400 response is sent in the latter case).
        """
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            self._send_error(400, "empty_body")
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self._send_error(400, "invalid_json")
            return None

    def _send_json(self, data: dict, status: int = 200) -> None:
        """Send a JSON response.

        Args:
            data: Dict to serialise as the response body.
            status: HTTP status code (default 200).
        """
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, reason: str) -> None:
        """Send a JSON error response.

        Args:
            status: HTTP status code.
            reason: Machine-readable error reason string.
        """
        self._send_json({"status": "error", "reason": reason}, status=status)

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D102
        logger.debug(fmt, *args)


def make_handler(store: RendezvousStore, node_pubkey: str) -> type:
    """Return a :class:`RendezvousHandler` subclass bound to *store* and *node_pubkey*.

    Args:
        store: Shared :class:`~hivemind_rendezvous.storage.RendezvousStore` instance.
        node_pubkey: PEM-encoded RSA public key of this rendezvous node.

    Returns:
        A :class:`RendezvousHandler` subclass with the given dependencies injected.
    """

    class _BoundHandler(RendezvousHandler):
        pass

    _BoundHandler.store = store
    _BoundHandler.node_pubkey = node_pubkey
    return _BoundHandler


def run_server(host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT,
               store: Optional[RendezvousStore] = None,
               node_pubkey: Optional[str] = None) -> None:
    """Start the rendezvous HTTP server (blocking).

    If *node_pubkey* is ``None``, the ``GET /pubkey`` endpoint will return an empty
    string.  Pass a :class:`~poorman_handshake.asymmetric.utils.RSA` public key for
    full functionality.

    Args:
        host: Bind address (default ``"0.0.0.0"``).
        port: Listen port (default ``6789``).
        store: :class:`~hivemind_rendezvous.storage.RendezvousStore` to use; a new
               default store is created if ``None``.
        node_pubkey: PEM-encoded RSA public key of this node (optional).
    """
    if store is None:
        store = RendezvousStore()
    handler_cls = make_handler(store, node_pubkey or "")
    server = HTTPServer((host, port), handler_cls)
    logger.info("Rendezvous server listening on %s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_server()
