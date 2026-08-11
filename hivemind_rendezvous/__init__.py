"""hivemind-rendezvous — a store-and-forward dead drop for HiveMind nodes.

Two nodes that are never online at the same time can still exchange INTERCOM
messages: one deposits, the other collects later. The relay is an ordinary
hivemind-core node with this package installed and rendezvous enabled, so it
speaks plain HiveMind over the existing listener — no second service, no
second port, and no authentication scheme of its own.

Enable it the way hivemind-presence is enabled: install the package and set
``rendezvous.enabled`` in the hivemind-core config.

Submodules:
    mailbox  — :class:`~hivemind_rendezvous.mailbox.RendezvousMailbox`, the
               ``RENDEZVOUS`` request handler hivemind-core calls
    storage  — :class:`~hivemind_rendezvous.storage.RendezvousStore`
    client   — depositor-side envelope helpers
"""

from hivemind_rendezvous.mailbox import RendezvousMailbox
from hivemind_rendezvous.storage import RendezvousStore
from hivemind_rendezvous.version import VERSION

__version__ = VERSION
__all__ = ["VERSION", "RendezvousMailbox", "RendezvousStore"]
