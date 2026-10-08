import type { ComponentStatus } from "../types";

export type Tone = "good" | "warning" | "critical" | "neutral";

const ICONS: Record<Tone, string> = { good: "●", warning: "▲", critical: "■", neutral: "○" };

/** Status is never color alone: icon + text label (see dataviz status rules). */
export function StatusBadge({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className={`badge badge-${tone}`}>
      <span aria-hidden="true">{ICONS[tone]}</span> {label}
    </span>
  );
}

export function cameraTone(status: string): Tone {
  if (status === "online") return "good";
  if (status === "error") return "critical";
  if (status === "offline") return "warning";
  return "neutral";
}

export function componentTone(status: ComponentStatus | string): Tone {
  if (status === "ok") return "good";
  if (status === "not_configured") return "neutral";
  return "critical";
}

export function healthTone(status: string): Tone {
  if (status === "ok") return "good";
  if (status === "degraded") return "warning";
  return "critical";
}
