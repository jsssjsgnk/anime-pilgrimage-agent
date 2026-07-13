"""Download/load the fixed E5 model and verify its production embedding contract."""

from math import sqrt

from pilgrimage_agent.rag.embedding import SentenceTransformerE5Embedder


def dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def norm(vector: tuple[float, ...]) -> float:
    return sqrt(sum(value * value for value in vector))


def main() -> int:
    embedder = SentenceTransformerE5Embedder()
    query = embedder.embed_query("京都で撮影禁止の表示を見たらどうする?")
    relevant, unrelated = embedder.embed_passages(
        (
            "京都では撮影禁止の表示と現地の案内に従ってください。",
            "Tokyo Metro stations provide information about elevators and accessible routes.",
        )
    )
    assert len(query) == len(relevant) == len(unrelated) == 384
    assert abs(norm(query) - 1.0) < 1e-4
    assert abs(norm(relevant) - 1.0) < 1e-4
    assert dot(query, relevant) > dot(query, unrelated)
    print("PASS: multilingual-e5-small produced normalized 384-d retrieval embeddings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
