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


# --- per-deployment adaptation settings --------------------------------------
#
# Five settings exist so a deployment differing from the verified one needs no
# fork. Each defaults to the value the verified instance already sees, so these
# first assertions are what keep "adding a knob" from changing anyone's wire.


def test_adaptation_settings_default_to_todays_behaviour():
    cfg = EasyvistaConfig(server="https://ev.example.com", account="acme", token="abc")
    assert cfg.extra_headers == {}
    assert cfg.default_params == {}
    assert cfg.user_agent is None
    assert cfg.additional_download_hosts == frozenset()
    assert cfg.verify_ssl is True


@pytest.mark.parametrize("key", ["Authorization", "authorization", "AUTHORIZATION"])
def test_extra_headers_refuses_the_credential_in_any_casing(key):
    # HTTP header names are case-insensitive, so the guard must be too: an
    # Authorization key here would silently shadow config.token with a secret
    # the client cannot see, redact from a repr, or rotate.
    with pytest.raises(ValueError, match="must not set"):
        EasyvistaConfig(
            server="https://ev.example.com",
            account="acme",
            token="abc",
            extra_headers={key: "Bearer other"},
        )


def test_mapping_settings_are_copied_and_read_only():
    # A frozen dataclass holding a live dict is not frozen. Both directions
    # matter: the caller's dict must not stay aliased, and the attribute must
    # not be writable through the mapping.
    headers = {"X-Api-Key": "k"}
    params = {"formatDate": "iso"}
    cfg = EasyvistaConfig(
        server="https://ev.example.com",
        account="acme",
        token="abc",
        extra_headers=headers,
        default_params=params,
    )
    headers["X-Injected"] = "nope"
    params["injected"] = "nope"
    assert cfg.extra_headers == {"X-Api-Key": "k"}
    assert cfg.default_params == {"formatDate": "iso"}
    with pytest.raises(TypeError):
        cfg.extra_headers["X"] = "y"  # type: ignore[index]
    with pytest.raises(TypeError):
        cfg.default_params["x"] = "y"  # type: ignore[index]


def test_config_stays_hashable_with_non_empty_mappings():
    # The regression the explicit __hash__ exists for: the hash @dataclass would
    # generate covers every field, and raises TypeError the moment a mapping
    # field is non-empty.
    cfg = EasyvistaConfig(
        server="https://ev.example.com",
        account="acme",
        token="abc",
        extra_headers={"X-Api-Key": "k"},
        default_params={"formatDate": "iso"},
    )
    assert isinstance(hash(cfg), int)
    assert len({cfg, cfg}) == 1
    twin = EasyvistaConfig(
        server="https://ev.example.com",
        account="acme",
        token="abc",
        extra_headers={"X-Api-Key": "k"},
        default_params={"formatDate": "iso"},
    )
    assert cfg == twin
    assert hash(cfg) == hash(twin)


def test_additional_download_hosts_are_normalised():
    cfg = EasyvistaConfig(
        server="https://ev.example.com",
        account="acme",
        token="abc",
        additional_download_hosts={"CDN.Example.COM ", "  ", "cdn2.example.com"},
    )
    assert cfg.additional_download_hosts == frozenset(
        {"cdn.example.com", "cdn2.example.com"}
    )


def test_repr_does_not_leak_a_secret_in_extra_headers():
    # Headers are the canonical place for a SECOND secret -- an API gateway key,
    # a proxy credential -- so they are redacted for the same reason token and
    # password are.
    cfg = EasyvistaConfig(
        server="https://ev.example.com",
        account="acme",
        token="tok",
        extra_headers={"X-Api-Key": "SECRET"},
    )
    assert "SECRET" not in repr(cfg)


def test_dataclasses_replace_composes_with_from_env(monkeypatch):
    # The documented idiom for adding adaptation settings to an env-built
    # config: from_env deliberately reads none of them, so replace() is how the
    # two compose. Nothing else pins it.
    import dataclasses

    monkeypatch.setenv("EASYVISTA_URL", "https://ev.example.com")
    monkeypatch.setenv("EASYVISTA_ACCOUNT", "acme")
    monkeypatch.setenv("EASYVISTA_TOKEN", "tok123")
    monkeypatch.delenv("EASYVISTA_TOKEN_FILE", raising=False)
    cfg = dataclasses.replace(
        EasyvistaConfig.from_env(), extra_headers={"X-Api-Key": "k"}
    )
    assert cfg.api_root == "https://ev.example.com/api/v1/acme"
    assert cfg.extra_headers == {"X-Api-Key": "k"}
    assert cfg.token == "tok123"


