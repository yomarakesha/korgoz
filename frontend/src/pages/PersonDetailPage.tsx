import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { ErrorNote, Loading } from "../components/Notice";
import { EVENT_LABELS, formatDate, formatDateTime, formatScore } from "../format";
import { useApi } from "../useApi";

export function PersonDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const [deleteError, setDeleteError] = useState<Error>();
  const state = useApi(async () => {
    const [person, timeline] = await Promise.all([api.person(id), api.timeline(id)]);
    return { person, timeline };
  }, [id]);

  async function remove() {
    if (!state.data) return;
    if (!window.confirm(`Удалить «${state.data.person.name}» и все векторы его лица? Это необратимо.`)) return;
    try {
      await api.deletePerson(id);
      navigate("/persons");
    } catch (error) {
      setDeleteError(error as Error);
    }
  }

  const data = state.data;
  return (
    <section>
      <Loading show={state.loading && !data} />
      <ErrorNote error={state.error ?? deleteError} />
      {data && (
        <>
          <h1>{data.person.name}</h1>
          <dl className="facts">
            <dt>External ID</dt>
            <dd>{data.person.external_id ?? "—"}</dd>
            <dt>Зарегистрирован</dt>
            <dd>{formatDate(data.person.created_at)}</dd>
            <dt>Векторов лица</dt>
            <dd>{data.person.embeddings}</dd>
            {data.person.description && (
              <>
                <dt>Описание</dt>
                <dd>{data.person.description}</dd>
              </>
            )}
          </dl>
          <button type="button" className="danger" onClick={() => void remove()}>
            Удалить человека
          </button>

          <h2>Timeline</h2>
          {data.timeline.length === 0 ? (
            <p className="muted">Человека ещё не видели камеры.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Время</th>
                    <th>Камера</th>
                    <th>Локация</th>
                    <th>Событие</th>
                    <th className="num">Уверенность</th>
                  </tr>
                </thead>
                <tbody>
                  {data.timeline.map((entry) => (
                    <tr key={entry.event_id}>
                      <td className="nowrap">{formatDateTime(entry.timestamp)}</td>
                      <td>{entry.camera.name}</td>
                      <td>{entry.location?.name ?? "—"}</td>
                      <td>{EVENT_LABELS[entry.event_type] ?? entry.event_type}</td>
                      <td className="num">{formatScore(entry.confidence)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
