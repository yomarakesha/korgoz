import { type FormEvent, useState } from "react";

import { api } from "../api";
import { ErrorNote, Notice } from "../components/Notice";
import { StatusBadge, componentTone } from "../components/StatusBadge";
import type { PublicSettings } from "../types";
import { useApi } from "../useApi";

type Row = [label: string, env: string, value: (s: PublicSettings) => string];

const yesNo = (value: boolean) => (value ? "да" : "нет");

const ROWS: Row[] = [
  ["Режим", "VISION_MODE", (s) => (s.vision_mode === "recognition" ? "распознавание лиц" : "анонимный")],
  ["Модель детекции людей", "PERSON_DETECTOR_MODEL_PATH", (s) => s.person_detector_model],
  ["Детекция на каждом N-м кадре", "DETECTION_INTERVAL", (s) => String(s.detection_interval)],
  ["Порог уверенности «человек»", "PERSON_CONFIDENCE_THRESHOLD", (s) => String(s.person_confidence_threshold)],
  ["Макс. FPS камеры", "CAMERA_MAX_FPS", (s) => String(s.camera_max_fps ?? "без ограничения")],
  ["Трекинг", "TRACKING_ENABLED", (s) => yesNo(s.tracking_enabled)],
  ["Человек может пропасть из кадра, с", "TRACK_MAX_LOST_SECONDS", (s) => String(s.track_max_lost_seconds)],
  ["Порог совпадения лица", "FACE_MATCH_THRESHOLD", (s) => String(s.face_match_threshold)],
  ["Мин. размер лица в кадре, px", "FACE_MIN_SIZE", (s) => String(s.face_min_size)],
  ["Мин. размер лица при регистрации, px", "FACE_REGISTRATION_MIN_SIZE", (s) => String(s.face_registration_min_size)],
  ["Повтор распознавания трека, с", "RECOGNITION_INTERVAL_SECONDS", (s) => String(s.recognition_interval_seconds)],
  ["События", "EVENTS_ENABLED", (s) => yesNo(s.events_enabled)],
  ["Антидубли событий, с", "EVENT_COOLDOWN_SECONDS", (s) => String(s.event_cooldown_seconds)],
  ["«Неизвестный» после попыток", "UNKNOWN_AFTER_ATTEMPTS", (s) => String(s.unknown_after_attempts)],
  ["Часовой пояс аналитики", "ANALYTICS_TIMEZONE", (s) => s.analytics_timezone],
  ["Live view", "LIVE_VIEW_ENABLED", (s) => yesNo(s.live_view_enabled)],
];

export function SettingsPage({ settings }: { settings: PublicSettings | undefined }) {
  const health = useApi(() => api.health(), [], 10_000);
  return (
    <section>
      <h1>Настройки</h1>
      <Notice>
        Настройки задаются в файле <code>.env</code> и применяются после перезапуска API и воркера.
        Пароли и адреса камер здесь не показываются.
      </Notice>
      <ErrorNote error={health.error} />
      {health.data && (
        <dl className="facts">
          <dt>База данных</dt>
          <dd>
            <StatusBadge tone={componentTone(health.data.database)} label={health.data.database} />
          </dd>
          <dt>Qdrant</dt>
          <dd>
            <StatusBadge tone={componentTone(health.data.qdrant)} label={health.data.qdrant} />
          </dd>
          <dt>Воркер / AI</dt>
          <dd>
            <StatusBadge tone={componentTone(health.data.ai)} label={health.data.ai} />
          </dd>
        </dl>
      )}
      {settings && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Параметр</th>
                <th>Значение</th>
                <th>Переменная</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([label, env, value]) => (
                <tr key={env}>
                  <td>{label}</td>
                  <td>{value(settings)}</td>
                  <td>
                    <code>{env}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            {settings.app_name} {settings.version} · {settings.environment}
          </p>
        </div>
      )}
      <PasswordForm />
    </section>
  );
}

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<Error>();
  const [done, setDone] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(undefined);
    setDone(false);
    if (next !== repeat) {
      setError(new Error("новые пароли не совпадают"));
      return;
    }
    try {
      await api.changePassword(current, next);
      setDone(true);
      setCurrent("");
      setNext("");
      setRepeat("");
    } catch (reason) {
      setError(reason as Error);
    }
  }

  return (
    <>
      <h2>Сменить мой пароль</h2>
      <p className="muted">Остальные ваши сеансы (другие браузеры и устройства) будут завершены.</p>
      <ErrorNote error={error} />
      {done && <p className="notice notice-ok">Пароль изменён.</p>}
      <form className="form-row" onSubmit={(e) => void submit(e)}>
        <input
          type="password"
          aria-label="Текущий пароль"
          placeholder="Текущий пароль"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          required
        />
        <input
          type="password"
          aria-label="Новый пароль"
          placeholder="Новый пароль"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          required
        />
        <input
          type="password"
          aria-label="Повторите новый пароль"
          placeholder="Повторите новый пароль"
          autoComplete="new-password"
          value={repeat}
          onChange={(e) => setRepeat(e.target.value)}
          required
        />
        <button type="submit">Сменить</button>
      </form>
    </>
  );
}
