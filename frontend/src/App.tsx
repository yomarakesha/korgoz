import { NavLink, Route, Routes } from "react-router-dom";

import { api } from "./api";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { CamerasPage } from "./pages/CamerasPage";
import { DashboardPage } from "./pages/DashboardPage";
import { EventsPage } from "./pages/EventsPage";
import { LiveViewPage } from "./pages/LiveViewPage";
import { PersonDetailPage } from "./pages/PersonDetailPage";
import { PersonsPage } from "./pages/PersonsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { useApi } from "./useApi";

const NAV = [
  { to: "/", label: "Обзор", end: true },
  { to: "/cameras", label: "Камеры" },
  { to: "/live", label: "Live View" },
  { to: "/persons", label: "Люди" },
  { to: "/events", label: "События" },
  { to: "/analytics", label: "Аналитика" },
  { to: "/settings", label: "Настройки" },
];

export function App() {
  const settings = useApi(() => api.settings(), []);
  const mode = settings.data?.vision_mode;
  return (
    <div className="layout">
      <nav className="sidebar" aria-label="Разделы">
        <div className="brand">
          KörGöz
          {mode && <span className="mode">{mode === "recognition" ? "распознавание" : "анонимный режим"}</span>}
        </div>
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end}>
            {item.label}
          </NavLink>
        ))}
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
          <Route path="*" element={<p>Страница не найдена.</p>} />
        </Routes>
      </main>
    </div>
  );
}
