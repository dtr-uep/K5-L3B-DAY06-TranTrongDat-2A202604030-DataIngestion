"""Suggested pipeline entry point; TODO: implement the orchestration."""
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import MyEmbedder
from .evaluation import _normalize_evidence, evaluate_query, summarize
from .ingestion import load_pdf
from .store import PgVectorStore

logger = logging.getLogger(__name__)
_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_STRATEGIES = ("A", "B", "C")


def main() -> None:
    """TODO:

    1. Load the corpus and benchmark; validate at least 30 content pages.
    2. Build strategies A (fixed), B (paragraph) and C (B + metadata filter).
    3. Embed with the same model and store vectors/metadata per strategy.
    4. Run the same dev/test questions and save full top-3 traces.
    5. Report retrieval metrics and prepare samples for manual assessment.

    Follow the five dimensions in ../../BENCHMARK.md.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    starter_dir = Path(__file__).resolve().parents[1]
    repository_root = starter_dir.parent
    load_dotenv(starter_dir / ".env")

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is missing. Configure it in starter/.env and start PostgreSQL."
        )

    benchmark_path = repository_root / "benchmark" / "arxiv-questions.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    corpus = benchmark["corpus"]
    source_id = corpus["source_id"]
    source_path = Path(corpus["source"])
    pdf_path = (repository_root / source_path).resolve()
    if repository_root.resolve() not in pdf_path.parents:
        raise ValueError("Benchmark source must be inside the repository")

    pages = load_pdf(pdf_path, source_id, corpus["source"])
    content_pages = [page for page in pages if _is_content_page(page.page, page.text)]
    if len(content_pages) < 30:
        raise ValueError(
            f"Corpus has {len(content_pages)} useful content pages; at least 30 are required"
        )
    page_by_number = {page.page: page for page in content_pages}

    questions = benchmark["questions"]
    _validate_questions(questions, source_id, page_by_number)

    build_started = time.perf_counter()
    chunks_a = [
        chunk
        for page in content_pages
        for chunk in fixed_size(page, size=500, overlap=50)
    ]
    chunks_b = [
        chunk
        for page in content_pages
        for chunk in by_paragraph(page, max_size=700)
    ]
    chunks_by_strategy = {"A": chunks_a, "B": chunks_b, "C": chunks_b}
    build_seconds = time.perf_counter() - build_started

    for question in questions:
        question_filter = question.get("filter")
        if question_filter:
            for key, value in question_filter.items():
                if not any(chunk.metadata.get(key) == value for chunk in chunks_b):
                    raise ValueError(
                        f"Question {question['id']} filter {key}={value!r} "
                        "does not match any chunk metadata"
                    )

    model_name = os.getenv("EMBEDDING_MODEL", "").strip() or _DEFAULT_MODEL
    logger.info("Loading embedding model %s", model_name)
    embedder = MyEmbedder(model_name)

    embedding_seconds: dict[str, float] = {}
    vectors_by_strategy: dict[str, list[list[float]]] = {}
    for strategy in ("A", "B"):
        started = time.perf_counter()
        vectors_by_strategy[strategy] = embedder.embed_documents(
            [chunk.text for chunk in chunks_by_strategy[strategy]]
        )
        embedding_seconds[strategy] = time.perf_counter() - started
    vectors_by_strategy["C"] = vectors_by_strategy["B"]
    embedding_seconds["C"] = 0.0

    chunk_statistics = {
        strategy: _chunk_statistics(chunks, embedder)
        for strategy, chunks in chunks_by_strategy.items()
    }

    store = PgVectorStore(database_url, embedder.dimensions)
    store.create_schema()
    store_started = time.perf_counter()
    for strategy in _STRATEGIES:
        store.upsert(
            strategy,
            chunks_by_strategy[strategy],
            vectors_by_strategy[strategy],
        )
    store_seconds = time.perf_counter() - store_started

    traces: list[dict[str, Any]] = []
    search_started = time.perf_counter()
    for question in questions:
        query_vector = embedder.embed_query(question["question"])
        for strategy in _STRATEGIES:
            query_filter = question.get("filter") if strategy == "C" else None
            hits = store.search(strategy, query_vector, top_k=3, filters=query_filter)
            if query_filter:
                _validate_filter_hits(question["id"], query_filter, hits)
            trace = evaluate_query(question, hits)
            trace["strategy"] = strategy
            traces.append(trace)
    search_seconds = time.perf_counter() - search_started

    metrics = summarize(traces)
    metrics["metadata_filter_compliance"] = _filter_compliance(traces)
    results_dir = starter_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    _write_json(results_dir / "traces.json", traces)
    _write_json(
        results_dir / "grounding_quality.json",
        _grounding_quality(traces),
    )
    _write_json(
        results_dir / "chunk_coherence.json",
        _chunk_coherence(content_pages, chunks_by_strategy),
    )

    metrics.update({
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus": {
            "source_id": source_id,
            "source": corpus["source"],
            "physical_pages": len(pages),
            "useful_content_pages": len(content_pages),
        },
        "benchmark": {
            "path": benchmark_path.relative_to(repository_root).as_posix(),
            "question_count": len(questions),
            "dev_count": sum(question["split"] == "dev" for question in questions),
            "test_count": sum(question["split"] == "test" for question in questions),
            "filter_question_count": sum(
                bool(question.get("filter")) for question in questions
            ),
        },
        "embedding": {
            "provider": "Sentence Transformers (local)",
            "model": model_name,
            "dimensions": embedder.dimensions,
            "normalized": True,
            "max_sequence_length": embedder.max_sequence_length,
        },
        "vector_store": {
            "backend": "PostgreSQL + pgvector",
            "metric": "cosine",
            "search": "exact",
        },
        "strategies": {
            "A": {"chunking": "fixed-size", "size_chars": 500, "overlap_chars": 50},
            "B": {"chunking": "paragraph", "max_size_chars": 700, "filter": False},
            "C": {
                "chunking": "paragraph",
                "max_size_chars": 700,
                "filter": "section when supplied by the question",
            },
        },
        "chunk_statistics": chunk_statistics,
        "timings_seconds": {
            "ingestion_and_chunking": build_seconds,
            "document_embedding": embedding_seconds,
            "database_upsert_all_strategies": store_seconds,
            "query_embedding_and_search_all_strategies": search_seconds,
        },
    })
    _write_json(results_dir / "retrieval_accuracy.json", metrics)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Saved traces and audit templates to {results_dir}")
    print("Manual coherence, metadata, and grounding scores remain for human review.")


def _is_content_page(page_number: int, text: str) -> bool:
    if page_number == 1 or not text.strip():
        return False
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return not re.match(r"^(references|appendix)\b", first_line, re.IGNORECASE)


def _validate_questions(
    questions: list[dict[str, Any]],
    source_id: str,
    page_by_number: dict[int, Any],
) -> None:
    if len(questions) != 20:
        raise ValueError(f"Expected 20 benchmark questions, found {len(questions)}")
    ids = [question.get("id") for question in questions]
    if len(set(ids)) != len(ids):
        raise ValueError("Benchmark question IDs must be unique")

    split_counts = {
        split: sum(question.get("split") == split for question in questions)
        for split in ("dev", "test")
    }
    if split_counts != {"dev": 15, "test": 5}:
        raise ValueError(f"Expected 15 dev / 5 test questions, found {split_counts}")

    filtered = [question for question in questions if question.get("filter")]
    if len(filtered) < 3 or not any(question["split"] == "test" for question in filtered):
        raise ValueError("Benchmark requires at least 3 filtered questions, including a test question")

    required_fields = {
        "id",
        "split",
        "question",
        "expected_answer",
        "gold_source_id",
        "gold_page",
        "evidence_quote",
    }
    for question in questions:
        missing = required_fields - question.keys()
        if missing:
            raise ValueError(f"Question {question.get('id')} is missing fields: {sorted(missing)}")
        if question["split"] not in {"dev", "test"}:
            raise ValueError(f"Question {question['id']} has invalid split")
        if question["gold_source_id"] != source_id:
            raise ValueError(f"Question {question['id']} points to an unexpected source")
        page = page_by_number.get(question["gold_page"])
        if page is None:
            raise ValueError(
                f"Question {question['id']} gold page {question['gold_page']} "
                "is outside the useful content pages"
            )
        evidence = question["evidence_quote"]
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"Question {question['id']} has an empty evidence quote")
        if _normalize_evidence(evidence) not in _normalize_evidence(page.text):
            raise ValueError(
                f"Question {question['id']} evidence does not match extracted page text"
            )
        question_filter = question.get("filter")
        if question_filter is not None and not isinstance(question_filter, dict):
            raise ValueError(f"Question {question['id']} filter must be an object")


def _validate_filter_hits(
    question_id: str,
    filters: dict[str, Any],
    hits: list[dict[str, Any]],
) -> None:
    for hit in hits:
        for key, expected_value in filters.items():
            if hit["metadata"].get(key) != expected_value:
                raise RuntimeError(
                    f"Filtered query {question_id} returned a chunk outside "
                    f"{key}={expected_value!r}"
                )


def _filter_compliance(traces: list[dict[str, Any]]) -> dict[str, Any]:
    filtered_traces = [
        trace
        for trace in traces
        if trace["strategy"] == "C" and trace.get("filter")
    ]
    hit_records = [
        (trace["filter"], hit)
        for trace in filtered_traces
        for hit in trace["hits"]
    ]
    compliant_records = sum(
        all(hit["metadata"].get(key) == value for key, value in filters.items())
        for filters, hit in hit_records
    )
    compliant_questions = sum(
        bool(trace["hits"])
        and all(
            all(hit["metadata"].get(key) == value for key, value in trace["filter"].items())
            for hit in trace["hits"]
        )
        for trace in filtered_traces
    )
    return {
        "strategy": "C",
        "filtered_questions": len(filtered_traces),
        "questions_with_compliant_top3": compliant_questions,
        "question_rate": (
            compliant_questions / len(filtered_traces) if filtered_traces else None
        ),
        "retrieved_records": len(hit_records),
        "compliant_records": compliant_records,
        "record_rate": compliant_records / len(hit_records) if hit_records else None,
    }


def _chunk_statistics(chunks: list[Any], embedder: MyEmbedder) -> dict[str, Any]:
    lengths = [len(chunk.text) for chunk in chunks]
    token_counts = [embedder.count_tokens(chunk.text) for chunk in chunks]
    if not lengths:
        raise ValueError("A strategy produced no chunks")
    return {
        "chunk_count": len(chunks),
        "total_characters": sum(lengths),
        "character_length": {
            "min": min(lengths),
            "mean": round(sum(lengths) / len(lengths), 2),
            "max": max(lengths),
        },
        "total_tokens": sum(token_counts),
        "token_length": {
            "min": min(token_counts),
            "mean": round(sum(token_counts) / len(token_counts), 2),
            "max": max(token_counts),
        },
    }


def _grounding_quality(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    for trace in traces:
        if trace["split"] != "test":
            continue
        audit.append(
            {
                "strategy": trace["strategy"],
                "question_id": trace["question_id"],
                "question": trace["question"],
                "gold_source_id": trace["gold_source_id"],
                "gold_page": trace["gold_page"],
                "top3": [
                    {
                        "rank": hit["rank"],
                        "chunk_id": hit["chunk_id"],
                        "source": hit["source"],
                        "page": hit["page"],
                        "metadata": hit["metadata"],
                        "text": hit["text"],
                        "metadata_correct": None,
                    }
                    for hit in trace["hits"][:3]
                ],
                "grounding_score_0_to_2": None,
                "grounding_reason": "",
            }
        )
    return audit


def _chunk_coherence(
    content_pages: list[Any],
    chunks_by_strategy: dict[str, list[Any]],
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for page in content_pages[:10]:
        first_paragraph = next(
            (paragraph.strip() for paragraph in re.split(r"\n\s*\n+", page.text) if paragraph.strip()),
            page.text.strip(),
        )
        anchor = first_paragraph[:180]
        normalized_anchor = _normalize_evidence(anchor)
        anchor_tokens = normalized_anchor.split()[:12]
        anchor_key = " ".join(anchor_tokens)
        strategy_chunks: dict[str, Any] = {}
        for strategy in _STRATEGIES:
            page_chunks = [
                chunk for chunk in chunks_by_strategy[strategy] if chunk.page == page.page
            ]
            selected = next(
                (
                    chunk
                    for chunk in page_chunks
                    if anchor_key
                    and anchor_key in _normalize_evidence(chunk.text)
                ),
                page_chunks[0] if page_chunks else None,
            )
            strategy_chunks[strategy] = (
                {
                    "chunk_id": selected.chunk_id,
                    "source": selected.source,
                    "page": selected.page,
                    "metadata": selected.metadata,
                    "text": selected.text,
                    "anchor_matched": bool(
                        anchor_key and anchor_key in _normalize_evidence(selected.text)
                    ),
                    "coherence_score_0_to_2": None,
                    "reason": "",
                }
                if selected is not None
                else None
            )
        samples.append(
            {
                "sample_id": f"page-{page.page}",
                "source": page.source,
                "page": page.page,
                "source_anchor": anchor,
                "strategies": strategy_chunks,
            }
        )
    return {
        "method": "First 10 useful content pages; compare chunks around the same page-start passage.",
        "scale": {
            "0": "Cut mid-idea or missing context; not understandable.",
            "1": "Partly understandable but missing context.",
            "2": "Self-contained and preserves the complete idea.",
        },
        "samples": samples,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
