"""HTTP Basic Auth mit bcrypt-Hash als ASGI-Middleware.

Hash erzeugen: `uv run python -m kubeevents.auth` oder `htpasswd -nbBC 12 <user> <passwort>`.
"""

import asyncio
import base64
import getpass
import hashlib
import hmac
import sys

import bcrypt
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Probes und Prometheus-Scrape laufen ohne Zugangsdaten
PUBLIC_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})

# Kosten für neu erzeugte Hashes
BCRYPT_ROUNDS = 12


def is_bcrypt_hash(value: str) -> bool:
    return value.startswith(("$2a$", "$2b$", "$2y$")) and len(value) == 60


def hash_password(password: str, rounds: int = BCRYPT_ROUNDS) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=rounds)).decode()


class BasicAuthMiddleware:
    """Verlangt Basic Auth für alle Pfade außer PUBLIC_PATHS.

    bcrypt kostet pro Prüfung je nach Rounds 100 ms und mehr. Der Browser schickt die Zugangsdaten mit jedem Request
    mit, deshalb merkt sich die Middleware den SHA-256 korrekter Zugangsdaten und prüft bcrypt nur beim ersten Mal.
    Die Prüfung läuft in einem Thread, damit sie den Event-Loop nicht blockiert.
    """

    def __init__(self, app: ASGIApp, username: str, password_hash: str, realm: str = "kubeevents") -> None:
        self.app = app
        self.username = username.encode()
        self.password_hash = password_hash.encode()
        self.challenge = f'Basic realm="{realm}", charset="UTF-8"'
        self.verified: set[bytes] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        if await self.authorized(Headers(scope=scope).get("authorization")):
            await self.app(scope, receive, send)
            return

        response = PlainTextResponse("Unauthorized", status_code=401, headers={"WWW-Authenticate": self.challenge})
        await response(scope, receive, send)

    async def authorized(self, header: str | None) -> bool:
        credentials = parse_basic(header)
        if credentials is None:
            return False
        username, password = credentials

        digest = hashlib.sha256(username + b":" + password).digest()
        if digest in self.verified:
            return True

        # bcrypt immer prüfen, damit ein falscher Benutzername nicht schneller abgelehnt wird
        password_ok = await asyncio.to_thread(bcrypt.checkpw, password, self.password_hash)
        if hmac.compare_digest(username, self.username) and password_ok:
            self.verified.add(digest)
            return True
        return False


def parse_basic(header: str | None) -> tuple[bytes, bytes] | None:
    """Liefert Benutzer und Passwort aus einem Authorization-Header oder None."""
    if not header:
        return None
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True)
    except ValueError:  # binascii.Error ist eine Unterklasse
        return None
    username, sep, password = decoded.partition(b":")
    if not sep:
        return None
    # bcrypt wertet nur die ersten 72 Byte aus, bcrypt 5 lehnt längere Passwörter ab
    if len(password) > 72:
        return None
    return username, password


def hash_cli() -> None:
    """Fragt ein Passwort ab und gibt den bcrypt-Hash für BASIC_AUTH_PASSWORD_HASH aus."""
    password = getpass.getpass("Passwort: ")
    if password != getpass.getpass("Wiederholen: "):
        sys.exit("Passwörter stimmen nicht überein")
    if not password or len(password.encode()) > 72:
        sys.exit("Passwort muss 1 bis 72 Byte lang sein")
    print(hash_password(password))


if __name__ == "__main__":
    hash_cli()
