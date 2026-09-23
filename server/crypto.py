"""Local Fernet helper for the TypeSafe API key."""

from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def load_fernet(data_dir: Path) -> Fernet:
    path = data_dir / "secret.key"
    data_dir.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        key = path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        path.write_bytes(key)
    return Fernet(key)


def encrypt_secret(fernet: Fernet, plaintext: str) -> str:
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(fernet: Fernet, token: str) -> str | None:
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
