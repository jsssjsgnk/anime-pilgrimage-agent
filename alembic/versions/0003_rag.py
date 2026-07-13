"""Add hybrid RAG document metadata and pgvector chunks.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("knowledge_documents", sa.Column("trip_id", postgresql.UUID(as_uuid=True)))
    op.add_column(
        "knowledge_documents",
        sa.Column("title", sa.String(300), nullable=False, server_default="Untitled"),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_type", sa.String(40), nullable=False, server_default="synthetic_test"),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("authority_level", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column("knowledge_documents", sa.Column("author", sa.String(200)))
    op.add_column(
        "knowledge_documents",
        sa.Column("language", sa.String(20), nullable=False, server_default="und"),
    )
    op.add_column("knowledge_documents", sa.Column("published_at", sa.Date()))
    op.add_column(
        "knowledge_documents",
        sa.Column("accessed_at", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
    )
    op.add_column("knowledge_documents", sa.Column("valid_from", sa.Date()))
    op.add_column("knowledge_documents", sa.Column("valid_until", sa.Date()))
    for name in ("subject_ids", "location_tags", "point_ids"):
        op.add_column(
            "knowledge_documents",
            sa.Column(
                name,
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )
    op.add_column(
        "knowledge_documents",
        sa.Column("content_sha256", sa.String(64), nullable=False, server_default="0" * 64),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
    )
    op.add_column("knowledge_documents", sa.Column("extraction_warning", sa.String(300)))
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_knowledge_namespace_hash", "knowledge_documents", ["namespace", "content_sha256"]
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.String(500)),
        sa.Column("page_start", sa.Integer()),
        sa.Column("page_end", sa.Integer()),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("lexical_tokens", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column(
            "chunk_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_chunk_ordinal"),
    )
    op.execute(
        "ALTER TABLE knowledge_chunks ALTER COLUMN embedding "
        "TYPE vector(384) USING embedding::vector"
    )
    op.create_index(op.f("ix_knowledge_chunks_document_id"), "knowledge_chunks", ["document_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_chunks_document_id"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_constraint("uq_knowledge_namespace_hash", "knowledge_documents", type_="unique")
    for name in (
        "updated_at",
        "extraction_warning",
        "status",
        "content_sha256",
        "point_ids",
        "location_tags",
        "subject_ids",
        "valid_until",
        "valid_from",
        "accessed_at",
        "published_at",
        "language",
        "author",
        "authority_level",
        "source_type",
        "title",
        "trip_id",
    ):
        op.drop_column("knowledge_documents", name)
