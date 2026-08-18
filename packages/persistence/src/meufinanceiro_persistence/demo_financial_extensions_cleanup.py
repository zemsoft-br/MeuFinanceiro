"""FK-safe administrative cleanup for post-foundation financial demo rows."""

from sqlalchemy import delete, select
from sqlalchemy.engine import Connection

from meufinanceiro_persistence.demo_contract import (
    DEMO_INSTALLATION_ID,
    DEMO_RESIDENCE_ID,
)
from meufinanceiro_persistence.financial_audit_schema import financial_audit_events
from meufinanceiro_persistence.financial_movement_allocation_schema import (
    financial_movement_allocation_sets,
    financial_movement_allocations,
)


def reset_demo_financial_extensions(connection: Connection) -> bool:
    """Delete audit/allocation rows before their referenced demo resources."""
    changed = False

    audit_result = connection.execute(
        delete(financial_audit_events).where(
            financial_audit_events.c.installation_id == DEMO_INSTALLATION_ID,
            financial_audit_events.c.residence_id == DEMO_RESIDENCE_ID,
        )
    )
    changed |= bool(audit_result.rowcount)

    allocation_result = connection.execute(
        delete(financial_movement_allocations).where(
            financial_movement_allocations.c.installation_id == DEMO_INSTALLATION_ID,
            financial_movement_allocations.c.residence_id == DEMO_RESIDENCE_ID,
        )
    )
    changed |= bool(allocation_result.rowcount)

    allocation_set_ids = connection.scalars(
        select(financial_movement_allocation_sets.c.id)
        .where(
            financial_movement_allocation_sets.c.installation_id
            == DEMO_INSTALLATION_ID,
            financial_movement_allocation_sets.c.residence_id == DEMO_RESIDENCE_ID,
        )
        .order_by(financial_movement_allocation_sets.c.revision.desc())
    ).all()
    for allocation_set_id in allocation_set_ids:
        result = connection.execute(
            delete(financial_movement_allocation_sets).where(
                financial_movement_allocation_sets.c.id == allocation_set_id
            )
        )
        changed |= bool(result.rowcount)

    return changed


__all__ = ["reset_demo_financial_extensions"]
