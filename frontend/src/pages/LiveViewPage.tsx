import { useState } from "react";

import { api } from "../api";
import { ErrorNote, Notice } from "../components/Notice";
import { StatusBadge, cameraTone } from "../components/StatusBadge";
import { CAMERA_STATUS_LABELS } from "../format";
import { useLookups } from "../lookups";
import type { Camera } from "../types";

function Stream({ camera }: { camera: Camera }) {
  const [failed, setFailed] = useState(false);
  if (!camera.enabled) return <div className="stream-placeholder">Камера выключена</div>;
  if (failed)
    return (
      <div className="stream-placeholder">
        Нет кадров: воркер не запущен или камера недоступна.{" "}
        <button type="button" className="link-button" onClick={() => setFailed(false)}>
          Повторить
        </button>
      </div>
    );
  // MJPEG from the worker via the API. Boxes and labels ("Track #42" or "Name 0.87")
  // are drawn by the worker, so the browser just shows the image.
  return (
    <img className="stream" src={api.streamUrl(camera.id)} alt={`Камера ${camera.name}`} onError={() => setFailed(true)} />
  );
}

export function LiveViewPage() {
  const lookups = useLookups(10_000);
  const data = lookups.data;
  return (
    <section>
      <h1>Live View</h1>
      <ErrorNote error={lookups.error} />
      {data && data.cameras.length === 0 && <Notice>Камер нет. Добавьте камеру на странице «Камеры».</Notice>}
      <div className="streams">
        {data?.cameras.map((camera) => (
          <article key={camera.id} className="stream-card">
            <header>
              <strong>{camera.name}</strong>
              <span className="muted">
                {camera.location_id ? data.locationNames.get(camera.location_id) : "без локации"}
              </span>
              <StatusBadge tone={cameraTone(camera.status)} label={CAMERA_STATUS_LABELS[camera.status]} />
            </header>
            <Stream camera={camera} />
          </article>
        ))}
      </div>
    </section>
  );
}
