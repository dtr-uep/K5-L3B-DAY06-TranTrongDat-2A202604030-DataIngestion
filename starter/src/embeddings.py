"""Choose a real embedding provider (API or local) and implement this contract."""
import math
from typing import Protocol

from sentence_transformers import SentenceTransformer


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """TODO: implement a provider adapter; do not silently fall back to mock vectors."""

    def __init__(self, model_name: str) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be empty")
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        dimension_getter = getattr(self._model, "get_embedding_dimension", None)
        if dimension_getter is None:
            dimension_getter = self._model.get_sentence_embedding_dimension
        dimensions = dimension_getter()
        if dimensions is None or dimensions <= 0:
            raise ValueError(f"Embedding model has invalid dimensions: {model_name}")
        self.dimensions = dimensions
        self.max_sequence_length = self._model.max_seq_length
        self._tokenizer = self._model.tokenizer

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("Document texts must not be empty")
        self._validate_text_lengths(texts)

        embeddings = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if len(embeddings) != len(texts):
            raise RuntimeError("Embedding model returned an unexpected vector count")

        vectors = [
            [float(value) for value in embedding.tolist()]
            for embedding in embeddings
        ]
        for vector in vectors:
            self._validate_vector(vector)
        return vectors

    def embed_query(self, question: str) -> list[float]:
        if not question.strip():
            raise ValueError("Question must not be empty")
        self._validate_text_lengths([question])

        embedding = self._model.encode(
            question,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vector = [float(value) for value in embedding.tolist()]
        self._validate_vector(vector)
        return vector

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False))

    def _validate_text_lengths(self, texts: list[str]) -> None:
        for index, text in enumerate(texts):
            token_count = len(self._tokenizer.encode(text))
            if token_count > self.max_sequence_length:
                raise ValueError(
                    f"Input {index} has {token_count} tokens; model limit is "
                    f"{self.max_sequence_length}"
                )

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self.dimensions:
            raise RuntimeError(
                f"Embedding model returned {len(vector)} values; "
                f"expected {self.dimensions}"
            )
        if not all(math.isfinite(value) for value in vector):
            raise RuntimeError("Embedding model returned non-finite values")
