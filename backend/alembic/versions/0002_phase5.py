"""Phase 5: tenant isolation, adaptive policy, jobs."""

from alembic import op
import sqlalchemy as sa

revision = "0002_phase5"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="TENANT_DEFAULT"))
    op.create_index("ix_transactions_tenant_id", "transactions", ["tenant_id"])
    op.add_column("audit_events", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="TENANT_DEFAULT"))
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.add_column("guardrail_results", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="TENANT_DEFAULT"))
    op.add_column("routing_attempts", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="TENANT_DEFAULT"))
    op.add_column("routing_attempts", sa.Column("error_code", sa.String(64), nullable=False, server_default=""))
    op.add_column("batches", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="TENANT_DEFAULT"))
    op.add_column("idempotency_keys", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="TENANT_DEFAULT"))
    op.add_column("rail_outcomes", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="TENANT_DEFAULT"))
    op.add_column("webhook_events", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="TENANT_DEFAULT"))
    op.add_column("routing_events", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="TENANT_DEFAULT"))

    op.drop_constraint("uq_idempotency_key_endpoint", "idempotency_keys", type_="unique")
    op.create_unique_constraint("uq_idempotency_tenant_key_endpoint", "idempotency_keys", ["tenant_id", "key", "endpoint"])

    op.rename_table("circuit_states", "circuit_states_old")
    op.create_table(
        "circuit_states",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("rail", sa.String(64), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="CLOSED"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("baseline_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("zscore", sa.Float(), nullable=False, server_default="0"),
        sa.Column("opened_by", sa.String(32), nullable=False, server_default="threshold"),
    )
    op.execute(
        "INSERT INTO circuit_states (tenant_id, rail, state, opened_at, cooldown_until, failure_rate, samples) "
        "SELECT 'TENANT_DEFAULT', rail, state, opened_at, cooldown_until, failure_rate, samples FROM circuit_states_old"
    )
    op.drop_table("circuit_states_old")

    op.create_table(
        "route_scores",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("error_code", sa.String(64), primary_key=True),
        sa.Column("rail", sa.String(64), primary_key=True),
        sa.Column("success_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "policy_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
    )
    op.create_table(
        "policy_thresholds",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("amount_limit", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("predict_fail_threshold", sa.Float(), nullable=False, server_default="0.65"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rationale", sa.Text(), nullable=False, server_default="Initial policy."),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("kind", sa.String(64), nullable=False, index=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "rate_hits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bucket", sa.String(128), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("rate_hits")
    op.drop_table("jobs")
    op.drop_table("policy_thresholds")
    op.drop_table("policy_snapshots")
    op.drop_table("route_scores")
