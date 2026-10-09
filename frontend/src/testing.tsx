// Test helpers: a fake API (fetch stub) and rendering inside the router.
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

export type Routes = Record<string, unknown | ((url: URL, init?: RequestInit) => unknown)>;

/** Stubs fetch: the longest route prefix matching the path answers with JSON. */
export function mockApi(routes: Routes) {
  const calls: { url: URL; init?: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    calls.push({ url, init });
    const key = Object.keys(routes)
      .filter((route) => url.pathname === route || url.pathname.startsWith(route + "/"))
      .sort((a, b) => b.length - a.length)[0];
    if (key === undefined) return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
    const handler = routes[key];
    const body = typeof handler === "function" ? handler(url, init) : handler;
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

export function renderAt(element: ReactElement, path = "/") {
  return render(<MemoryRouter initialEntries={[path]}>{element}</MemoryRouter>);
}

export const SETTINGS = {
  app_name: "KörGöz",
  version: "0.1.0",
  environment: "test",
  vision_mode: "recognition",
  person_detector_model: "yolox_s.onnx",
  detection_interval: 3,
  person_confidence_threshold: 0.5,
  tracking_enabled: true,
  track_max_lost_seconds: 3,
  face_match_threshold: 0.4,
  face_min_size: 40,
  face_registration_min_size: 80,
  recognition_interval_seconds: 1,
  events_enabled: true,
  event_cooldown_seconds: 30,
  unknown_after_attempts: 3,
  analytics_timezone: "Asia/Tashkent",
  camera_max_fps: 15,
  live_view_enabled: true,
} as const;

export const CAMERAS = [
  {
    id: 1,
    name: "entrance",
    location_id: 1,
    enabled: true,
    status: "online",
    source_kind: "network",
    stream_url_masked: "rtsp://***:***@cam/1",
    created_at: "2026-10-08T10:00:00Z",
    updated_at: "2026-10-08T10:00:00Z",
  },
];
export const LOCATIONS = [{ id: 1, name: "Hall", description: null }];
export const PERSONS = [
  {
    id: 7,
    name: "Alice",
    external_id: "emp-1",
    description: null,
    status: "active",
    embeddings: 1,
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
  },
];

export const ADMIN = {
  id: 1,
  username: "admin",
  role: "admin",
  is_active: true,
  last_login_at: "2026-10-09T09:00:00Z",
  created_at: "2026-10-01T10:00:00Z",
} as const;
export const VIEWER = { ...ADMIN, id: 2, username: "viewer", role: "user" } as const;
