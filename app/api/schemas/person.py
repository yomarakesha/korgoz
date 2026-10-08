from datetime import datetime

from pydantic import BaseModel

from app.database.models import Person, PersonStatus


class PersonRead(BaseModel):
    id: int
    name: str
    external_id: str | None
    description: str | None
    status: PersonStatus
    embeddings: int  # number of registered face vectors (the vectors themselves never leave Qdrant)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, person: Person) -> "PersonRead":
        return cls(
            id=person.id,
            name=person.name,
            external_id=person.external_id,
            description=person.description,
            status=person.status,
            embeddings=len(person.embeddings),
            created_at=person.created_at,
            updated_at=person.updated_at,
        )
