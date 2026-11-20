"""Add the phase-two media catalog, immutable observations and durable job leases."""

from pathlib import Path
from runpy import run_path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _tables():
    # Use frozen metadata rather than reflecting a live connection: offline SQL also works.
    snapshots = Path(__file__).parents[1] / "snapshots"
    foundation = run_path(str(snapshots / "foundation_schema.py"))["metadata"]
    return run_path(str(snapshots / "phase_two_schema.py"))["phase_two_schema"](foundation)


def upgrade():
    for table in _tables():
        table.create(op.get_bind())


def downgrade():
    # Destructive: removes the phase-two catalog and observations. Back up before downgrading.
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind)
