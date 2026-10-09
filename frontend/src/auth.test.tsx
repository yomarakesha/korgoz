import { fireEvent, screen, waitFor } from "@testing-library/react";

import { App } from "./App";
import { ADMIN, SETTINGS, mockApi, renderAt } from "./testing";

const unauthorized = () => new Response(JSON.stringify({ detail: "Not authenticated" }), { status: 401 });

function routes(loggedIn: { value: boolean }) {
  return {
    "/auth/me": () => (loggedIn.value ? ADMIN : unauthorized()),
    "/auth/logout": () => {
      loggedIn.value = false;
      return new Response(null, { status: 204 });
    },
    "/auth/login": (_url: URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { password: string };
      if (body.password === "locked") return new Response(JSON.stringify({ detail: "Too many" }), { status: 429 });
      if (body.password !== "admin-password-1")
        return new Response(JSON.stringify({ detail: "Invalid username or password" }), { status: 401 });
      loggedIn.value = true;
      return { user: ADMIN, access_token: "t", token_type: "bearer", expires_at: "" };
    },
    "/settings": () => (loggedIn.value ? SETTINGS : unauthorized()),
    "/health": { status: "ok", database: "ok", qdrant: "ok", ai: "ok", cameras: 0 },
    "/cameras": () => (loggedIn.value ? [] : unauthorized()),
    "/locations": [],
    "/persons": [],
    "/events": [],
    "/events/count": { count: 0 },
    "/analytics/occupancy": { at: "", total: 0, cameras: [] },
  };
}

async function submitLogin(password: string) {
  fireEvent.change(await screen.findByLabelText("Логин"), { target: { value: "admin" } });
  fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Войти" }));
}

describe("authentication", () => {
  it("shows the login page, explains errors, then opens the dashboard", async () => {
    mockApi(routes({ value: false }));
    renderAt(<App />, "/");
    await submitLogin("wrong");
    expect(await screen.findByRole("alert")).toHaveTextContent("Неверный логин или пароль.");
    await submitLogin("locked");
    expect(await screen.findByRole("alert")).toHaveTextContent("Слишком много неудачных попыток");
    await submitLogin("admin-password-1");
    expect(await screen.findByText("Сейчас в кадре")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Журнал аудита" })).toBeInTheDocument();
  });

  it("logout and an expired session return to the login page", async () => {
    const loggedIn = { value: true };
    mockApi(routes(loggedIn));
    renderAt(<App />, "/");
    fireEvent.click(await screen.findByRole("button", { name: "Выйти" }));
    expect(await screen.findByRole("button", { name: "Войти" })).toBeInTheDocument();

    loggedIn.value = true;
    await submitLogin("admin-password-1");
    await screen.findByRole("button", { name: "Выйти" });
    loggedIn.value = false; // e.g. the admin blocked us: the next API call gets 401
    fireEvent.click(screen.getByRole("link", { name: "Камеры" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Войти" })).toBeInTheDocument());
  });
});
