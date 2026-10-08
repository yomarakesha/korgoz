"""Runs `QdrantVectorStore` against a real Qdrant.

Uses QDRANT_URL (default http://localhost:6333) and a throwaway collection
that is deleted at the end. Skipped when Qdrant is unreachable.
"""

import os
import uuid
from collections.abc import Iterator

import numpy as np
import pytest
from qdrant_client import QdrantClient

from app.vector_store.base import VectorStoreError
from app.vector_store.qdrant_store import QdrantVectorStore

pytestmark = pytest.mark.integration

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")


def unit(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


@pytest.fixture
def store() -> Iterator[QdrantVectorStore]:
    collection = f"korgoz_test_{uuid.uuid4().hex[:8]}"
    store = QdrantVectorStore(QDRANT_URL, collection, timeout_seconds=3)
    if not store.health_check():
        pytest.skip(f"Qdrant at {QDRANT_URL} is unreachable")
    yield store
    QdrantClient(url=QDRANT_URL, check_compatibility=False).delete_collection(collection)


def test_add_search_delete(store: QdrantVectorStore) -> None:
    assert store.search(unit(1, 0, 0)) == []  # collection doesn't exist yet
    alice = store.add_embedding(1, unit(1, 0, 0), "test")
    store.add_embedding(2, unit(0, 1, 0), "test")
    store.add_embedding(2, unit(0, 1, 0.1), "test")

    best = store.search(unit(1, 0.1, 0), limit=3)
    assert best[0].person_id == 1
    assert best[0].vector_id == alice
    assert best[0].score == pytest.approx(0.995, abs=1e-3)  # cosine similarity

    store.delete_person(2)
    assert [m.person_id for m in store.search(unit(0, 1, 0), limit=3)] == [1]
    store.delete_embedding(alice)
    assert store.search(unit(1, 0, 0)) == []


def test_create_collection_is_idempotent(store: QdrantVectorStore) -> None:
    store.create_collection(3)
    store.create_collection(3)


def test_unreachable_server_raises_store_error() -> None:
    broken = QdrantVectorStore("http://127.0.0.1:1", "x", timeout_seconds=1)
    assert broken.health_check() is False
    with pytest.raises(VectorStoreError, match=r"ConnectError|ResponseHandlingException"):
        broken.search(unit(1, 0, 0))
