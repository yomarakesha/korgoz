import { useState } from "react";

import { type EventQuery, api } from "../api";
import { EventTable } from "../components/EventTable";
import { ErrorNote } from "../components/Notice";
import { EVENT_LABELS, localInputToIso } from "../format";
import { useLookups } from "../lookups";
import { EVENT_TYPES, type EventType } from "../types";
import { useApi } from "../useApi";

export const PAGE_SIZE = 50;

interface Filters {
  since: string; // datetime-local values (browser time)
  until: string;
  camera: string;
  location: string;
  person: string;
  types: EventType[];
}

const EMPTY: Filters = { since: "", until: "", camera: "", location: "", person: "", types: [] };

export function toQuery(filters: Filters): Omit<EventQuery, "limit" | "offset"> {
  const id = (value: string) => (value ? Number(value) : null);
  return {
    since: localInputToIso(filters.since),
    until: localInputToIso(filters.until),
    camera_id: id(filters.camera),
    location_id: id(filters.location),
    person_id: id(filters.person),
    event_type: filters.types,
  };
}

export function EventsPage() {
  const lookups = useLookups();
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [page, setPage] = useState(0);
  const query = toQuery(filters);
  const key = JSON.stringify(query);
  const events = useApi(
    async () => {
      const [rows, total] = await Promise.all([
        api.events({ ...query, limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
        api.eventsCount(query),
      ]);
      return { rows, total: total.count };
    },
    [key, page],
  );

  function update(change: Partial<Filters>) {
    setFilters({ ...filters, ...change });
    setPage(0);
  }

  function toggleType(type: EventType) {
    update({
      types: filters.types.includes(type) ? filters.types.filter((t) => t !== type) : [...filters.types, type],
    });
  }

  const pages = events.data ? Math.max(1, Math.ceil(events.data.total / PAGE_SIZE)) : 1;
  return (
    <section>
      <h1>События</h1>
      <div className="filters">
        <label>
          С
          <input type="datetime-local" value={filters.since} onChange={(e) => update({ since: e.target.value })} />
        </label>
        <label>
          По
          <input type="datetime-local" value={filters.until} onChange={(e) => update({ until: e.target.value })} />
        </label>
        <label>
          Камера
          <select value={filters.camera} onChange={(e) => update({ camera: e.target.value })}>
            <option value="">все</option>
            {lookups.data?.cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Локация
          <select value={filters.location} onChange={(e) => update({ location: e.target.value })}>
            <option value="">все</option>
            {lookups.data?.locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Человек
          <select value={filters.person} onChange={(e) => update({ person: e.target.value })}>
            <option value="">все</option>
            {lookups.data?.persons.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="link-button" onClick={() => update(EMPTY)}>
          Сбросить
        </button>
      </div>
      <fieldset className="type-filter">
        <legend>Тип события</legend>
        {EVENT_TYPES.filter((t) => t !== "PERSON_DETECTED").map((type) => (
          <label key={type}>
            <input type="checkbox" checked={filters.types.includes(type)} onChange={() => toggleType(type)} />{" "}
            {EVENT_LABELS[type]}
          </label>
        ))}
      </fieldset>

      <ErrorNote error={events.error ?? lookups.error} />
      {events.data && lookups.data && (
        <>
          <p className="muted">Найдено: {events.data.total}. Новые сверху.</p>
          <EventTable
            events={events.data.rows}
            cameraNames={lookups.data.cameraNames}
            locationNames={lookups.data.locationNames}
            personNames={lookups.data.personNames}
          />
          <div className="pager">
            <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>
              ← Новее
            </button>
            <span>
              Страница {page + 1} из {pages}
            </span>
            <button type="button" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
              Старее →
            </button>
          </div>
        </>
      )}
    </section>
  );
}
