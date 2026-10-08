import { fireEvent, render, screen } from "@testing-library/react";

import { FlowChart } from "./FlowChart";

const BUCKETS = [
  { hour: "2026-10-08T16:00:00+05:00", entered: 0, left: 0 },
  { hour: "2026-10-08T17:00:00+05:00", entered: 4, left: 3 },
];

describe("FlowChart", () => {
  it("draws a bar per non-zero value, with legend and time zone", () => {
    const { container } = render(<FlowChart buckets={BUCKETS} timezone="Asia/Tashkent" />);
    expect(container.querySelectorAll("rect.series-1")).toHaveLength(1);
    expect(container.querySelectorAll("rect.series-2")).toHaveLength(1);
    expect(screen.getByText("Вошли")).toBeInTheDocument();
    expect(screen.getByText(/Asia\/Tashkent/)).toBeInTheDocument();
  });

  it("shows a tooltip on hover", () => {
    render(<FlowChart buckets={BUCKETS} timezone="UTC" />);
    fireEvent.mouseEnter(screen.getAllByTestId("hit")[1]!);
    expect(screen.getByRole("status")).toHaveTextContent("08.10 17:00");
    expect(screen.getByRole("status")).toHaveTextContent("Вошли: 4");
  });

  it("has a table view", () => {
    render(<FlowChart buckets={BUCKETS} timezone="UTC" />);
    fireEvent.click(screen.getByRole("button", { name: "Таблица" }));
    expect(screen.getByRole("table")).toHaveTextContent("08.10 17:00");
  });
});
