// Shapes of the KörGöz API responses (see docs/api.md).

export type ComponentStatus = "ok" | "unavailable" | "not_configured";

export interface Health {
  status: "ok" | "degraded" | "error";
  database: ComponentStatus;
  qdrant: ComponentStatus;
  ai: ComponentStatus;
  cameras: number;
}

export interface PublicSettings {
  app_name: string;
  version: string;
  environment: string;
  vision_mode: "anonymous" | "recognition";
  person_detector_model: string;
  detection_interval: number;
  person_confidence_threshold: number;
  tracking_enabled: boolean;
  track_max_lost_seconds: number;
  face_match_threshold: number;
  face_min_size: number;
  face_registration_min_size: number;
  recognition_interval_seconds: number;
  events_enabled: boolean;
  event_cooldown_seconds: number;
  unknown_after_attempts: number;
  analytics_timezone: string;
  camera_max_fps: number | null;
  live_view_enabled: boolean;
}

export type CameraStatus = "unknown" | "online" | "offline" | "error";

export interface Camera {
  id: number;
  name: string;
  location_id: number | null;
  enabled: boolean;
  status: CameraStatus;
  source_kind: "usb" | "network" | "file";
  stream_url_masked: string;
  created_at: string;
  updated_at: string;
}

export interface Location {
  id: number;
  name: string;
  description: string | null;
}

export interface Person {
  id: number;
  name: string;
  external_id: string | null;
  description: string | null;
  status: "active" | "inactive";
  embeddings: number;
  created_at: string;
  updated_at: string;
}

export const EVENT_TYPES = [
  "PERSON_ENTERED",
  "PERSON_LEFT",
  "PERSON_RECOGNIZED",
  "PERSON_UNKNOWN",
  "TRACK_STARTED",
  "TRACK_ENDED",
  "CAMERA_ONLINE",
  "CAMERA_OFFLINE",
  "PERSON_DETECTED",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

export interface KorEvent {
  id: number;
  event_type: EventType;
  timestamp: string;
  camera_id: number;
  location_id: number | null;
  person_id: number | null;
  track_id: number | null;
  confidence: number | null;
  metadata: Record<string, unknown>;
}

export interface NamedRef {
  id: number;
  name: string;
}

export interface TimelineEntry {
  event_id: number;
  event_type: EventType;
  timestamp: string;
  confidence: number | null;
  camera: NamedRef;
  location: NamedRef | null;
  track_id: number | null;
}

export interface Period {
  since: string;
  until: string;
}

export interface Occupancy {
  at: string;
  total: number;
  cameras: { camera_id: number; name: string; count: number }[];
}

export interface PeopleCount {
  period: Period;
  visits: number;
  recognized_persons: number;
  unknown_visits: number;
}

export interface DwellTime {
  period: Period;
  sessions: number;
  average_seconds: number | null;
  median_seconds: number | null;
  min_seconds: number | null;
  max_seconds: number | null;
}

export interface FlowBucket {
  hour: string; // ISO with the analytics time zone offset
  entered: number;
  left: number;
}

export interface PeopleFlow {
  period: Period;
  timezone: string;
  peak_hours: number[];
  buckets: FlowBucket[];
}

export interface RepeatVisitor {
  person_id: number;
  name: string;
  visits: number;
  first_seen: string;
  last_seen: string;
}

export type UserRole = "admin" | "user";

export interface User {
  id: number;
  username: string;
  role: UserRole;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export type AuditAction =
  | "LOGIN"
  | "LOGIN_FAILED"
  | "LOGOUT"
  | "PASSWORD_CHANGED"
  | "USER_CREATED"
  | "USER_UPDATED"
  | "USER_DELETED"
  | "CAMERA_CREATED"
  | "CAMERA_UPDATED"
  | "CAMERA_DELETED"
  | "LOCATION_CREATED"
  | "LOCATION_DELETED"
  | "PERSON_REGISTERED"
  | "PERSON_DELETED";

export interface AuditEntry {
  id: number;
  timestamp: string;
  user_id: number | null;
  username: string | null;
  action: AuditAction;
  target_type: string | null;
  target_id: number | null;
  ip_address: string | null;
  details: Record<string, unknown>;
}
