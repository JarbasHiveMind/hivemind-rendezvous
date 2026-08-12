"""Depositor-side helper for encrypting mail before it is deposited.

A mailbox is addressed by the recipient's **access key** on the rendezvous
node, which is what that node authenticates its clients with. Encryption is a
separate matter and stays entirely with the depositor: the message is encrypted
to the recipient's **public key** with
:func:`hivemind_bus_client.encryption.hybrid_encrypt`, so the relay holds a
blob it has no key for.

Nothing here is enforced by the relay, and this module deliberately does not
claim otherwise. The relay accepts an ``INTERCOM`` message and stores it; it
cannot tell an encrypted envelope from a cleartext dict, and it does not
inspect one to find out. Confidentiality is the depositor's responsibility,
and this helper is how to discharge it.
"""

from typing import Dict, Optional, Union

from hivemind_bus_client.encryption import hybrid_encrypt


def make_deposit_envelope(
    target_pubkey: str,
    plaintext: Union[str, bytes],
    sign_key: Optional[Union[str, bytes]] = None,
) -> Dict[str, str]:
    """Encrypt *plaintext* for the holder of *target_pubkey*.

    The result becomes the payload of the ``INTERCOM``
    :class:`~hivemind_bus_client.message.HiveMessage` that is deposited.

    Args:
        target_pubkey: PEM-encoded RSA public key of the recipient. This is the
            key the message is encrypted **to**; it is not the mailbox address
            (see the module docstring).
        plaintext: The bytes/str to encrypt, typically a serialised inner
            :class:`~hivemind_bus_client.message.HiveMessage`.
        sign_key: Optional RSA private key of the depositor, used by
            ``hybrid_encrypt`` to sign the payload so the recipient can tell
            who sent it.

    Returns:
        The encryption envelope dict.
    """
    return hybrid_encrypt(target_pubkey, plaintext, sign_key=sign_key)
