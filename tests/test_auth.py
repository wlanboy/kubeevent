import base64
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kubeevents.auth import hash_password, parse_basic
from kubeevents.config import Settings, get_settings

PASSWORD = "geheim"
# Niedrige Kosten, damit die Tests schnell bleiben
PASSWORD_HASH = hash_password(PASSWORD, rounds=4)


def basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from kubeevents.app import create_app

    monkeypatch.setenv("BASIC_AUTH_USER", "admin")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD_HASH", PASSWORD_HASH)
    get_settings.cache_clear()
    with TestClient(create_app(get_settings(), background=False)) as test_client:
        yield test_client


def test_without_credentials_returns_401(auth_client: TestClient) -> None:
    response = auth_client.get("/events/latest")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith('Basic realm="kubeevents"')


def test_static_files_are_protected(auth_client: TestClient) -> None:
    assert auth_client.get("/static/app.js").status_code == 401


def test_valid_credentials(auth_client: TestClient) -> None:
    assert auth_client.get("/events/latest", headers=basic("admin", PASSWORD)).status_code == 200
    # zweiter Request geht über den Cache
    assert auth_client.get("/", headers=basic("admin", PASSWORD)).status_code == 200


@pytest.mark.parametrize(("user", "password"), [("admin", "falsch"), ("root", PASSWORD), ("", "")])
def test_wrong_credentials(auth_client: TestClient, user: str, password: str) -> None:
    assert auth_client.get("/events/latest", headers=basic(user, password)).status_code == 401


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/metrics"])
def test_public_paths(auth_client: TestClient, path: str) -> None:
    assert auth_client.get(path).status_code == 200


def test_auth_disabled_by_default(client: TestClient) -> None:
    assert client.get("/events/latest").status_code == 200


def test_htpasswd_2y_hash_is_accepted() -> None:
    settings = Settings(basic_auth_user="admin", basic_auth_password_hash=PASSWORD_HASH.replace("$2b$", "$2y$"))
    assert settings.basic_auth_enabled


@pytest.mark.parametrize(
    ("user", "password_hash"),
    [("admin", ""), ("", PASSWORD_HASH), ("admin", "klartext")],
)
def test_invalid_settings(user: str, password_hash: str) -> None:
    with pytest.raises(ValidationError):
        Settings(basic_auth_user=user, basic_auth_password_hash=password_hash)


@pytest.mark.parametrize(
    "header",
    [None, "", "Bearer abc", "Basic", "Basic !!!", "Basic " + base64.b64encode(b"ohne-doppelpunkt").decode()],
)
def test_parse_basic_rejects(header: str | None) -> None:
    assert parse_basic(header) is None


def test_parse_basic_password_with_colon() -> None:
    assert parse_basic(basic("admin", "a:b")["Authorization"]) == (b"admin", b"a:b")
