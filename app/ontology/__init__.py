"""Vision Ontology: domain objects and their relations on top of the ORM.

`objects` are immutable snapshots that the rest of the system (timeline, API,
analytics) can pass around without holding a database session. `relations`
answers graph questions ("which events did this person generate?") with SQL.
"""
