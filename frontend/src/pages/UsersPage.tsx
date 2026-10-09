import { type FormEvent, useState } from "react";

import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorNote, Notice } from "../components/Notice";
import { formatDateTime } from "../format";
import type { UserRole } from "../types";
import { useApi } from "../useApi";

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "администратор",
  user: "просмотр",
};

export function UsersPage() {
  const { user: me } = useAuth();
  const users = useApi(() => api.users(), []);
  const [actionError, setActionError] = useState<Error>();
  const [done, setDone] = useState<string>();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("user");

  async function run(action: () => Promise<unknown>, message?: string) {
    setActionError(undefined);
    setDone(undefined);
    try {
      await action();
      if (message) setDone(message);
      users.reload();
    } catch (error) {
      setActionError(error as Error);
    }
  }

  function addUser(event: FormEvent) {
    event.preventDefault();
    void run(async () => {
      await api.createUser({ username, password, role });
      setUsername("");
      setPassword("");
    }, `Пользователь «${username.trim().toLowerCase()}» создан.`);
  }

  function resetPassword(id: number, name: string) {
    const value = window.prompt(`Новый пароль для «${name}» (пользователь выйдет на всех устройствах):`);
    if (value) void run(() => api.updateUser(id, { password: value }), `Пароль «${name}» изменён.`);
  }

  return (
    <section>
      <h1>Пользователи</h1>
      <Notice>
        Администратор может всё. Роль «просмотр» видит дашборд, live view, события и аналитику, но ничего не
        меняет. Свою роль и статус изменить нельзя — так в системе всегда остаётся администратор.
      </Notice>
      <ErrorNote error={users.error ?? actionError} />
      {done && <p className="notice notice-ok">{done}</p>}
      {users.data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Логин</th>
                <th>Роль</th>
                <th>Активен</th>
                <th>Последний вход</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.data.map((u) => {
                const self = u.id === me.id;
                return (
                  <tr key={u.id}>
                    <td>
                      {u.username} {self && <span className="muted">(вы)</span>}
                    </td>
                    <td>
                      <select
                        aria-label={`Роль ${u.username}`}
                        value={u.role}
                        disabled={self}
                        onChange={(e) => void run(() => api.updateUser(u.id, { role: e.target.value as UserRole }))}
                      >
                        {(Object.keys(ROLE_LABELS) as UserRole[]).map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABELS[r]}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${u.username} активен`}
                        checked={u.is_active}
                        disabled={self}
                        onChange={(e) => void run(() => api.updateUser(u.id, { is_active: e.target.checked }))}
                      />
                    </td>
                    <td>{u.last_login_at ? formatDateTime(u.last_login_at) : "—"}</td>
                    <td className="nowrap">
                      <button type="button" className="link-button" onClick={() => resetPassword(u.id, u.username)}>
                        сменить пароль
                      </button>{" "}
                      {!self && (
                        <button
                          type="button"
                          className="danger"
                          onClick={() => {
                            if (window.confirm(`Удалить пользователя «${u.username}»?`))
                              void run(() => api.deleteUser(u.id));
                          }}
                        >
                          Удалить
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <h2>Новый пользователь</h2>
      <form className="form-row" onSubmit={addUser}>
        <input
          placeholder="Логин"
          aria-label="Логин"
          autoComplete="off"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
        <input
          placeholder="Пароль"
          aria-label="Пароль"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <select aria-label="Роль" value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
          <option value="user">{ROLE_LABELS.user}</option>
          <option value="admin">{ROLE_LABELS.admin}</option>
        </select>
        <button type="submit">Создать</button>
      </form>
    </section>
  );
}
