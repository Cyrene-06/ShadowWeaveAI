"""Phase-one foundational subset; remaining R02 columns/tables are staged migrations."""

from alembic import op
from pathlib import Path

namespace = {}
exec(
    compile(
        (Path(__file__).parents[1] / "snapshots" / "foundation_schema.py").read_text(encoding="utf-8"),
        "foundation_schema.py",
        "exec",
    ),
    namespace,
)
metadata = namespace["metadata"]

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade():
    metadata.drop_all(op.get_bind(), checkfirst=False)
