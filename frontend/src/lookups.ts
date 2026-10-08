import { api } from "./api";
import type { Camera, Location, Person } from "./types";
import { useApi } from "./useApi";

export interface Lookups {
  cameras: Camera[];
  locations: Location[];
  persons: Person[];
  cameraNames: Map<number, string>;
  locationNames: Map<number, string>;
  personNames: Map<number, string>;
}

const names = (rows: { id: number; name: string }[]) => new Map(rows.map((r) => [r.id, r.name]));

/** Cameras, locations and persons, for filters and for showing names instead of ids. */
export function useLookups(refreshMs?: number) {
  return useApi<Lookups>(
    async () => {
      const [cameras, locations, persons] = await Promise.all([
        api.cameras(),
        api.locations(),
        api.persons(),
      ]);
      return {
        cameras,
        locations,
        persons,
        cameraNames: names(cameras),
        locationNames: names(locations),
        personNames: names(persons),
      };
    },
    [],
    refreshMs,
  );
}
