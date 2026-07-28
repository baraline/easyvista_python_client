import pytest

from easyvista_python_client.config import EasyvistaConfig


def test_token_config_builds_base_url():
    cfg = EasyvistaConfig(server="https://ev.example.com", account="acme", token="abc")
    assert cfg.api_root == "https://ev.example.com/api/v1/acme"
    assert cfg.token == "abc"
    assert cfg.uses_basic_auth is False


def test_server_trailing_slash_is_normalized():
    cfg = EasyvistaConfig(server="https://ev.example.com/", account="acme", token="abc")
    assert cfg.api_root == "https://ev.example.com/api/v1/acme"


def test_basic_auth_config():
    cfg = EasyvistaConfig(
        server="https://ev.example.com", account="acme", login="u", password="p"
    )
    assert cfg.uses_basic_auth is True
    assert cfg.token is None


def test_requires_some_credential():
    with pytest.raises(ValueError, match="credential"):
        EasyvistaConfig(server="https://ev.example.com", account="acme")


def test_from_env_token(monkeypatch):
    monkeypatch.setenv("EASYVISTA_URL", "https://ev.example.com")
    monkeypatch.setenv("EASYVISTA_ACCOUNT", "acme")
    monkeypatch.setenv("EASYVISTA_TOKEN", "tok123")
    monkeypatch.delenv("EASYVISTA_TOKEN_FILE", raising=False)
    cfg = EasyvistaConfig.from_env()
    assert cfg.token == "tok123"
    assert cfg.account == "acme"


def test_from_env_token_file(monkeypatch, tmp_path):
    token_file = tmp_path / "bearer"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setenv("EASYVISTA_SERVER", "https://ev.example.com")
    monkeypatch.setenv("EASYVISTA_ACCOUNT", "acme")
    monkeypatch.delenv("EASYVISTA_TOKEN", raising=False)
    monkeypatch.setenv("EASYVISTA_TOKEN_FILE", str(token_file))
    cfg = EasyvistaConfig.from_env()
    assert cfg.token == "file-token"


def test_from_env_basic(monkeypatch):
    monkeypatch.setenv("EASYVISTA_URL", "https://ev.example.com")
    monkeypatch.setenv("EASYVISTA_ACCOUNT", "acme")
    monkeypatch.delenv("EASYVISTA_TOKEN", raising=False)
    monkeypatch.delenv("EASYVISTA_TOKEN_FILE", raising=False)
    monkeypatch.setenv("EASYVISTA_LOGIN", "u")
    monkeypatch.setenv("EASYVISTA_PASSWORD", "p")
    cfg = EasyvistaConfig.from_env()
    assert cfg.uses_basic_auth is True


def test_repr_does_not_leak_secrets():
    cfg = EasyvistaConfig(
        server="https://ev.example.com", account="acme", token="SECRET"
    )
    assert "SECRET" not in repr(cfg)
    basic = EasyvistaConfig(
        server="https://ev.example.com", account="acme", login="u", password="PW123"
    )
    assert "PW123" not in repr(basic)
