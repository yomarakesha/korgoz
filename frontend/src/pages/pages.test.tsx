import { fireEvent, screen, waitFor } from "@testing-library/react";

import { App } from "../App";
import { CAMERAS, LOCATIONS, PERSONS, SETTINGS, mockApi, renderAt } from "../testing";

const EVENT = {
  id: 1,
  event_type: "PERSON_RECOGNIZED",
  timestamp: "2026-10-08T12:00:00Z",
  camera_id: 1,
  location_id: 1,
  person_id: 7,
  track_id: 3,
  confidence: 0.79,
  metadata: { track_identifier: "3" },
};

function baseRoutes() {
  return {
    "/settings": SETTINGS,
    "/health": { status: "ok", database: "ok", qdrant: "ok", ai: "ok", cameras: 1 },
    "/cameras": CAMERAS,
    "/locations": LOCATIONS,
    "/persons": PERSONS,
    "/events": [EVENT],
    "/events/count": { count: 1 },
    "/analytics/occupancy": { at: "2026-10-08T12:00:00Z", total: 2, cameras: [] },
    "/analytics/people-count": {
      period: { since: "", until: "" },
      visits: 5,
      recognized_persons: 1,
      unknown_visits: 2,
    },
    "/analytics/dwell-time": {
      period: { since: "", until: "" },
      sessions: 4,
      average_seconds: 4.5,
      median_seconds: 4.2,
      min_seconds: 3.9,
      max_seconds: 5.8,
    },
    "/analytics/people-flow": {
      period: { since: "", until: "" },
      timezone: "Asia/Tashkent",
      peak_hours: [17],
      buckets: [{ hour: "2026-10-08T17:00:00+05:00", entered: 4, left: 4 }],
    },
    "/analytics/repeat-visitors": [
      { person_id: 7, name: "Alice", visits: 2, first_seen: EVENT.timestamp, last_seen: EVENT.timestamp },
    ],
  };
}

describe("pages", () => {
  it("dashboard shows counters, health and recent events with names", async () => {
    mockApi(baseRoutes());
    renderAt(<App />, "/");
    expect(await screen.findByText("Сейчас в кадре")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Узнан")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Alice" })).toHaveAttribute("href", "/persons/7");
    expect(screen.getAllByText("Hall").length).toBeGreaterThan(0);
    expect(screen.getByText("распознавание")).toBeInTheDocument();
  });

  it("events page sends filters and pages through results", async () => {
    const calls = mockApi({ ...baseRoutes(), "/events/count": { count: 120 } });
    renderAt(<App />, "/events");
    expect(await screen.findByText("Страница 1 из 3")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Вышел"));
    fireEvent.change(screen.getByLabelText("Камера"), { target: { value: "1" } });
    await waitFor(() =>
      expect(calls.some((c) => c.url.search.includes("camera_id=1&event_type=PERSON_LEFT"))).toBe(true),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Старее →" }));
    await waitFor(() => expect(calls.some((c) => c.url.search.includes("offset=50"))).toBe(true));
  });

  it("person page shows the timeline", async () => {
    mockApi({
      ...baseRoutes(),
      "/persons/7": PERSONS[0],
      "/persons/7/timeline": [
        {
          event_id: 1,
          event_type: "PERSON_ENTERED",
          timestamp: EVENT.timestamp,
          confidence: null,
          camera: { id: 1, name: "entrance" },
          location: { id: 1, name: "Hall" },
          track_id: 3,
        },
      ],
    });
    renderAt(<App />, "/persons/7");
    expect(await screen.findByRole("heading", { name: "Alice" })).toBeInTheDocument();
    expect(screen.getByText("Вошёл")).toBeInTheDocument();
    expect(screen.getByText("emp-1")).toBeInTheDocument();
  });

  it("registration shows the API's reason for rejecting a photo", async () => {
    mockApi({
      ...baseRoutes(),
      "/persons": (_url: URL, init?: RequestInit) =>
        init?.method === "POST"
          ? new Response(JSON.stringify({ detail: "Expected one face, found 2" }), { status: 422 })
          : PERSONS,
    });
    renderAt(<App />, "/persons");
    const name = await screen.findByLabelText("Имя");
    await waitFor(() => expect(name).not.toBeDisabled());
    fireEvent.change(name, { target: { value: "Bob" } });
    const photo = screen.getByLabelText("Фото") as HTMLInputElement;
    fireEvent.change(photo, { target: { files: [new File(["x"], "bob.jpg", { type: "image/jpeg" })] } });
    fireEvent.submit(name.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Expected one face, found 2");
  });

  it("registration is disabled in anonymous mode", async () => {
    mockApi({ ...baseRoutes(), "/settings": { ...SETTINGS, vision_mode: "anonymous" } });
    renderAt(<App />, "/persons");
    expect(await screen.findByText(/только в режиме распознавания/)).toBeInTheDocument();
    expect(screen.getByLabelText("Имя")).toBeDisabled();
  });

  it("analytics page shows tiles, chart and repeat visitors", async () => {
    mockApi(baseRoutes());
    renderAt(<App />, "/analytics");
    expect(await screen.findByText("17:00")).toBeInTheDocument();
    expect(screen.getByText("4.2 с")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Входы и выходы по часам" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Alice" })).toBeInTheDocument();
  });

  it("live view shows a stream per camera and a placeholder when it fails", async () => {
    mockApi(baseRoutes());
    renderAt(<App />, "/live");
    const image = await screen.findByAltText("Камера entrance");
    expect(image).toHaveAttribute("src", "/cameras/1/stream");
    fireEvent.error(image);
    expect(screen.getByText(/Нет кадров/)).toBeInTheDocument();
  });

  it("settings page lists configuration without secrets", async () => {
    mockApi(baseRoutes());
    renderAt(<App />, "/settings");
    expect(await screen.findByText("Asia/Tashkent")).toBeInTheDocument();
    expect(screen.getByText("FACE_MATCH_THRESHOLD")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/DATABASE_URL|rtsp/);
  });

  it("cameras page changes a camera's location", async () => {
    const calls = mockApi({
      ...baseRoutes(),
      "/cameras": (_url: URL, init?: RequestInit) => (init?.method === "PATCH" ? CAMERAS[0] : CAMERAS),
    });
    renderAt(<App />, "/cameras");
    const select = await screen.findByLabelText("Локация камеры entrance");
    fireEvent.change(select, { target: { value: "" } });
    await waitFor(() => {
      const patch = calls.find((c) => c.init?.method === "PATCH");
      expect(patch?.url.pathname).toBe("/cameras/1");
      expect(patch?.init?.body).toBe(JSON.stringify({ location_id: null }));
    });
  });
});
