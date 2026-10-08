"""Vector store abstraction for face embeddings.

Only the vector and a minimal payload (`person_id`, `model_name`) are stored:
no names, no images. Deleting a person deletes their points here.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Vector = NDArray[np.float32]


class VectorStoreError(RuntimeError):
    """The vector store is unreachable or rejected the request."""


@dataclass(frozen=True, slots=True)
class VectorMatch:
    vector_id: str
    person_id: int
    score: float  # cosine similarity, higher = more similar


class VectorStore(ABC):
    @abstractmethod
    def create_collection(self, dimension: int) -> None:
        """Create the collection if it does not exist yet (idempotent)."""

    @abstractmethod
    def add_embedding(self, person_id: int, vector: Vector, model_name: str) -> str:
        """Store a vector and return its id."""

    @abstractmethod
    def search(self, vector: Vector, limit: int = 1) -> list[VectorMatch]:
        """Most similar vectors first. Empty if the collection does not exist."""

    @abstractmethod
    def delete_embedding(self, vector_id: str) -> None: ...

    @abstractmethod
    def delete_person(self, person_id: int) -> None:
        """Delete every vector of a person."""

    @abstractmethod
    def health_check(self) -> bool: ...
