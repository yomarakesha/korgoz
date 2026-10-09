import { type FormEvent, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorNote, Notice } from "../components/Notice";
import { formatDate } from "../format";
import type { PublicSettings } from "../types";
import { useApi } from "../useApi";

export function PersonsPage({ settings }: { settings: PublicSettings | undefined }) {
  const persons = useApi(() => api.persons(), []);
  const { isAdmin } = useAuth();
  const [formError, setFormError] = useState<Error>();
  const [saving, setSaving] = useState(false);
  const [registered, setRegistered] = useState<string>();
  const form = useRef<HTMLFormElement>(null);
  const recognition = settings?.vision_mode === "recognition";

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(undefined);
    setRegistered(undefined);
    setSaving(true);
    try {
      const data = new FormData(event.currentTarget);
      if (!data.get("external_id")) data.delete("external_id");
      if (!data.get("description")) data.delete("description");
      const person = await api.registerPerson(data);
      setRegistered(person.name);
      form.current?.reset();
      persons.reload();
    } catch (error) {
      setFormError(error as Error);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <h1>Люди</h1>
      <ErrorNote error={persons.error} />
      {persons.data && persons.data.length === 0 && <p className="muted">Никто не зарегистрирован.</p>}
      {persons.data && persons.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Имя</th>
                <th>External ID</th>
                <th>Зарегистрирован</th>
                <th className="num">Векторов лица</th>
              </tr>
            </thead>
            <tbody>
              {persons.data.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link to={`/persons/${p.id}`}>{p.name}</Link>
                  </td>
                  <td>{p.external_id ?? "—"}</td>
                  <td>{formatDate(p.created_at)}</td>
                  <td className="num">{p.embeddings}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {isAdmin && (
        <>
          <h2>Регистрация</h2>
          {settings && !recognition && (
            <Notice>
              Регистрация лиц доступна только в режиме распознавания: <code>VISION_MODE=recognition</code>{" "}
              (сейчас — анонимный режим).
            </Notice>
          )}
          <p className="muted">
            Одно фото, на нём ровно одно лицо анфас, не меньше {settings?.face_registration_min_size ?? 80} px.
            Фото не сохраняется: из него считается вектор лица.
          </p>
          <ErrorNote error={formError} />
          {registered && <p className="notice notice-ok">«{registered}» зарегистрирован.</p>}
          <form ref={form} className="form-grid" onSubmit={(e) => void register(e)}>
            <label>
              Имя
              <input name="name" required maxLength={255} disabled={!recognition} />
            </label>
            <label>
              External ID (табельный номер и т. п.)
              <input name="external_id" maxLength={255} disabled={!recognition} />
            </label>
            <label>
              Описание
              <input name="description" disabled={!recognition} />
            </label>
            <label>
              Фото
              <input name="photo" type="file" accept="image/jpeg,image/png" required disabled={!recognition} />
            </label>
            <button type="submit" disabled={!recognition || saving}>
              {saving ? "Обработка…" : "Зарегистрировать"}
            </button>
          </form>
        </>
      )}
    </section>
  );
}
