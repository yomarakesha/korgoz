import type { CameraStatus, EventType } from "./types";

const dateTime = new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "medium" });
const dateOnly = new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" });

export const formatDateTime = (iso: string): string => dateTime.format(new Date(iso));
export const formatDate = (iso: string): string => dateOnly.format(new Date(iso));

/** 75 -> "1 мин 15 с"; 3.9 -> "3.9 с". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Number(seconds.toFixed(1))} с`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} мин ${Math.round(seconds % 60)} с`;
  return `${Math.floor(minutes / 60)} ч ${minutes % 60} мин`;
}

export const formatScore = (value: number | null | undefined): string =>
  value === null || value === undefined ? "—" : value.toFixed(2);

export const EVENT_LABELS: Record<EventType, string> = {
  PERSON_ENTERED: "Вошёл",
  PERSON_LEFT: "Вышел",
  PERSON_RECOGNIZED: "Узнан",
  PERSON_UNKNOWN: "Неизвестный",
  TRACK_STARTED: "Трек начат",
  TRACK_ENDED: "Трек завершён",
  CAMERA_ONLINE: "Камера онлайн",
  CAMERA_OFFLINE: "Камера офлайн",
  PERSON_DETECTED: "Обнаружен",
};

export const CAMERA_STATUS_LABELS: Record<CameraStatus, string> = {
  online: "онлайн",
  offline: "офлайн",
  error: "ошибка",
  unknown: "неизвестно",
};

/** Hour "17" from "2026-10-08T17:00:00+05:00": the hour in the analytics time zone,
 * not in the browser's. */
export const bucketHour = (iso: string): number => Number(iso.slice(11, 13));

/** Value of <input type="datetime-local"> (browser local time) -> ISO UTC. */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** Start of today in the browser's time zone, as ISO UTC. */
export function startOfToday(now: Date = new Date()): string {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  return start.toISOString();
}
