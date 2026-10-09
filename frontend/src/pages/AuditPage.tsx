import { useState } from "react";

import { api } from "../api";
import { ErrorNote } from "../components/Notice";
import { formatDateTime } from "../format";
import type { AuditAction, AuditEntry } from "../types";
import { useApi } from "../useApi";

const PAGE_SIZE = 50;

export const AUDIT_LABELS: Record<AuditAction, string> = {
  LOGIN: "Вход",
  LOGIN_FAILED: "Неудачный вход",
  LOGOUT: "Выход",
  PASSWORD_CHANGED: "Смена своего пароля",
  USER_CREATED: "Пользователь создан",
  USER_UPDATED: "Пользователь изменён",
  USER_DELETED: "Пользователь удалён",
  CAMERA_CREATED: "Камера добавлена",
  CAMERA_UPDATED: "Камера изменена",
  CAMERA_DELETED: "Камера удалена",
  LOCATION_CREATED: "Локация добавлена",
  LOCATION_DELETED: "Локация удалена",
  PERSON_REGISTERED: "Человек зарегистрирован",
  PERSON_DELETED: "Человек удалён",
};

function describeTarget(entry: AuditEntry): string {
  if (!entry.target_type) return "";
  return `${entry.target_type} #${entry.target_id ?? "?"}`;
}

function describeDetails(details: Record<string, unknown>): string {
  return Object.entries(details)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join("; ");
}

export function AuditPage() {
  const [action, setAction] = useState("");
  const [userId, setUserId] = useState("");
  const [page, setPage] = useState(0);
  const users = useApi(() => api.users(), []);
  const entries = useApi(
    () =>
      api.audit({
        action: action ? [action as AuditAction] : undefined,
        user_id: userId ? Number(userId) : null,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    [action, userId, page],
  );

  return (
    <section>
      <h1>Журнал аудита</h1>
      <p className="muted">
        Кто, когда и откуда входил и что менял. Пароли, адреса камер и данные лиц сюда не пишутся.
      </p>
      <div className="filters">
        <label>
          Действие
          <select
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setPage(0);
            }}
          >
            <option value="">все</option>
            {(Object.keys(AUDIT_LABELS) as AuditAction[]).map((a) => (
              <option key={a} value={a}>
                {AUDIT_LABELS[a]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Пользователь
          <select
            value={userId}
            onChange={(e) => {
              setUserId(e.target.value);
              setPage(0);
            }}
          >
            <option value="">все</option>
            {users.data?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.username}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ErrorNote error={entries.error ?? users.error} />
      {entries.data && (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Время</th>
                  <th>Пользователь</th>
                  <th>Действие</th>
                  <th>Объект</th>
                  <th>Подробности</th>
                  <th>IP</th>
                </tr>
              </thead>
              <tbody>
                {entries.data.map((e) => (
                  <tr key={e.id}>
                    <td className="nowrap">{formatDateTime(e.timestamp)}</td>
                    <td>{e.username ?? "—"}</td>
                    <td>{AUDIT_LABELS[e.action] ?? e.action}</td>
                    <td>{describeTarget(e)}</td>
                    <td>{describeDetails(e.details)}</td>
                    <td>{e.ip_address ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {entries.data.length === 0 && <p className="muted">Записей нет.</p>}
          <div className="pager">
            <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>
              ← Новее
            </button>
            <span>Страница {page + 1}</span>
            <button type="button" disabled={entries.data.length < PAGE_SIZE} onClick={() => setPage(page + 1)}>
              Старее →
            </button>
          </div>
        </>
      )}
    </section>
  );
}
