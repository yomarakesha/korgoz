import { api } from "../api";
import { EventTable } from "../components/EventTable";
import { ErrorNote } from "../components/Notice";
import { StatCard } from "../components/StatCard";
import { StatusBadge, type Tone, componentTone, healthTone } from "../components/StatusBadge";
import { startOfToday } from "../format";
import { useLookups } from "../lookups";
import type { Health } from "../types";
import { useApi } from "../useApi";

const REFRESH_MS = 10_000;

function healthItems(health: Health): { name: string; tone: Tone; status: string }[] {
  return [
    { name: "Система", tone: healthTone(health.status), status: health.status },
    { name: "БД", tone: componentTone(health.database), status: health.database },
    { name: "Qdrant", tone: componentTone(health.qdrant), status: health.qdrant },
    { name: "Воркер / AI", tone: componentTone(health.ai), status: health.ai },
  ];
}

export function DashboardPage() {
  const lookups = useLookups(REFRESH_MS);
  const live = useApi(
    async () => {
      const since = startOfToday();
      const [health, occupancy, eventsToday, visits, recent] = await Promise.all([
        api.health(),
        api.occupancy(),
        api.eventsCount({ since }),
        api.peopleCount({ since }),
        api.events({ limit: 10 }),
      ]);
      return { health, occupancy, eventsToday, visits, recent };
    },
    [],
    REFRESH_MS,
  );

  const cameras = lookups.data?.cameras ?? [];
  const online = cameras.filter((c) => c.status === "online").length;
  const data = live.data;

  return (
    <section>
      <h1>Обзор</h1>
      <ErrorNote error={live.error ?? lookups.error} />
      <div className="stats">
        <StatCard
          label="Камеры"
          value={cameras.length}
          hint={`онлайн ${online} · офлайн ${cameras.length - online}`}
        />
        <StatCard label="Сейчас в кадре" value={data?.occupancy.total ?? "—"} hint="людей (активные треки)" />
        <StatCard label="Событий сегодня" value={data?.eventsToday.count ?? "—"} />
        <StatCard
          label="Визитов сегодня"
          value={data?.visits.visits ?? "—"}
          hint={data ? `узнано ${data.visits.recognized_persons} · неизвестных ${data.visits.unknown_visits}` : undefined}
        />
      </div>

      {data && (
        <p className="health-line">
          {healthItems(data.health).map(({ name, tone, status }) => (
            <span key={name}>
              {name}: <StatusBadge tone={tone} label={status} />
            </span>
          ))}
        </p>
      )}

      <h2>Последние события</h2>
      {data && lookups.data && (
        <EventTable
          events={data.recent}
          cameraNames={lookups.data.cameraNames}
          locationNames={lookups.data.locationNames}
          personNames={lookups.data.personNames}
        />
      )}
    </section>
  );
}
