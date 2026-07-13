"""Exercise pgvector persistence, hybrid search, isolation, and deletion."""

from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pilgrimage_agent.config import get_settings
from pilgrimage_agent.persistence import KnowledgeRecord
from pilgrimage_agent.rag.embedding import FixtureE5Embedder
from pilgrimage_agent.rag.fixtures import load_fixture_index
from pilgrimage_agent.rag.schemas import IngestedDocument, KnowledgeQuery
from pilgrimage_agent.rag.sql import SqlRagRepository

FIXTURE_ROOT = Path.cwd() / "fixtures" / "rag"


async def main(*, cleanup: bool = False) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    fixture_index, _queries = load_fixture_index(FIXTURE_ROOT)
    fixture_ids = tuple(fixture_index.documents)
    repository = SqlRagRepository(
        sessions, FixtureE5Embedder(), bm25_root=settings.rag_bm25_index_dir
    )
    try:
        if cleanup:
            async with sessions.begin() as session:
                await session.execute(
                    delete(KnowledgeRecord).where(KnowledgeRecord.id.in_(fixture_ids))
                )
            print("PASS: Phase 5 fixture corpus removed from PostgreSQL.")
            return
        async with sessions.begin() as session:
            extension = await session.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            assert extension is not None
        for document_id, document in fixture_index.documents.items():
            chunks = tuple(
                chunk
                for chunk in fixture_index.chunks.values()
                if chunk.document_id == document_id
            )
            await repository.save(IngestedDocument(document=document, chunks=chunks))
        result = await repository.search(
            KnowledgeQuery(
                owner_user_id="golden-user",
                question="Kyoto no-photography notices and private residential lanes",
            )
        )
        assert result.evidence
        assert result.evidence[0].document_id == UUID(
            "11111111-1111-4111-8111-111111111111"
        )
        hidden = await repository.search(
            KnowledgeQuery(
                owner_user_id="another-user",
                question="private low-walking preference elevators seated breaks",
            )
        )
        assert UUID("66666666-6666-4666-8666-666666666666") not in {
            evidence.document_id for evidence in hidden.evidence
        }
        deleted = await repository.delete_document(
            "golden-user", None, UUID("66666666-6666-4666-8666-666666666666")
        )
        assert deleted
        after_delete = await repository.search(
            KnowledgeQuery(
                owner_user_id="golden-user",
                question="private low-walking preference elevators seated breaks",
            )
        )
        assert UUID("66666666-6666-4666-8666-666666666666") not in {
            evidence.document_id for evidence in after_delete.evidence
        }
    finally:
        await engine.dispose()
    print("PASS: exact pgvector + BM25/RRF search is isolated and deletion-consistent.")


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(main(cleanup=arguments.cleanup))
