"""Tests for the discogs-setup CLI tool (api/setup.py)."""

from unittest.mock import MagicMock, call, patch

import pytest


class TestMask:
    """Tests for the _mask helper."""

    def test_empty_string(self) -> None:
        from api.setup import _mask

        assert _mask("") == "(not set)"

    def test_short_value_fully_masked(self) -> None:
        from api.setup import _mask

        assert _mask("ab") == "****"
        assert _mask("abcd") == "****"

    def test_longer_value_shows_first_and_last(self) -> None:
        from api.setup import _mask

        result = _mask("abcdefgh")
        assert result.startswith("ab")
        assert result.endswith("gh")
        assert "****" in result

    def test_mask_length_matches_original(self) -> None:
        from api.setup import _mask

        value = "1234567890"
        result = _mask(value)
        assert len(result) == len(value)


class TestBuildConninfo:
    """Tests for _build_conninfo."""

    def test_builds_conninfo_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from api.setup import _build_conninfo

        monkeypatch.setenv("POSTGRES_ADDRESS", "db:5432")
        monkeypatch.setenv("POSTGRES_USERNAME", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pass")
        monkeypatch.setenv("POSTGRES_DATABASE", "mydb")

        conninfo = _build_conninfo()
        assert "host=db" in conninfo
        assert "port=5432" in conninfo
        assert "user=user" in conninfo
        assert "password=pass" in conninfo
        assert "dbname=mydb" in conninfo

    def test_address_without_port_defaults_to_5432(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from api.setup import _build_conninfo

        monkeypatch.setenv("POSTGRES_ADDRESS", "myhost")
        monkeypatch.setenv("POSTGRES_USERNAME", "u")
        monkeypatch.setenv("POSTGRES_PASSWORD", "p")
        monkeypatch.setenv("POSTGRES_DATABASE", "d")

        conninfo = _build_conninfo()
        assert "host=myhost" in conninfo
        assert "port=5432" in conninfo

    def test_missing_env_vars_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from api.setup import _build_conninfo

        for var in ("POSTGRES_ADDRESS", "POSTGRES_USERNAME", "POSTGRES_PASSWORD", "POSTGRES_DATABASE"):
            monkeypatch.delenv(var, raising=False)

        with pytest.raises(SystemExit) as exc_info:
            _build_conninfo()
        assert exc_info.value.code == 1

    def test_partial_missing_env_vars_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from api.setup import _build_conninfo

        monkeypatch.setenv("POSTGRES_ADDRESS", "db:5432")
        monkeypatch.delenv("POSTGRES_USERNAME", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.delenv("POSTGRES_DATABASE", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            _build_conninfo()
        assert exc_info.value.code == 1


class TestShowConfig:
    """Tests for show_config."""

    def test_show_prints_masked_values(self, capsys: pytest.CaptureFixture[str]) -> None:
        from api.setup import show_config

        mock_rows = [
            {"key": "discogs_consumer_key", "value": "mykey12345"},
            {"key": "discogs_consumer_secret", "value": "mysecret678"},
        ]

        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall = MagicMock(return_value=mock_rows)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=mock_cur)

        with patch("psycopg.connect", return_value=mock_conn):
            show_config("host=localhost dbname=test")

        captured = capsys.readouterr()
        assert "discogs_consumer_key" in captured.out
        assert "discogs_consumer_secret" in captured.out
        # Values should be masked, not shown in plain text
        assert "mykey12345" not in captured.out
        assert "mysecret678" not in captured.out

    def test_show_decrypts_encrypted_values(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        from cryptography.fernet import Fernet

        from api.setup import show_config

        encryption_key = Fernet.generate_key().decode("ascii")
        monkeypatch.setenv("OAUTH_ENCRYPTION_KEY", encryption_key)

        f = Fernet(encryption_key.encode("ascii"))
        encrypted_key = f.encrypt(b"mykey12345").decode("ascii")
        encrypted_secret = f.encrypt(b"mysecret678").decode("ascii")

        mock_rows = [
            {"key": "discogs_consumer_key", "value": encrypted_key},
            {"key": "discogs_consumer_secret", "value": encrypted_secret},
        ]

        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall = MagicMock(return_value=mock_rows)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=mock_cur)

        with patch("psycopg.connect", return_value=mock_conn):
            show_config("host=localhost dbname=test")

        captured = capsys.readouterr()
        # Decrypted values should be masked (first/last 2 chars visible)
        assert "my" in captured.out  # first 2 chars of "mykey12345"
        assert "45" in captured.out  # last 2 chars of "mykey12345"
        # Raw encrypted ciphertext must not appear in output
        assert encrypted_key not in captured.out
        assert encrypted_secret not in captured.out

    def test_show_handles_unset_values(self, capsys: pytest.CaptureFixture[str]) -> None:
        from api.setup import show_config

        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall = MagicMock(return_value=[])  # no rows

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=mock_cur)

        with patch("psycopg.connect", return_value=mock_conn):
            show_config("host=localhost dbname=test")

        captured = capsys.readouterr()
        assert "(not set)" in captured.out


class TestSetConfig:
    """Tests for set_config."""

    def test_upserts_both_keys(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        from api.setup import set_config

        monkeypatch.delenv("OAUTH_ENCRYPTION_KEY", raising=False)

        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=mock_cur)

        with patch("psycopg.connect", return_value=mock_conn):
            set_config("host=localhost dbname=test", "mykey", "mysecret")

        # Two execute calls: one for each credential
        assert mock_cur.execute.call_count == 2
        calls = mock_cur.execute.call_args_list
        assert calls[0] == call(
            mock_cur.execute.call_args_list[0][0][0],
            ("discogs_consumer_key", "mykey"),
        )
        assert calls[1] == call(
            mock_cur.execute.call_args_list[1][0][0],
            ("discogs_consumer_secret", "mysecret"),
        )

        captured = capsys.readouterr()
        assert "✅" in captured.out
        assert "updated successfully" in captured.out

    def test_encrypts_values_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cryptography.fernet import Fernet

        from api.setup import set_config

        encryption_key = Fernet.generate_key().decode("ascii")
        monkeypatch.setenv("OAUTH_ENCRYPTION_KEY", encryption_key)

        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor = MagicMock(return_value=mock_cur)

        with patch("psycopg.connect", return_value=mock_conn):
            set_config("host=localhost dbname=test", "mykey", "mysecret")

        calls = mock_cur.execute.call_args_list
        stored_key_val = calls[0][0][1][1]
        stored_secret_val = calls[1][0][1][1]

        # Stored values must not be the original plaintext
        assert stored_key_val != "mykey"
        assert stored_secret_val != "mysecret"

        # Stored values must decrypt back to originals
        f = Fernet(encryption_key.encode("ascii"))
        assert f.decrypt(stored_key_val.encode("ascii")).decode("utf-8") == "mykey"
        assert f.decrypt(stored_secret_val.encode("ascii")).decode("utf-8") == "mysecret"


class TestMain:
    """Tests for the main() entry point."""

    def test_help_exits_cleanly(self) -> None:
        from api.setup import main

        with pytest.raises(SystemExit) as exc_info, patch("sys.argv", ["discogs-setup", "--help"]):
            main()
        assert exc_info.value.code == 0

    def test_no_args_exits_with_error(self) -> None:
        from api.setup import main

        with pytest.raises(SystemExit) as exc_info, patch("sys.argv", ["discogs-setup"]):
            main()
        assert exc_info.value.code != 0

    def test_consumer_key_without_secret_exits_with_error(self) -> None:
        from api.setup import main

        with pytest.raises(SystemExit) as exc_info, patch("sys.argv", ["discogs-setup", "--consumer-key", "mykey"]):
            main()
        assert exc_info.value.code != 0

    def test_consumer_secret_without_key_exits_with_error(self) -> None:
        from api.setup import main

        with pytest.raises(SystemExit) as exc_info, patch("sys.argv", ["discogs-setup", "--consumer-secret", "mysecret"]):
            main()
        assert exc_info.value.code != 0

    def test_show_and_key_together_exits_with_error(self) -> None:
        from api.setup import main

        with pytest.raises(SystemExit) as exc_info, patch("sys.argv", ["discogs-setup", "--show", "--consumer-key", "k"]):
            main()
        assert exc_info.value.code != 0

    def test_show_calls_show_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from api.setup import main

        monkeypatch.setenv("POSTGRES_ADDRESS", "db:5432")
        monkeypatch.setenv("POSTGRES_USERNAME", "u")
        monkeypatch.setenv("POSTGRES_PASSWORD", "p")
        monkeypatch.setenv("POSTGRES_DATABASE", "d")

        with (
            patch("sys.argv", ["discogs-setup", "--show"]),
            patch("api.setup.show_config") as mock_show,
        ):
            main()

        mock_show.assert_called_once()

    def test_set_credentials_calls_set_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from api.setup import main

        monkeypatch.setenv("POSTGRES_ADDRESS", "db:5432")
        monkeypatch.setenv("POSTGRES_USERNAME", "u")
        monkeypatch.setenv("POSTGRES_PASSWORD", "p")
        monkeypatch.setenv("POSTGRES_DATABASE", "d")

        with (
            patch("sys.argv", ["discogs-setup", "--consumer-key", "mykey", "--consumer-secret", "mysecret"]),
            patch("api.setup.set_config") as mock_set,
        ):
            main()

        mock_set.assert_called_once()
        _, call_key, call_secret = mock_set.call_args[0]
        assert call_key == "mykey"
        assert call_secret == "mysecret"
