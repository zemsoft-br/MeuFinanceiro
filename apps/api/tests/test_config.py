from pathlib import Path

from app.core.config import Settings


def test_database_url_is_redacted_from_settings_representation(tmp_path: Path) -> None:
    secret = "database-password-value"
    settings = Settings(
        database_url=f"postgresql://user:{secret}@postgres/database",
        app_keyring_file=tmp_path / "keyring.json",
    )

    assert secret not in repr(settings)
    assert "SecretStr" in repr(settings)
