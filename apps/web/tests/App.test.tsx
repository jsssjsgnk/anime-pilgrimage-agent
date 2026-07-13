import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "../src/App";

describe("App", () => {
  it("explains safety boundaries and provides a labelled mixed-initiative input", () => {
    render(<App />);

    expect(screen.getByText("只读规划 · 不预订 · 不付款")).toBeInTheDocument();
    expect(screen.getByLabelText("旅行想法")).toHaveValue(
      "我从京都出发，九月去东京三天，想巡礼《孤独摇滚！》，预算中等，希望少走路。",
    );
  });

  it("acknowledges input without silently confirming key choices", () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /整理旅行条件/ }));
    expect(screen.getByText(/不会静默确认关键选择/)).toBeInTheDocument();
  });
});
