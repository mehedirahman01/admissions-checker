"""add arts type and ownership to university

Revision ID: 8cc94bf7f3de
Revises: c3cb10c7ed28
Create Date: 2026-11-21 22:30:12.539818

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8cc94bf7f3de'
down_revision: Union[str, Sequence[str], None] = 'c3cb10c7ed28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add art colleges as a type, and public/private/church ownership."""
    op.add_column(
        "university",
        sa.Column("ownership", sa.String(length=10), server_default="public", nullable=False),
    )
    op.create_check_constraint(
        "ownership", "university", "ownership IN ('public', 'private', 'church')"
    )
    # Autogenerate does not detect a changed CHECK constraint, so this part is written by hand.
    op.drop_constraint(op.f("ck_university_type"), "university", type_="check")
    op.create_check_constraint(
        "type", "university", "type IN ('university', 'applied_sciences', 'arts')"
    )


def downgrade() -> None:
    """Undo the above. Fails if 'arts' rows still exist, which protects the data."""
    op.drop_constraint(op.f("ck_university_type"), "university", type_="check")
    op.create_check_constraint("type", "university", "type IN ('university', 'applied_sciences')")
    op.drop_constraint(op.f("ck_university_ownership"), "university", type_="check")
    op.drop_column("university", "ownership")
