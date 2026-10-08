"""Qdrant implementation of `VectorStore` (cosine distance).

Client exceptions are wrapped into `VectorStoreError` with the exception type
only: their text can contain the server URL or API key.
"""

import logging
import uuid
from collections.abc import Callable
from typing import TypeVar

from qdrant_client import QdrantClient, models

from app.vector_store.base import Vector, VectorMatch, VectorStore, VectorStoreError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class QdrantVectorStore(VectorStore):
    def __init__(
        self,
        url: str,
        collection: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._collection = collection
        self._client = QdrantClient(
            url=url,
            api_key=api_key,
            timeout=int(max(timeout_seconds, 1)),
            check_compatibility=False,
        )

    def _call(self, action: str, operation: Callable[[], T]) -> T:
        try:
            return operation()
        except Exception as exc:
            logger.warning("Qdrant %s failed: %s", action, type(exc).__name__)
            raise VectorStoreError(f"Qdrant {action} failed: {type(exc).__name__}") from None

    def _exists(self) -> bool:
        return self._call(
            "collection check", lambda: self._client.collection_exists(self._collection)
        )

    def create_collection(self, dimension: int) -> None:
        if self._exists():
            return
        self._call(
            "create collection",
            lambda: self._client.create_collection(
                self._collection,
                vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
            ),
        )
        self._call(
            "create index",
            lambda: self._client.create_payload_index(
                self._collection, "person_id", models.PayloadSchemaType.INTEGER
            ),
        )
        logger.info("Created Qdrant collection %s (dim=%d)", self._collection, dimension)

    def add_embedding(self, person_id: int, vector: Vector, model_name: str) -> str:
        self.create_collection(len(vector))
        vector_id = str(uuid.uuid4())
        point = models.PointStruct(
            id=vector_id,
            vector=vector.astype(float).tolist(),
            payload={"person_id": person_id, "model_name": model_name},
        )
        self._call("upsert", lambda: self._client.upsert(self._collection, [point], wait=True))
        return vector_id

    def search(self, vector: Vector, limit: int = 1) -> list[VectorMatch]:
        if not self._exists():
            return []  # nobody registered yet
        response = self._call(
            "search",
            lambda: self._client.query_points(
                self._collection,
                query=vector.astype(float).tolist(),
                limit=limit,
                with_payload=True,
            ),
        )
        return [
            VectorMatch(
                vector_id=str(point.id),
                person_id=int((point.payload or {})["person_id"]),
                score=float(point.score),
            )
            for point in response.points
        ]

    def delete_embedding(self, vector_id: str) -> None:
        if not self._exists():
            return
        self._call(
            "delete",
            lambda: self._client.delete(
                self._collection, models.PointIdsList(points=[vector_id]), wait=True
            ),
        )

    def delete_person(self, person_id: int) -> None:
        if not self._exists():
            return
        selector = models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(key="person_id", match=models.MatchValue(value=person_id))
                ]
            )
        )
        self._call(
            "delete person", lambda: self._client.delete(self._collection, selector, wait=True)
        )

    def health_check(self) -> bool:
        try:
            self._call("health check", self._client.get_collections)
        except VectorStoreError:
            return False
        return True
