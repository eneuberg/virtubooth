"""Settings (pydantic-settings): VB_* names, validators, secrets, VB_WEB_DIR, VB_DEV."""

from __future__ import annotations

from pathlib import Path

import pytest

from virtubooth import settings as settings_mod
from virtubooth.settings import ConfigError, Settings

BASE = {
    "VB_PARTY_TOKEN": "test-party-token-0123456789",
    "VB_ADMIN_PASSWORD": "x" * 12,
    "VB_SECRET_KEY": "y" * 32,
}


def test_secrets_never_show_in_repr(tmp_path):
    s = Settings.from_env(BASE | {"VB_DATA_DIR": str(tmp_path)})
    text = repr(s) + str(s) + s.model_dump_json()
    for secret in BASE.values():
        assert secret not in text
    assert s.party_token.get_secret_value() == BASE["VB_PARTY_TOKEN"]


def test_from_env_reads_only_the_given_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("VB_PARTY_NAME", "From the shell")
    s = Settings.from_env(BASE | {"VB_DATA_DIR": str(tmp_path)})
    assert s.party_name == "Party"
    monkeypatch.setenv("VB_PARTY_TOKEN", BASE["VB_PARTY_TOKEN"])
    monkeypatch.setenv("VB_ADMIN_PASSWORD", BASE["VB_ADMIN_PASSWORD"])
    monkeypatch.setenv("VB_SECRET_KEY", BASE["VB_SECRET_KEY"])
    monkeypatch.setenv("VB_DATA_DIR", str(tmp_path))
    assert Settings.from_env().party_name == "From the shell"


def test_defaults_and_blank_values(tmp_path):
    env = BASE | {
        "VB_DATA_DIR": str(tmp_path),
        "VB_PARTY_NAME": "   ",
        "VB_CONSENT_VERSION": "",
        "VB_TIMEZONE": " ",
        "VB_COOKIE_SECURE": "",
        "VB_EXTENSIONS": " , ",
        "VB_MAX_UPLOAD_BYTES": " ",
        "VB_PUBLIC_BASE_URL": " https://party.example/ ",
    }
    s = Settings.from_env(env)
    assert (s.party_name, s.consent_version, s.timezone, s.cookie_secure) == (
        "Party", "1", "Europe/Berlin", "auto",
    )  # fmt: skip
    assert s.extensions is None and s.allowed_origins == ()
    assert s.max_upload_bytes == 8_000_000 and s.admin_session_hours == 12
    assert s.public_base_url == "https://party.example"
    assert s.dev is False


def test_data_dir_defaults_to_dot_data(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert Settings.from_env(BASE).data_dir == tmp_path / "data"


@pytest.mark.parametrize(
    ("name", "value", "says"),
    [
        ("VB_PARTY_TOKEN", "short", "VB_PARTY_TOKEN must be 16-128"),
        ("VB_ADMIN_PASSWORD", "short", "VB_ADMIN_PASSWORD must be at least 12"),
        ("VB_SECRET_KEY", "short", "VB_SECRET_KEY must be at least 32"),
        ("VB_COOKIE_SECURE", "maybe", "VB_COOKIE_SECURE must be auto, true or false"),
        ("VB_UPLOADS_PER_IP_PER_MIN", "many", "VB_UPLOADS_PER_IP_PER_MIN must be an integer"),
        ("VB_DEV", "perhaps", "VB_DEV"),
    ],
)
def test_bad_values_name_the_variable(tmp_path, name, value, says):
    with pytest.raises(ConfigError, match=says):
        Settings.from_env(BASE | {"VB_DATA_DIR": str(tmp_path), name: value})


def test_missing_secrets_say_how_to_get_them():
    with pytest.raises(ConfigError) as exc:
        Settings.from_env({})
    assert "VB_PARTY_TOKEN is not set" in str(exc.value) and "gen-env" in str(exc.value)


def test_web_dir_and_dev(tmp_path, monkeypatch):
    s = Settings.from_env(BASE | {"VB_WEB_DIR": str(tmp_path / "dist"), "VB_DEV": "1"})
    assert s.web_dir == tmp_path / "dist" and s.dev is True
    # default: <repo>/frontend/dist when it exists, else none
    built = tmp_path / "frontend" / "dist"
    monkeypatch.setattr(settings_mod, "DEFAULT_WEB_DIR", built)
    assert Settings.from_env(BASE).web_dir is None
    built.mkdir(parents=True)
    assert Settings.from_env(BASE).web_dir == built


def test_replace_validates(tmp_path):
    s = Settings.from_env(BASE | {"VB_DATA_DIR": str(tmp_path)})
    t = s.replace(max_upload_bytes=10, party_token="n" * 20)
    assert t.max_upload_bytes == 10 and t.party_token.get_secret_value() == "n" * 20
    assert s.max_upload_bytes == 8_000_000  # frozen: a copy
    with pytest.raises(ConfigError):
        s.replace(secret_key="short")


def test_settings_are_frozen(tmp_path):
    s = Settings.from_env(BASE | {"VB_DATA_DIR": str(tmp_path)})
    with pytest.raises(ValueError):
        s.party_name = "x"  # type: ignore[misc]


def test_repo_root_points_at_the_checkout():
    assert (settings_mod.REPO_ROOT / "backend" / "pyproject.toml").is_file()
    assert settings_mod.DEFAULT_WEB_DIR == settings_mod.REPO_ROOT / "frontend" / "dist"
    assert isinstance(settings_mod.REPO_ROOT, Path)
