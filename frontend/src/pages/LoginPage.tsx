import { type FormEvent, useState } from "react";

import { ApiError, api } from "../api";
import type { User } from "../types";

function loginError(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return "Неверный логин или пароль.";
  if (error instanceof ApiError && error.status === 429)
    return "Слишком много неудачных попыток. Подождите несколько минут.";
  return `Ошибка: ${error instanceof Error ? error.message : String(error)}`;
}

export function LoginPage({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(undefined);
    setBusy(true);
    try {
      const { user } = await api.login(username, password);
      onLogin(user);
    } catch (reason) {
      setError(loginError(reason));
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form className="login-card" onSubmit={(e) => void submit(e)}>
        <h1>KörGöz</h1>
        {error && (
          <p className="notice notice-error" role="alert">
            {error}
          </p>
        )}
        <label>
          Логин
          <input
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoFocus
          />
        </label>
        <label>
          Пароль
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Вход…" : "Войти"}
        </button>
      </form>
    </main>
  );
}
