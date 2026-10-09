import { type ReactElement, useCallback, useEffect, useMemo, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";

import { UNAUTHORIZED_EVENT, api } from "./api";
import { type Auth, AuthContext, useAuth } from "./auth";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { AuditPage } from "./pages/AuditPage";
import { CamerasPage } from "./pages/CamerasPage";
import { DashboardPage } from "./pages/DashboardPage";
import { EventsPage } from "./pages/EventsPage";
import { LiveViewPage } from "./pages/LiveViewPage";
import { LoginPage } from "./pages/LoginPage";
import { PersonDetailPage } from "./pages/PersonDetailPage";
import { PersonsPage } from "./pages/PersonsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { UsersPage } from "./pages/UsersPage";
import type { User } from "./types";
import { useApi } from "./useApi";

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

const NAV: NavItem[] = [
  { to: "/", label: "Обзор", end: true },
  { to: "/cameras", label: "Камеры" },
  { to: "/live", label: "Live View" },
  { to: "/persons", label: "Люди" },
  { to: "/events", label: "События" },
  { to: "/analytics", label: "Аналитика" },
  { to: "/settings", label: "Настройки" },
];
const ADMIN_NAV: NavItem[] = [
  { to: "/users", label: "Пользователи" },
  { to: "/audit", label: "Журнал аудита" },
];

/** Checks the session first: the login page or the dashboard. */
export function App() {
  // undefined = still asking the API, null = not logged in.
  const [user, setUser] = useState<User | null>();

  useEffect(() => {
    api.me().then(setUser, () => setUser(null));
    const loggedOut = () => setUser(null);
    window.addEventListener(UNAUTHORIZED_EVENT, loggedOut);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, loggedOut);
  }, []);

  const logout = useCallback(() => {
    api.logout().finally(() => setUser(null));
  }, []);
  const auth = useMemo<Auth | null>(
    () => (user ? { user, isAdmin: user.role === "admin", logout } : null),
    [user, logout],
  );

  if (user === undefined) return <p className="muted center">Загрузка…</p>;
  if (!auth) return <LoginPage onLogin={setUser} />;
  return (
    <AuthContext.Provider value={auth}>
      <Shell />
    </AuthContext.Provider>
  );
}

function Shell() {
  const { user, isAdmin, logout } = useAuth();
  const settings = useApi(() => api.settings(), []);
  const mode = settings.data?.vision_mode;
  const adminOnly = (page: ReactElement) => (isAdmin ? page : <p>Раздел доступен только администратору.</p>);
  return (
    <div className="layout">
      <nav className="sidebar" aria-label="Разделы">
        <div className="brand">
          KörGöz
          {mode && <span className="mode">{mode === "recognition" ? "распознавание" : "анонимный режим"}</span>}
        </div>
        {[...NAV, ...(isAdmin ? ADMIN_NAV : [])].map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end}>
            {item.label}
          </NavLink>
        ))}
        <div className="account">
          <span>
            {user.username} <span className="muted">({isAdmin ? "администратор" : "просмотр"})</span>
          </span>
          <button type="button" className="link-button" onClick={logout}>
            Выйти
          </button>
        </div>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/cameras" element={<CamerasPage />} />
          <Route path="/live" element={<LiveViewPage />} />
          <Route path="/persons" element={<PersonsPage settings={settings.data} />} />
          <Route path="/persons/:id" element={<PersonDetailPage />} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="/analytics" element={<AnalyticsPage settings={settings.data} />} />
          <Route path="/settings" element={<SettingsPage settings={settings.data} />} />
          <Route path="/users" element={adminOnly(<UsersPage />)} />
          <Route path="/audit" element={adminOnly(<AuditPage />)} />
          <Route path="*" element={<p>Страница не найдена.</p>} />
        </Routes>
      </main>
    </div>
  );
}
