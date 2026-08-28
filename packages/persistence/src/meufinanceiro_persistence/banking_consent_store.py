"""Actor-aware minimal persistence projection for local banking consent facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import DBAPIError

from meufinanceiro_persistence.banking_models import (
    BankingPersistenceError,
    ConnectionNotFoundError,
    StoredConnectionStatus,
    require_aware,
)
from meufinanceiro_persistence.household_schema import household_memberships
from meufinanceiro_persistence.schema import connections


@dataclass(frozen=True, slots=True, repr=False)
class BankingConsentConnectionSnapshot:
    """Minimum persisted facts needed to classify consent lifecycle."""

    status: StoredConnectionStatus
    consent_expires_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, StoredConnectionStatus):
            raise TypeError("status must be StoredConnectionStatus")
        require_aware(self.consent_expires_at, "consent_expires_at")

    def __repr__(self) -> str:
        return "BankingConsentConnectionSnapshot(<consent-facts-redacted>)"


class BankingConsentConnectionStore:
    """Read consent metadata only after proving active actor membership."""

    def __init__(self, engine: Engine) -> None:
        if not isinstance(engine, Engine):
            raise TypeError("engine must be SQLAlchemy Engine")
        self._engine = engine

    def get_consent_connection_snapshot(
        self,
        *,
        installation_id: UUID,
        residence_id: UUID,
        operator_id: UUID,
        connection_id: UUID,
    ) -> BankingConsentConnectionSnapshot:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    select(
                        func.set_config(
                            "app.current_installation_id",
                            str(installation_id),
                            True,
                        ),
                        func.set_config(
                            "app.current_residence_id",
                            str(residence_id),
                            True,
                        ),
                        func.set_config(
                            "app.current_operator_id",
                            str(operator_id),
                            True,
                        ),
                    )
                )
                membership_id = connection.scalar(
                    select(household_memberships.c.id).where(
                        household_memberships.c.installation_id == installation_id,
                        household_memberships.c.residence_id == residence_id,
                        household_memberships.c.operator_id == operator_id,
                        household_memberships.c.status == "active",
                    )
                )
                if membership_id is None:
                    raise ConnectionNotFoundError(
                        "banking connection was not found"
                    )

                row = (
                    connection.execute(
                        select(
                            connections.c.status,
                            connections.c.consent_expires_at,
                        ).where(
                            connections.c.id == connection_id,
                            connections.c.installation_id == installation_id,
                            connections.c.residence_id == residence_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except BankingPersistenceError:
            raise
        except DBAPIError:
            raise BankingPersistenceError(
                "banking consent metadata could not be read"
            ) from None

        if row is None:
            raise ConnectionNotFoundError("banking connection was not found")
        return BankingConsentConnectionSnapshot(
            status=StoredConnectionStatus(row["status"]),
            consent_expires_at=row["consent_expires_at"],
        )


__all__ = [
    "BankingConsentConnectionSnapshot",
    "BankingConsentConnectionStore",
]
