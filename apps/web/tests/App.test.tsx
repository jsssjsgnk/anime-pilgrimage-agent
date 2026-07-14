import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import maplibregl from "maplibre-gl";

import { App } from "../src/App";
import { createRouteMapOptions, ROUTE_MAP_STYLE_URL } from "../src/route-map-config";

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App", () => {
  it("explains safety boundaries and provides a labelled mixed-initiative input", () => {
    renderApp();

    expect(screen.getByText("只读规划 · 不预订 · 不付款")).toBeInTheDocument();
    expect(screen.getByLabelText("旅行想法")).toHaveValue(
      "我从京都出发，九月去东京三天，想巡礼《孤独摇滚！》，预算中等，希望少走路。",
    );
  });

  it("acknowledges input without silently confirming key choices", () => {
    renderApp();

    fireEvent.click(screen.getByRole("button", { name: /整理旅行条件/ }));
    expect(screen.getByText(/不会静默确认关键选择/)).toBeInTheDocument();
  });

  it("configures an interactive attributed OpenFreeMap basemap", () => {
    const bounds = new maplibregl.LngLatBounds([139.66, 35.66], [139.68, 35.67]);
    const options = createRouteMapOptions(document.createElement("div"), bounds);

    expect(options.style).toBe(ROUTE_MAP_STYLE_URL);
    expect(options.interactive).toBe(true);
    expect(options.cooperativeGestures).toBe(true);
    if (!options.attributionControl) throw new Error("Map attribution must remain enabled.");
    expect(options.attributionControl.compact).toBe(false);
  });
});
