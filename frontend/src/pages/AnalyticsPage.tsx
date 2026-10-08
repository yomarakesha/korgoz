import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { FlowChart } from "../components/FlowChart";
import { ErrorNote, Notice } from "../components/Notice";
import { StatCard } from "../components/StatCard";
import { formatDateTime, formatDuration } from "../format";
import { useLookups } from "../lookups";
import type { PublicSettings } from "../types";
import { useApi } from "../useApi";

export const PRESETS = [
  { key: "24h", label: "24 часа", hours: 24 },
  { key: "7d", label: "7 дней", hours: 24 * 7 },
  { key: "30d", label: "30 дней", hours: 24 * 30 },
] as const;

type PresetKey = (typeof PRESETS)[number]["key"];

export function AnalyticsPage({ settings }: { settings: PublicSettings | undefined }) {
  const lookups = useLookups();
  const [preset, setPreset] = useState<PresetKey>("24h");
  const [camera, setCamera] = useState("");
  const state = useApi(
    async () => {
      const hours = PRESETS.find((p) => p.key === preset)?.hours ?? 24;
      const until = new Date();
      const query = {
        since: new Date(until.getTime() - hours * 3600_000).toISOString(),
        until: until.toISOString(),
        camera_id: camera ? Number(camera) : null,
      };
      const [count, dwell, flow, occupancy, repeat] = await Promise.all([
        api.peopleCount(query),
        api.dwellTime(query),
        api.peopleFlow(query),
        api.occupancy({ camera_id: query.camera_id }),
        api.repeatVisitors(query),
      ]);
      return { count, dwell, flow, occupancy, repeat };
    },
    [preset, camera],
    60_000,
  );

  const data = state.data;
  const recognition = settings?.vision_mode === "recognition";
  return (
    <section>
      <h1>Аналитика</h1>
      <div className="filters">
        <div className="segmented" role="group" aria-label="Период">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              type="button"
              className={p.key === preset ? "active" : ""}
              aria-pressed={p.key === preset}
              onClick={() => setPreset(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
        <label>
          Камера
          <select value={camera} onChange={(e) => setCamera(e.target.value)}>
            <option value="">все</option>
            {lookups.data?.cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ErrorNote error={state.error} />

      {data && (
        <>
          <div className="stats">
            <StatCard label="Визиты" value={data.count.visits} hint="треков за период" />
            <StatCard label="Сейчас в кадре" value={data.occupancy.total} />
            <StatCard
              label="Время пребывания"
              value={formatDuration(data.dwell.median_seconds)}
              hint={`медиана · среднее ${formatDuration(data.dwell.average_seconds)} · сессий ${data.dwell.sessions}`}
            />
            <StatCard
              label="Пиковые часы"
              value={data.flow.peak_hours.length ? data.flow.peak_hours.map((h) => `${h}:00`).join(", ") : "—"}
              hint={data.flow.timezone}
            />
            {recognition && (
              <StatCard
                label="Узнано людей"
                value={data.count.recognized_persons}
                hint={`неизвестных визитов: ${data.count.unknown_visits}`}
              />
            )}
          </div>

          <h2>Поток людей по часам</h2>
          <FlowChart buckets={data.flow.buckets} timezone={data.flow.timezone} />

          {recognition && (
            <>
              <h2>Повторные визиты</h2>
              {data.repeat.length === 0 ? (
                <p className="muted">За период никто не приходил больше одного раза.</p>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Человек</th>
                        <th className="num">Визитов</th>
                        <th>Первый раз</th>
                        <th>Последний раз</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.repeat.map((v) => (
                        <tr key={v.person_id}>
                          <td>
                            <Link to={`/persons/${v.person_id}`}>{v.name}</Link>
                          </td>
                          <td className="num">{v.visits}</td>
                          <td>{formatDateTime(v.first_seen)}</td>
                          <td>{formatDateTime(v.last_seen)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
          <Notice>
            Визит = трек: если человека надолго закрыли и трек разорвался, это два визита.
          </Notice>
        </>
      )}
    </section>
  );
}
