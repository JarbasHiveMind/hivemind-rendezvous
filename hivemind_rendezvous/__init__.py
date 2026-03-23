"""hivemind-rendezvous — async store-and-forward dead drop for HiveMind nodes.

Nodes from different, non-simultaneously-connected hives can exchange INTERCOM
messages via a shared rendezvous point.  The sender deposits a message keyed by
the recipient's RSA public key; the recipient retrieves it later by proving
pubkey ownership (signed timestamp, no server-side challenge state).

Submodules:
    auth     — :func:`~hivemind_rendezvous.auth.sign_ownership` /
               :func:`~hivemind_rendezvous.auth.verify_ownership`
    storage  — :class:`~hivemind_rendezvous.storage.RendezvousStore`
    server   — :func:`~hivemind_rendezvous.server.run_server`
"""

from hivemind_rendezvous.version import VERSION

__version__ = VERSION
__all__ = ["VERSION"]
