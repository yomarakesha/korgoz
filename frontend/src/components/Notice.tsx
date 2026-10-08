import type { ReactNode } from "react";

export function ErrorNote({ error }: { error: Error | undefined }) {
  if (!error) return null;
  return (
    <p className="notice notice-error" role="alert">
      Ошибка: {error.message}
    </p>
  );
}

export function Notice({ children }: { children: ReactNode }) {
  return <p className="notice">{children}</p>;
}

export function Loading({ show }: { show: boolean }) {
  return show ? <p className="muted">Загрузка…</p> : null;
}
