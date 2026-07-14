import { render, screen } from "@testing-library/react";
import maplibregl from "maplibre-gl";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "../src/App";
import { createRouteMapOptions, ROUTE_MAP_STYLE_URL } from "../src/route-map-config";
import { extractSubjectQueries } from "../src/workspace/intake";

describe("App", () => {
  afterEach(() => window.sessionStorage.clear());

  it("shows one conversational workflow without implementation diagnostics", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "多作品巡礼工作区" })).toBeVisible();
    expect(screen.getByLabelText("你的巡礼想法")).toHaveValue(
      "我想用三天巡礼《孤独摇滚！》和《莉可丽丝》，每天不要走太多路。",
    );
    expect(screen.queryByText(/Route A|Route B|PlanPatch|Anitabi|目录身份/u)).not.toBeInTheDocument();
    expect(screen.queryByText("经典路线兼容流程")).not.toBeInTheDocument();
  });

  it("extracts up to three works from natural Chinese requests", () => {
    expect(extractSubjectQueries("我想三天巡礼《孤独摇滚！》和《莉可丽丝》，住在新宿附近"))
      .toEqual(["孤独摇滚！", "莉可丽丝"]);
    expect(extractSubjectQueries("这次想巡礼孤独摇滚！和莉可丽丝，每天少走一点"))
      .toEqual(["孤独摇滚！", "莉可丽丝"]);
  });

  it("keeps an interactive attributed basemap", () => {
    const bounds = new maplibregl.LngLatBounds([139.66, 35.66], [139.68, 35.67]);
    const options = createRouteMapOptions(document.createElement("div"), bounds);

    expect(options.style).toBe(ROUTE_MAP_STYLE_URL);
    expect(options.interactive).toBe(true);
    expect(options.cooperativeGestures).toBe(true);
    expect(options.attributionControl).toBeTruthy();
  });
});
