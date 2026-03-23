"""HTTP rendezvous server.

Exposes three endpoints:

``GET  /pubkey``     — return this node's RSA public key (PEM).
``POST /deposit``    — store an INTERCOM message for a recipient pubkey.
``POST /retrieve``   — prove pubkey ownership and fetch pending messages.

The server has no persistent HiveMind session; proof-of-pubkey-ownership is the
only authentication mechanism (see :mod:`hivemind_rendezvous.auth`).

**TLS / HTTPS**: this server speaks plain HTTP.  Deploy behind a TLS-terminating
reverse proxy (e.g. nginx, Caddy) in production.  Example nginx snippet::

    location / {
        proxy_pass http://127.0.0.1:6789;
    }

**Rate limiting**: per-IP sliding-window limiting is applied to ``POST /deposit``
to prevent mailbox flooding.  The default is 60 deposits per IP per minute.
The limit can be adjusted via the *deposit_rate_limit* / *deposit_rate_window*
parameters to :func:`make_handler`.

**Depositor authentication**: ``POST /deposit`` optionally accepts
``depositor_pubkey`` + ``depositor_timestamp`` + ``depositor_signature`` fields.
When present, the server verifies the depositor's proof-of-ownership before
accepting the message.  This prevents anonymous flooding by unknown parties.
"""

import json
import logging
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Deque, Dict, Optional

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_rendezvous.auth import verify_ownership
from hivemind_rendezvous.storage import RendezvousStore

logger = logging.getLogger(__name__)

_DEFAULT_HOST: str = "0.0.0.0"
_DEFAULT_PORT: int = 6789
_DEFAULT_DEPOSIT_RATE_LIMIT: int = 60   # max deposits per IP per window
_DEFAULT_DEPOSIT_RATE_WINDOW: int = 60  # window size in seconds


class _RateLimiter:
    """Sliding-window rate limiter keyed by a string identifier (e.g. IP address).

    Args:
        limit: Maximum number of events allowed within *window* seconds.
        window: Size of the sliding window in seconds.
    """

    def __init__(self, limit: int, window: int) -> None:
        """Initialise the rate limiter."""
        self._limit: int = limit
        self._window: int = window
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str) -> bool:
        """Return ``True`` if *key* is within its rate limit, ``False`` otherwise.

        Timestamps older than the window are evicted before the check.

        Args:
            key: Identifier for the rate-limited entity (e.g. IP address string).

        Returns:
            ``True`` if the request should be allowed; ``False`` if throttled.
        """
        now = time.time()
        bucket = self._buckets[key]
        # Evict expired timestamps
        while bucket and bucket[0] < now - self._window:
            bucket.popleft()
        if len(bucket) >= self._limit:
            return False
        bucket.append(now)
        return True


class RendezvousHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the rendezvous service.

    Class attributes set by :func:`make_handler`:

    Attributes:
        store: Shared :class:`~hivemind_rendezvous.storage.RendezvousStore` instance.
        node_pubkey: PEM-encoded RSA public key of this rendezvous node.
        rate_limiter: :class:`_RateLimiter` instance for deposit throttling.
        require_depositor_proof: If ``True``, deposits without a valid depositor
            proof-of-ownership are rejected.
    """

    store: RendezvousStore
    node_pubkey: str
    rate_limiter: _RateLimiter
    require_depositor_proof: bool = False

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

        Required body fields:
        - ``payload`` (str): Serialised HiveMessage; must be INTERCOM type.
        - ``target_pubkey`` (str): PEM-encoded recipient RSA public key.

        Optional body fields:
        - ``ttl`` (int): Seconds until expiry (default/cap: 7 days).
        - ``depositor_pubkey`` (str): PEM-encoded depositor RSA public key.
        - ``depositor_timestamp`` (int): Unix timestamp of the depositor proof.
        - ``depositor_signature`` (str): Base64-encoded depositor ownership proof.

        When :attr:`require_depositor_proof` is ``True``, the three
        ``depositor_*`` fields are mandatory and the proof is verified before
        the deposit is accepted.
        """
        client_ip = self.client_address[0] if self.client_address else "unknown"
        if not self.rate_limiter.is_allowed(client_ip):
            logger.warning("deposit: rate limit exceeded for %s", client_ip)
            self._send_error(429, "rate_limit_exceeded")
            return

        payload_str: Optional[str] = body.get("payload")
        target_pubkey: Optional[str] = body.get("target_pubkey")
        ttl: int = int(body.get("ttl", 604800))

        if not payload_str or not target_pubkey:
            self._send_error(400, "missing_fields")
            return

        # Optional / required depositor proof-of-ownership
        depositor_pubkey: Optional[str] = body.get("depositor_pubkey")
        depositor_timestamp: Optional[int] = body.get("depositor_timestamp")
        depositor_signature: Optional[str] = body.get("depositor_signature")

        if self.require_depositor_proof:
            if not depositor_pubkey or depositor_timestamp is None or not depositor_signature:
                self._send_error(400, "depositor_proof_required")
                return

        if depositor_pubkey and depositor_timestamp is not None and depositor_signature:
            if not verify_ownership(depositor_pubkey, int(depositor_timestamp),
                                    depositor_signature,
                                    server_pubkey=self.node_pubkey):
                self._send_error(401, "invalid_depositor_signature")
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

        # Fix 4: verify the envelope was encrypted for target_pubkey.
        # When the sender used hybrid_encrypt(recipient_pubkey=...), the
        # envelope contains recipient_fingerprint = SHA256(recipient_pem).
        # Verify it matches SHA256(target_pubkey) so a depositor cannot
        # place a message encrypted to a different key into this mailbox.
        envelope = msg.payload if isinstance(msg.payload, dict) else {}
        if "recipient_fingerprint" in envelope:
            import hashlib, base64 as _b64
            expected_fp = hashlib.sha256(target_pubkey.encode("utf-8")).digest()
            try:
                provided_fp = _b64.b64decode(envelope["recipient_fingerprint"])
            except Exception:
                self._send_error(400, "invalid_recipient_fingerprint")
                return
            if provided_fp != expected_fp:
                self._send_error(400, "recipient_fingerprint_mismatch")
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

        if not verify_ownership(pubkey, int(timestamp), signature,
                                server_pubkey=self.node_pubkey):
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


def make_handler(store: RendezvousStore, node_pubkey: str,
                 deposit_rate_limit: int = _DEFAULT_DEPOSIT_RATE_LIMIT,
                 deposit_rate_window: int = _DEFAULT_DEPOSIT_RATE_WINDOW,
                 require_depositor_proof: bool = False) -> type:
    """Return a :class:`RendezvousHandler` subclass bound to *store* and *node_pubkey*.

    Args:
        store: Shared :class:`~hivemind_rendezvous.storage.RendezvousStore` instance.
        node_pubkey: PEM-encoded RSA public key of this rendezvous node.
        deposit_rate_limit: Max deposits per IP per *deposit_rate_window* seconds
            (default 60).
        deposit_rate_window: Rate-limit window size in seconds (default 60).
        require_depositor_proof: If ``True``, deposits without a valid
            ``depositor_pubkey``/``depositor_timestamp``/``depositor_signature``
            triple are rejected with HTTP 400.

    Returns:
        A :class:`RendezvousHandler` subclass with the given dependencies injected.
    """

    class _BoundHandler(RendezvousHandler):
        pass

    _BoundHandler.store = store
    _BoundHandler.node_pubkey = node_pubkey
    _BoundHandler.rate_limiter = _RateLimiter(deposit_rate_limit, deposit_rate_window)
    _BoundHandler.require_depositor_proof = require_depositor_proof
    return _BoundHandler


def run_server(host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT,
               store: Optional[RendezvousStore] = None,
               node_pubkey: Optional[str] = None,
               deposit_rate_limit: int = _DEFAULT_DEPOSIT_RATE_LIMIT,
               deposit_rate_window: int = _DEFAULT_DEPOSIT_RATE_WINDOW,
               require_depositor_proof: bool = False) -> None:
    """Start the rendezvous HTTP server (blocking).

    Args:
        host: Bind address (default ``"0.0.0.0"``).
        port: Listen port (default ``6789``).
        store: :class:`~hivemind_rendezvous.storage.RendezvousStore` to use; a new
               default store is created if ``None``.
        node_pubkey: PEM-encoded RSA public key of this node (optional).
        deposit_rate_limit: Max deposits per IP per *deposit_rate_window* seconds.
        deposit_rate_window: Rate-limit sliding window in seconds.
        require_depositor_proof: Reject deposits missing a valid depositor proof.
    """
    if store is None:
        store = RendezvousStore()
    handler_cls = make_handler(store, node_pubkey or "",
                               deposit_rate_limit=deposit_rate_limit,
                               deposit_rate_window=deposit_rate_window,
                               require_depositor_proof=require_depositor_proof)
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
