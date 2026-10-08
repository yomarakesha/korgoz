import { type FormEvent, useState } from "react";

import { api } from "../api";
import { ErrorNote, Notice } from "../components/Notice";
import { StatusBadge, cameraTone } from "../components/StatusBadge";
import { CAMERA_STATUS_LABELS } from "../format";
import { useLookups } from "../lookups";

export function CamerasPage() {
  const lookups = useLookups(10_000);
  const [actionError, setActionError] = useState<Error>();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [locationId, setLocationId] = useState("");
  const [locationName, setLocationName] = useState("");

  async function run(action: () => Promise<unknown>) {
    setActionError(undefined);
    try {
      await action();
      lookups.reload();
    } catch (error) {
      setActionError(error as Error);
    }
  }

  function addCamera(event: FormEvent) {
    event.preventDefault();
    void run(async () => {
      await api.createCamera({ name, stream_url: url, location_id: locationId ? Number(locationId) : null });
      setName("");
      setUrl("");
    });
  }

  function addLocation(event: FormEvent) {
    event.preventDefault();
    void run(async () => {
      await api.createLocation({ name: locationName });
      setLocationName("");
    });
  }

  const data = lookups.data;
  return (
    <section>
      <h1>Камеры</h1>
      <ErrorNote error={lookups.error ?? actionError} />
      <Notice>
        Воркер читает список камер при старте: после добавления, удаления или включения камеры
        перезапустите <code>python -m app.worker</code>.
      </Notice>

      {data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Название</th>
                <th>Статус</th>
                <th>Источник</th>
                <th>Локация</th>
                <th>Включена</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.cameras.map((camera) => (
                <tr key={camera.id}>
                  <td>{camera.id}</td>
                  <td>{camera.name}</td>
                  <td>
                    <StatusBadge tone={cameraTone(camera.status)} label={CAMERA_STATUS_LABELS[camera.status]} />
                  </td>
                  <td>
                    <code>{camera.stream_url_masked}</code> <span className="muted">({camera.source_kind})</span>
                  </td>
                  <td>
                    <select
                      aria-label={`Локация камеры ${camera.name}`}
                      value={camera.location_id ?? ""}
                      onChange={(e) =>
                        void run(() =>
                          api.updateCamera(camera.id, {
                            location_id: e.target.value ? Number(e.target.value) : null,
                          }),
                        )
                      }
                    >
                      <option value="">—</option>
                      {data.locations.map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Камера ${camera.name} включена`}
                      checked={camera.enabled}
                      onChange={(e) => void run(() => api.updateCamera(camera.id, { enabled: e.target.checked }))}
                    />
                  </td>
                  <td>
                    <button
                      type="button"
                      className="danger"
                      onClick={() => {
                        if (window.confirm(`Удалить камеру «${camera.name}» вместе с её треками и событиями?`))
                          void run(() => api.deleteCamera(camera.id));
                      }}
                    >
                      Удалить
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>Добавить камеру</h2>
      <form className="form-row" onSubmit={addCamera}>
        <input placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} required />
        <input
          placeholder="0, rtsp://user:pass@host/stream или путь к видео"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
          className="wide"
        />
        <select aria-label="Локация" value={locationId} onChange={(e) => setLocationId(e.target.value)}>
          <option value="">Без локации</option>
          {data?.locations.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
        <button type="submit">Добавить</button>
      </form>

      <h2>Локации</h2>
      <ul className="plain-list">
        {data?.locations.map((l) => (
          <li key={l.id}>
            {l.name}{" "}
            <button
              type="button"
              className="link-button"
              onClick={() => {
                if (window.confirm(`Удалить локацию «${l.name}»? Камеры останутся без локации.`))
                  void run(() => api.deleteLocation(l.id));
              }}
            >
              удалить
            </button>
          </li>
        ))}
      </ul>
      <form className="form-row" onSubmit={addLocation}>
        <input placeholder="Новая локация" value={locationName} onChange={(e) => setLocationName(e.target.value)} required />
        <button type="submit">Добавить</button>
      </form>
    </section>
  );
}
