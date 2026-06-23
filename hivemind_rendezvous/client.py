"""Client-side helpers for depositing into a rendezvous mailbox.

The rendezvous server keys mailboxes by the recipient's RSA public key, but the
message payload itself is end-to-end encrypted by the depositor with
:func:`hivemind_bus_client.encryption.hybrid_encrypt`.  That helper encrypts to a
public key but does **not** record *which* key it was encrypted for, so the
server cannot, on its own, tell whether an envelope dropped into a given mailbox
was actually encrypted for that mailbox's owner.

To restore that binding without changing the upstream encryption API, the
depositor attaches a ``recipient_fingerprint`` field to the envelope:
``base64(SHA256(target_pem))``.  The server recomputes the fingerprint from the
``target_pubkey`` of the deposit request and rejects the deposit on mismatch
(see :func:`hivemind_rendezvous.server`).  The fingerprint is not secret — it
only binds an envelope to a mailbox; confidentiality comes from the encryption.
"""

import base64
import hashlib
from typing import Dict, Optional, Union

from hivemind_bus_client.encryption import hybrid_encrypt


def recipient_fingerprint(target_pubkey: str) -> str:
    """Return the mailbox-binding fingerprint for a recipient public key.

    Args:
        target_pubkey: PEM-encoded RSA public key of the recipient (the mailbox
            owner).

    Returns:
        ``base64(SHA256(target_pubkey_utf8))`` — the value carried in the
        ``recipient_fingerprint`` envelope field.
    """
    digest = hashlib.sha256(target_pubkey.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("utf-8")


def make_deposit_envelope(
    target_pubkey: str,
    plaintext: Union[str, bytes],
    sign_key: Optional[Union[str, bytes]] = None,
) -> Dict[str, str]:
    """Encrypt *plaintext* for *target_pubkey* and bind it to that mailbox.

    Produces the dict that becomes the payload of an INTERCOM
    :class:`~hivemind_bus_client.message.HiveMessage` deposited at the
    rendezvous server.  The dict is the output of
    :func:`hivemind_bus_client.encryption.hybrid_encrypt` with an extra
    ``recipient_fingerprint`` field so the server can verify the envelope was
    encrypted for the mailbox it is being deposited into.

    Args:
        target_pubkey: PEM-encoded RSA public key of the recipient.
        plaintext: The bytes/str to encrypt (typically a serialised inner
            :class:`~hivemind_bus_client.message.HiveMessage`).
        sign_key: Optional RSA private key (PEM string/bytes/RsaKey) of the
            depositor, used by ``hybrid_encrypt`` to sign the payload.

    Returns:
        The encryption envelope dict, augmented with ``recipient_fingerprint``.
    """
    envelope = hybrid_encrypt(target_pubkey, plaintext, sign_key=sign_key)
    envelope["recipient_fingerprint"] = recipient_fingerprint(target_pubkey)
    return envelope
