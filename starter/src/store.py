"""TODO: store and search vectors using PostgreSQL + pgvector."""
import json
import math
from typing import Any

import psycopg

from .models import Chunk

_TABLE_NAME = "day6_chunks"
_FILTER_FIELDS = {
    "section",
    "year",
    "version",
    "category",
    "audience",
    "language",
    "document_type",
}


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        """TODO: retain connection settings; validate model dimensions."""
        if not database_url.strip():
            raise ValueError("database_url must not be empty")
        if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("dimensions must be a positive integer")
        self.database_url = database_url
        self.dimensions = dimensions

    def create_schema(self) -> None:
        """TODO: create table with vector column and source/page/filter metadata."""
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
                strategy TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                page INTEGER NOT NULL CHECK (page > 0),
                text TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                embedding VECTOR({self.dimensions}) NOT NULL,
                PRIMARY KEY (strategy, chunk_id)
                    )
                    """
                )
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS day6_chunks_metadata_idx "
                    f"ON {_TABLE_NAME} USING GIN (metadata)"
                )

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """TODO: validate lengths/dimensions and write stable IDs without duplicates.

        When re-ingesting changed source documents, remove obsolete chunks too.
        """
        if not strategy.strip():
            raise ValueError("strategy must not be empty")
        if not chunks:
            raise ValueError("chunks must not be empty")
        if len(chunks) != len(vectors):
            raise ValueError("Each chunk must have exactly one embedding vector")

        document_ids: list[str] = []
        rows: list[tuple[str, str, str, str, int, str, str, str]] = []
        for chunk, vector in zip(chunks, vectors):
            if not chunk.chunk_id.strip() or not chunk.document_id.strip():
                raise ValueError("Chunk ID and document ID must not be empty")
            if not chunk.source.strip() or chunk.page <= 0:
                raise ValueError("Chunk source must not be empty and page must be positive")
            if not chunk.text.strip():
                raise ValueError(f"Chunk {chunk.chunk_id} has no text")
            if len(vector) != self.dimensions:
                raise ValueError(
                    f"Chunk {chunk.chunk_id} has vector dimension {len(vector)}; "
                    f"expected {self.dimensions}"
                )
            normalized_vector = [float(value) for value in vector]
            if not all(math.isfinite(value) for value in normalized_vector):
                raise ValueError(f"Chunk {chunk.chunk_id} has non-finite vector values")
            if not isinstance(chunk.metadata, dict):
                raise ValueError(f"Chunk {chunk.chunk_id} metadata must be a dictionary")

            if chunk.document_id not in document_ids:
                document_ids.append(chunk.document_id)
            vector_literal = "[" + ",".join(
                format(value, ".9g") for value in normalized_vector
            ) + "]"
            rows.append(
                (
                    strategy,
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.source,
                    chunk.page,
                    chunk.text,
                    json.dumps(chunk.metadata, ensure_ascii=False),
                    vector_literal,
                )
            )

        insert_sql = f"""
            INSERT INTO {_TABLE_NAME}
                (strategy, chunk_id, document_id, source, page, text, metadata, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
            ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                document_id = EXCLUDED.document_id,
                source = EXCLUDED.source,
                page = EXCLUDED.page,
                text = EXCLUDED.text,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding
        """
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {_TABLE_NAME} "
                    "WHERE strategy = %s AND document_id = ANY(%s)",
                    (strategy, document_ids),
                )
                cursor.executemany(insert_sql, rows)

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """TODO: filter permitted metadata in SQL, rank by cosine distance, return top-k.

        Return chunk ID, text, score and metadata. Parameterize user-supplied values.
        """
        if not strategy.strip():
            raise ValueError("strategy must not be empty")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")
        if len(query_vector) != self.dimensions:
            raise ValueError(
                f"Query vector dimension {len(query_vector)} does not match "
                f"expected dimension {self.dimensions}"
            )
        normalized_vector = [float(value) for value in query_vector]
        if not all(math.isfinite(value) for value in normalized_vector):
            raise ValueError("Query vector contains non-finite values")

        filters = filters or {}
        filter_clauses: list[str] = []
        filter_values: list[str] = []
        for key, value in filters.items():
            if key not in _FILTER_FIELDS:
                raise ValueError(f"Unsupported metadata filter: {key}")
            if value is None or isinstance(value, (dict, list)):
                raise ValueError(f"Filter value for {key} must be a scalar")
            filter_clauses.append("metadata ->> %s = %s")
            filter_values.extend((key, str(value)))

        vector_literal = "[" + ",".join(
            format(value, ".9g") for value in normalized_vector
        ) + "]"
        where_filters = (
            " AND " + " AND ".join(filter_clauses) if filter_clauses else ""
        )
        search_sql = f"""
            SELECT chunk_id, document_id, source, page, text, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM {_TABLE_NAME}
            WHERE strategy = %s{where_filters}
            ORDER BY embedding <=> %s::vector, chunk_id
            LIMIT %s
        """
        parameters = [
            vector_literal,
            strategy,
            *filter_values,
            vector_literal,
            top_k,
        ]
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(search_sql, parameters)
                rows = cursor.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            metadata = row[5]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            results.append(
                {
                    "chunk_id": row[0],
                    "document_id": row[1],
                    "source": row[2],
                    "page": row[3],
                    "text": row[4],
                    "metadata": metadata,
                    "score": float(row[6]),
                }
            )
        return results
