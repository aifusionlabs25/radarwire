"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("sources", sa.Column("id", sa.String(), primary_key=True), sa.Column("workspace_id", sa.String(), nullable=False), sa.Column("name", sa.String(), nullable=False), sa.Column("url", sa.String(), nullable=False), sa.Column("config_json", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("articles", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("workspace_id", sa.String(), nullable=False), sa.Column("source_id", sa.String(), nullable=False), sa.Column("canonical_url", sa.String(), nullable=False), sa.Column("title", sa.String(), nullable=False), sa.Column("author", sa.String()), sa.Column("published_at", sa.DateTime()), sa.Column("content_hash", sa.String(), nullable=False), sa.Column("sanitized_text", sa.Text(), nullable=False), sa.Column("status", sa.String(), nullable=False), sa.Column("first_seen_at", sa.DateTime(), nullable=False), sa.Column("last_seen_at", sa.DateTime(), nullable=False), sa.Column("last_analyzed_hash", sa.String()), sa.UniqueConstraint("workspace_id", "canonical_url", name="uq_article_workspace_url"))
    op.create_table("runs", sa.Column("id", sa.String(), primary_key=True), sa.Column("workspace_id", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False), sa.Column("stage", sa.String(), nullable=False), sa.Column("started_at", sa.DateTime(), nullable=False), sa.Column("finished_at", sa.DateTime()), sa.Column("summary_json", sa.JSON(), nullable=False))
    op.create_table("analysis", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("workspace_id", sa.String(), nullable=False), sa.Column("run_id", sa.String(), nullable=False), sa.Column("article_id", sa.Integer(), nullable=False), sa.Column("content_hash", sa.String(), nullable=False), sa.Column("result_json", sa.JSON(), nullable=False), sa.Column("stdout", sa.Text()), sa.Column("stderr", sa.Text()), sa.Column("exit_code", sa.Integer()), sa.Column("duration_ms", sa.Integer()), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("outbox", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("workspace_id", sa.String(), nullable=False), sa.Column("message_key", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False), sa.Column("recipient", sa.String(), nullable=False), sa.Column("subject", sa.String(), nullable=False), sa.Column("provider_response", sa.Text()), sa.Column("attempt_count", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("sent_at", sa.DateTime()), sa.UniqueConstraint("workspace_id", "message_key", name="uq_outbox_workspace_message"))
    op.create_table("locks", sa.Column("name", sa.String(), primary_key=True), sa.Column("workspace_id", sa.String(), nullable=False), sa.Column("owner", sa.String(), nullable=False), sa.Column("acquired_at", sa.DateTime(), nullable=False), sa.Column("expires_at", sa.DateTime(), nullable=False))
def downgrade():
    for t in ["locks","outbox","analysis","runs","articles","sources"]: op.drop_table(t)
