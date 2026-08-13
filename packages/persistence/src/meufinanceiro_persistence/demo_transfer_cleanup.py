"""FK-safe administrative cleanup for transfers in the isolated demo scope."""

from sqlalchemy import select
from sqlalchemy.engine import Connection

from meufinanceiro_persistence.demo_contract import DEMO_INSTALLATION_ID, DEMO_RESIDENCE_ID
from meufinanceiro_persistence.financial_transfer_schema import financial_transfer_legs, financial_transfers


def reset_demo_transfers(connection: Connection) -> bool:
    transfer_ids = select(financial_transfers.c.id).where(
        financial_transfers.c.installation_id == DEMO_INSTALLATION_ID,
        financial_transfers.c.residence_id == DEMO_RESIDENCE_ID,
    )
    results = [
        connection.execute(financial_transfer_legs.delete().where(financial_transfer_legs.c.transfer_id.in_(transfer_ids))),
        connection.execute(financial_transfers.delete().where(
            financial_transfers.c.installation_id == DEMO_INSTALLATION_ID,
            financial_transfers.c.residence_id == DEMO_RESIDENCE_ID,
            financial_transfers.c.role == "REVERSAL",
        )),
        connection.execute(financial_transfers.delete().where(
            financial_transfers.c.installation_id == DEMO_INSTALLATION_ID,
            financial_transfers.c.residence_id == DEMO_RESIDENCE_ID,
        )),
    ]
    return any(bool(result.rowcount) for result in results)
