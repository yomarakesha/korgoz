// Thin typed client for the KörGöz API. Same origin: the API serves the dashboard
// at /ui, and the Vite dev server proxies these paths to uvicorn.
import type {
  AuditAction,
  AuditEntry,
  Camera,
  CameraStatus,
  DwellTime,
  EventType,
  Health,
  KorEvent,
  Location,
  Occupancy,
  PeopleCount,
  PeopleFlow,
  Person,
  PublicSettings,
  RepeatVisitor,
  TimelineEntry,
  User,
  UserRole,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type QueryValue = string | number | boolean | null | undefined | readonly string[];

/** `?a=1&b=x&b=y`; empty values are skipped. */
export function queryString(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((item) => search.append(key, item));
    else search.append(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** FastAPI errors: {"detail": "text"} or, for validation, {"detail": [{"msg": ...}]}. */
function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : ""))
        .filter(Boolean)
        .join("; ");
    }
  }
  return `HTTP ${status}`;
}

/** Fired on any 401 except a failed login: the session is gone, show the login page. */
export const UNAUTHORIZED_EVENT = "korgoz:unauthorized";

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Same origin: the browser sends the HttpOnly session cookie by itself.
  const response = await fetch(path, init);
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    if (response.status === 401 && path !== "/auth/login") {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(response.status, errorMessage(body, response.status));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export interface EventQuery {
  camera_id?: number | null;
  location_id?: number | null;
  person_id?: number | null;
  event_type?: readonly EventType[];
  since?: string | null;
  until?: string | null;
  limit?: number;
  offset?: number;
}

export interface AnalyticsQuery {
  since?: string;
  until?: string;
  camera_id?: number | null;
  location_id?: number | null;
  tz?: string;
}

const q = (params: object) => queryString(params as Record<string, QueryValue>);

export interface AuditQuery {
  user_id?: number | null;
  action?: readonly AuditAction[];
  limit?: number;
  offset?: number;
}

export const api = {
  login: (username: string, password: string) =>
    request<{ user: User }>("/auth/login", json("POST", { username, password })),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<User>("/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/auth/password", json("POST", { current_password, new_password })),

  users: () => request<User[]>("/users"),
  createUser: (body: { username: string; password: string; role: UserRole }) =>
    request<User>("/users", json("POST", body)),
  updateUser: (id: number, body: { role?: UserRole; is_active?: boolean; password?: string }) =>
    request<User>(`/users/${id}`, json("PATCH", body)),
  deleteUser: (id: number) => request<void>(`/users/${id}`, { method: "DELETE" }),
  audit: (query: AuditQuery) => request<AuditEntry[]>(`/audit${q(query)}`),

  health: () => request<Health>("/health"),
  settings: () => request<PublicSettings>("/settings"),

  cameras: () => request<Camera[]>("/cameras"),
  createCamera: (body: { name: string; stream_url: string; location_id: number | null }) =>
    request<Camera>("/cameras", json("POST", body)),
  updateCamera: (id: number, body: { name?: string; location_id?: number | null; enabled?: boolean }) =>
    request<Camera>(`/cameras/${id}`, json("PATCH", body)),
  deleteCamera: (id: number) => request<void>(`/cameras/${id}`, { method: "DELETE" }),
  streamUrl: (id: number) => `/cameras/${id}/stream`,

  locations: () => request<Location[]>("/locations"),
  createLocation: (body: { name: string; description?: string }) =>
    request<Location>("/locations", json("POST", body)),
  deleteLocation: (id: number) => request<void>(`/locations/${id}`, { method: "DELETE" }),

  persons: () => request<Person[]>("/persons"),
  person: (id: number) => request<Person>(`/persons/${id}`),
  registerPerson: (form: FormData) => request<Person>("/persons", { method: "POST", body: form }),
  deletePerson: (id: number) => request<void>(`/persons/${id}`, { method: "DELETE" }),
  timeline: (id: number, limit = 200) =>
    request<TimelineEntry[]>(`/persons/${id}/timeline${q({ limit })}`),

  events: (query: EventQuery) => request<KorEvent[]>(`/events${q(query)}`),
  eventsCount: (query: Omit<EventQuery, "limit" | "offset">) =>
    request<{ count: number }>(`/events/count${q(query)}`),

  occupancy: (query: { camera_id?: number | null } = {}) =>
    request<Occupancy>(`/analytics/occupancy${q(query)}`),
  peopleCount: (query: AnalyticsQuery) => request<PeopleCount>(`/analytics/people-count${q(query)}`),
  dwellTime: (query: AnalyticsQuery) => request<DwellTime>(`/analytics/dwell-time${q(query)}`),
  peopleFlow: (query: AnalyticsQuery) => request<PeopleFlow>(`/analytics/people-flow${q(query)}`),
  repeatVisitors: (query: AnalyticsQuery) =>
    request<RepeatVisitor[]>(`/analytics/repeat-visitors${q(query)}`),
};

export type { CameraStatus };
