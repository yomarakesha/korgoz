import { bucketHour, formatDuration, localInputToIso, startOfToday } from "./format";
import { queryString } from "./api";
import { niceTicks } from "./components/FlowChart";

describe("format", () => {
  it("formats durations", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(3.94)).toBe("3.9 с");
    expect(formatDuration(75)).toBe("1 мин 15 с");
    expect(formatDuration(3 * 3600 + 120)).toBe("3 ч 2 мин");
  });

  it("takes the bucket hour in the analytics zone, not the browser's", () => {
    expect(bucketHour("2026-10-08T17:00:00+05:00")).toBe(17);
  });

  it("converts datetime-local input to ISO", () => {
    expect(localInputToIso("")).toBeNull();
    expect(localInputToIso("garbage")).toBeNull();
    const iso = localInputToIso("2026-10-08T09:30");
    expect(iso && new Date(iso).getMinutes()).toBe(30);
  });

  it("start of today is local midnight", () => {
    const start = new Date(startOfToday(new Date(2026, 9, 8, 15, 45)));
    expect([start.getDate(), start.getHours(), start.getMinutes()]).toEqual([8, 0, 0]);
  });
});

describe("queryString", () => {
  it("skips empty values and repeats arrays", () => {
    expect(
      queryString({ a: 1, b: "", c: null, d: undefined, t: ["X", "Y"], ok: false }),
    ).toBe("?a=1&t=X&t=Y&ok=false");
    expect(queryString({})).toBe("");
  });
});

describe("niceTicks", () => {
  it("rounds the axis up to whole steps", () => {
    expect(niceTicks(0)).toEqual([0, 1]);
    expect(niceTicks(1)).toEqual([0, 1]);
    expect(niceTicks(7)).toEqual([0, 2, 4, 6, 8]);
    expect(niceTicks(130)).toEqual([0, 50, 100, 150]);
  });
});
