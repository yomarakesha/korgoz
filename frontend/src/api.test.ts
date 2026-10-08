import { ApiError, api, request } from "./api";
import { mockApi } from "./testing";

describe("request", () => {
  it("returns JSON", async () => {
    mockApi({ "/health": { status: "ok" } });
    expect(await request("/health")).toEqual({ status: "ok" });
  });

  it("turns FastAPI errors into ApiError with the detail text", async () => {
    mockApi({ "/persons": () => new Response(JSON.stringify({ detail: "No face found in the photo" }), { status: 422 }) });
    const error = await api.registerPerson(new FormData()).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, message: "No face found in the photo" });
  });

  it("joins validation error messages", async () => {
    mockApi({
      "/events": () =>
        new Response(JSON.stringify({ detail: [{ msg: "bad type" }, { msg: "bad date" }] }), { status: 422 }),
    });
    await expect(api.events({})).rejects.toThrow("bad type; bad date");
  });

  it("handles 204 and non-JSON errors", async () => {
    mockApi({
      "/persons": (_url: URL, init?: RequestInit) =>
        init?.method === "DELETE" ? new Response(null, { status: 204 }) : new Response("oops", { status: 502 }),
    });
    await expect(api.deletePerson(1)).resolves.toBeUndefined();
    await expect(api.persons()).rejects.toThrow("HTTP 502");
  });

  it("sends event filters as query parameters", async () => {
    const calls = mockApi({ "/events": [] });
    await api.events({ camera_id: 2, event_type: ["PERSON_ENTERED", "PERSON_LEFT"], limit: 50 });
    expect(calls[0]?.url.search).toBe("?camera_id=2&event_type=PERSON_ENTERED&event_type=PERSON_LEFT&limit=50");
  });
});
