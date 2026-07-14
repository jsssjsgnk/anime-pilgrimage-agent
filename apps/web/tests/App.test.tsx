import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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
  afterEach(() => {
    vi.unstubAllGlobals();
    window.sessionStorage.clear();
  });

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

  it("preserves confirmed data and offers recovery for a partial workflow", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      if (url.includes("/api/preferences")) {
        return Promise.resolve(new Response(
          "[]",
          { status: 200, headers: { "Content-Type": "application/json" } },
        ));
      }
      if (url.includes("/messages")) {
        return Promise.resolve(new Response(
          "[]",
          { status: 200, headers: { "Content-Type": "application/json" } },
        ));
      }
      return Promise.resolve(new Response(JSON.stringify({
        trip_id: "00000000-0000-4000-8000-000000000001",
        thread_id: "local-web-thread",
        status: "partial",
        phase: "fetch_points_partial",
        pending_confirmation: null,
        revision_count: 0,
        warnings: ["Point Provider unavailable; confirmed subject data was preserved."],
        requirements: null,
        requirement_source: "provided",
        requirement_assumptions: [],
        effective_walking_limit: null,
        applied_preference_keys: [],
        subject_candidates: [{
          subject_id: "328609",
          name: "Bocchi the Rock!",
          name_cn: "孤独摇滚！",
          aliases: [],
          score: 8.2,
          provenance: {
            provider: "bangumi-fixture",
            source_url: "https://example.test/subject/328609",
            fetched_at: "2030-01-01T00:00:00Z",
            status: "cached",
          },
        }],
        confirmed_subject: {
          subject_id: "328609",
          name: "Bocchi the Rock!",
          name_cn: "孤独摇滚！",
        },
        route_a: null,
        planning_options: null,
        route_b: null,
        weather: null,
        knowledge: null,
        validation_issues: [],
        reviewer_explanation: null,
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    }));
    renderApp();

    fireEvent.click(screen.getByRole("button", { name: /整理旅行条件/ }));

    expect(await screen.findByRole("status")).toHaveTextContent("fetch_points_partial");
    expect(screen.getByRole("heading", { name: "确认你要巡礼的作品" })).toBeVisible();
    expect(screen.getByRole("button", { name: "从当前输入重新安全读取" })).toBeVisible();
  });

  it("sends trip-scoped messages and restores the transcript after reload", async () => {
    const tripId = "00000000-0000-4000-8000-000000000013";
    const workflow = {
      trip_id: tripId,
      thread_id: "local-web-thread",
      status: "waiting_confirmation",
      phase: "requirements_confirmation",
      pending_confirmation: { kind: "requirements" },
      revision_count: 0,
      warnings: [],
      requirements: null,
      requirement_source: "deterministic_fallback",
      requirement_assumptions: [],
      effective_walking_limit: null,
      applied_preference_keys: [],
      subject_candidates: [],
      confirmed_subject: null,
      route_a: null,
      planning_options: null,
      route_b: null,
      weather: null,
      knowledge: null,
      validation_issues: [],
      reviewer_explanation: null,
    };
    let transcript = [{
      message_id: "00000000-0000-4000-8000-000000000101",
      role: "assistant",
      content: "我会在这个行程里保留后续上下文。",
      intent: "trip_started",
      action: { kind: "confirmation_required", target_day: null, revision_count: null },
      created_at: "2030-01-01T00:00:00Z",
    }];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      const method = init?.method ?? "GET";
      const json = (value: unknown) => Promise.resolve(new Response(
        JSON.stringify(value),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ));
      if (url.includes("/api/preferences")) return json([]);
      if (url.endsWith("/api/workflows") && method === "POST") return json(workflow);
      if (url.includes("/messages") && method === "GET") return json(transcript);
      if (url.includes("/messages") && method === "POST") {
        transcript = [...transcript, {
          message_id: "00000000-0000-4000-8000-000000000102",
          role: "user",
          content: "现在还缺什么？",
          intent: "general",
          action: { kind: "none", target_day: null, revision_count: null },
          created_at: "2030-01-01T00:01:00Z",
        }, {
          message_id: "00000000-0000-4000-8000-000000000103",
          role: "assistant",
          content: "当前还需要明确确认旅行条件。",
          intent: "status",
          action: { kind: "confirmation_required", target_day: null, revision_count: null },
          created_at: "2030-01-01T00:01:01Z",
        }];
        return json({
          trip_id: tripId,
          messages: transcript,
          assistant_message: transcript.at(-1),
          workflow,
        });
      }
      if (url.includes(`/api/workflows/${tripId}`) && method === "GET") {
        return json(workflow);
      }
      return Promise.resolve(new Response("Not found", { status: 404 }));
    }));

    const firstRender = renderApp();
    fireEvent.click(screen.getByRole("button", { name: /整理旅行条件/ }));
    expect(await screen.findByRole("heading", { name: "和规划 Agent 继续聊" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("继续询问或提出修改"), {
      target: { value: "现在还缺什么？" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("当前还需要明确确认旅行条件。")).toBeVisible();

    firstRender.unmount();
    renderApp();
    expect(await screen.findByText("当前还需要明确确认旅行条件。")).toBeVisible();
    expect(screen.getAllByText("现在还缺什么？")).toHaveLength(2);
  });
});
