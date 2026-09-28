from meufinanceiro_persistence.database import Database

from app.core.config import Settings


def create_database(settings: Settings) -> Database:
    return Database(
        settings.database_url.get_secret_value(),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )
