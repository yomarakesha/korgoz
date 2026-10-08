"""Timeline (spec §17): a person's history Person → Events → Camera → Location → time."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.database.models import Person
from app.ontology.objects import EventObject
from app.ontology.relations import Ontology


class PersonNotFoundError(LookupError):
    pass


class TimelineService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._ontology = Ontology(session)

    def person_timeline(
        self,
        person_id: int,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EventObject]:
        """Newest first. Includes the enter/leave events of tracks the person was
        recognised on, so a visit shows up as entered → recognized → left."""
        if self._session.get(Person, person_id) is None:
            raise PersonNotFoundError(person_id)
        return self._ontology.events_of_person(
            person_id, since=since, until=until, limit=limit, offset=offset
        )
