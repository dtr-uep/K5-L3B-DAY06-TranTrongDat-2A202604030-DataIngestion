"""TODO: evaluate retrieved evidence and preserve per-query traces."""
import re
import unicodedata
from collections import defaultdict
from typing import Any


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """TODO: check source/page and enough gold evidence; keep hit@1 and hit@3 trace.

    Accept any documented alternative gold evidence. Do not infer human grounding
    or chunk coherence labels from exact string match.
    """
    evidence_quote = question.get("evidence_quote")
    if not isinstance(evidence_quote, str) or not evidence_quote.strip():
        raise ValueError(f"Question {question.get('id')} has no evidence quote")

    gold_source_id = question.get("gold_source_id")
    gold_page = question.get("gold_page")
    gold_pages = gold_page if isinstance(gold_page, list) else [gold_page]
    normalized_evidence = _normalize_evidence(evidence_quote)

    traced_hits: list[dict[str, Any]] = []
    for rank, hit in enumerate(hits, start=1):
        source_match = hit.get("document_id") == gold_source_id
        page_match = str(hit.get("page")) in {str(page) for page in gold_pages}
        evidence_match = (
            source_match
            and page_match
            and normalized_evidence in _normalize_evidence(hit.get("text", ""))
        )
        traced_hits.append(
            {
                **hit,
                "rank": rank,
                "gold_source_match": source_match,
                "gold_page_match": page_match,
                "evidence_match": evidence_match,
            }
        )

    return {
        "question_id": question["id"],
        "split": question["split"],
        "question": question["question"],
        "expected_answer": question["expected_answer"],
        "gold_source_id": gold_source_id,
        "gold_page": gold_page,
        "evidence_quote": evidence_quote,
        "filter": question.get("filter"),
        "hits": traced_hits,
        "hit_at_1": bool(traced_hits and traced_hits[0]["evidence_match"]),
        "evidence_hit_at_3": any(
            hit["evidence_match"] for hit in traced_hits[:3]
        ),
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """TODO: aggregate Hit@1 and Evidence Hit@3 by strategy and dev/test split."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        strategy = trace.get("strategy")
        split = trace.get("split")
        if not strategy or split not in {"dev", "test"}:
            raise ValueError("Each trace must include a strategy and dev/test split")
        grouped[(strategy, split)].append(trace)

    summaries: list[dict[str, Any]] = []
    for (strategy, split), group in sorted(grouped.items()):
        total = len(group)
        hit_at_1 = sum(bool(trace["hit_at_1"]) for trace in group)
        evidence_hit_at_3 = sum(bool(trace["evidence_hit_at_3"]) for trace in group)
        summaries.append(
            {
                "strategy": strategy,
                "split": split,
                "total": total,
                "hit_at_1": {
                    "hits": hit_at_1,
                    "total": total,
                    "rate": hit_at_1 / total,
                },
                "evidence_hit_at_3": {
                    "hits": evidence_hit_at_3,
                    "total": total,
                    "rate": evidence_hit_at_3 / total,
                },
            }
        )
    return {"results": summaries}


def _normalize_evidence(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"(?<=\w)-\s+(?=\w)", "", normalized)
    return " ".join(re.findall(r"\w+", normalized))
