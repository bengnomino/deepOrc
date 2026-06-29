"""WireGuard key generation and management."""

from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


@dataclass(frozen=True)
class WireGuardKeyPair:
    private_key: str
    public_key: str


def _b64_encode(key_bytes: bytes) -> str:
    import base64

    return base64.b64encode(key_bytes).decode("ascii")


def generate_keypair() -> WireGuardKeyPair:
    private = X25519PrivateKey.generate()
    private_bytes = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return WireGuardKeyPair(
        private_key=_b64_encode(private_bytes),
        public_key=_b64_encode(public_bytes),
    )
