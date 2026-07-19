import os
import tempfile
from pathlib import Path

from meufinanceiro_security.keyring import initialize_keyring_file

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

_test_secret_directory = Path(tempfile.mkdtemp(prefix="meufinanceiro-tests-"))
_test_keyring = _test_secret_directory / "keyring.json"
initialize_keyring_file(_test_keyring)
os.environ.setdefault("APP_KEYRING_FILE", str(_test_keyring))
