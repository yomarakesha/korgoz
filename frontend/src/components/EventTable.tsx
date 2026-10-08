import { Link } from "react-router-dom";

import { EVENT_LABELS, formatDateTime, formatScore } from "../format";
import type { KorEvent } from "../types";

export function EventTable({
  events,
  cameraNames,
  locationNames,
  personNames,
}: {
  events: KorEvent[];
  cameraNames: Map<number, string>;
  locationNames: Map<number, string>;
  personNames: Map<number, string>;
}) {
  if (events.length === 0) return <p className="muted">Событий нет.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Время</th>
            <th>Событие</th>
            <th>Камера</th>
            <th>Локация</th>
            <th>Человек</th>
            <th className="num">Уверенность</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.id}>
              <td className="nowrap">{formatDateTime(event.timestamp)}</td>
              <td>
                <span className={`event-type event-${event.event_type.toLowerCase()}`}>
                  {EVENT_LABELS[event.event_type] ?? event.event_type}
                </span>
                {event.metadata.track_identifier !== undefined && (
                  <span className="muted"> · трек #{String(event.metadata.track_identifier)}</span>
                )}
              </td>
              <td>{cameraNames.get(event.camera_id) ?? `#${event.camera_id}`}</td>
              <td>{event.location_id ? (locationNames.get(event.location_id) ?? "—") : "—"}</td>
              <td>
                {event.person_id ? (
                  <Link to={`/persons/${event.person_id}`}>
                    {personNames.get(event.person_id) ?? `#${event.person_id}`}
                  </Link>
                ) : (
                  "—"
                )}
              </td>
              <td className="num">{formatScore(event.confidence)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
