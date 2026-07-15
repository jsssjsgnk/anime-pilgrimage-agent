import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TripWorkspace } from "../src/workspace/TripWorkspace";
import type { PlanPatch, WorkspaceView } from "../src/workspace/types";

const tripId = "00000000-0000-4000-8000-000000000201";
const intentId = "00000000-0000-4000-8000-000000000202";
const subject = { subject_id: "328609", name: "Bocchi the Rock!", name_cn: "孤独摇滚！", aliases: [] };

function workspace(status: string, version: number): WorkspaceView {
  return {
    trip_id: tripId,
    thread_id: "local-workspace-thread",
    state_version: version,
    status,
    requirements: {
      origin: "京都",
      destination: "东京",
      base_preference: "新宿",
      start_date: "2030-09-01",
      end_date: "2030-09-03",
      walking_preference: "medium",
      subject_intents: [{ intent_id: intentId, query: "孤独摇滚！", priority: 5, is_primary: true, status: status === "awaiting_subject_confirmation" ? "proposed" : "confirmed", confirmed_subject_id: status === "awaiting_subject_confirmation" ? null : subject.subject_id, confirmed_subject_ids: status === "awaiting_subject_confirmation" ? [] : [subject.subject_id] }],
    },
    subject_groups: [{
      intent: { intent_id: intentId, query: "孤独摇滚！", priority: 5, is_primary: true, status: "proposed", confirmed_subject_id: null, confirmed_subject_ids: [] },
      candidates: [subject], status: "ok", warning: null,
    }],
    confirmed_subjects: status === "awaiting_subject_confirmation" ? [] : [{
      intent_id: intentId,
      subject,
      evidence_status: "ok",
      point_collection: {
        provider: "anitabi_static",
        is_complete: false,
        expected_count: 4,
        loaded_count: 3,
        data_version: "fixture-v1",
        retrieved_at: "2030-01-01T00:00:00Z",
        expires_at: "2030-01-02T00:00:00Z",
      },
    }],
    places: [],
    areas: [],
    base_candidates: status === "awaiting_subject_confirmation" ? [] : [{ base_id: "shimokitazawa", name: "下北泽", coordinate: { latitude: 35.66, longitude: 139.67 } }],
    selected_base_id: status === "planned" ? "shimokitazawa" : null,
    candidate_graph: status === "awaiting_subject_confirmation" ? null : { evidence_status: "ok" },
    itineraries: status === "planned" ? [{
      itinerary_id: "00000000-0000-4000-8000-000000000203", version: 1,
      strategy: "primary_subject_first", days: [], omissions: [], validation_issues: [],
    }] : [],
    counts: { raw_scene_records: status === "awaiting_subject_confirmation" ? 0 : 3, quarantined_records: 0, canonical_places: status === "awaiting_subject_confirmation" ? 0 : 2, areas: status === "awaiting_subject_confirmation" ? 0 : 1, recommended_places: 2, scheduled_places: 0 },
    warnings: [], handoffs: [], contexts: [], patches: [], pending_patch_id: null,
    impacts: [], diffs: [], knowledge_rules: [],
  };
}

function json(value: unknown) {
  return Promise.resolve(new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } }));
}

describe("TripWorkspace", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.sessionStorage.clear();
  });

  it("starts a multi-subject workspace from natural input and requires explicit confirmation", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/messages") && !init?.method) return json([]);
      return json(workspace("awaiting_subject_confirmation", 1));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<TripWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "开始规划" }));
    expect(await screen.findByRole("heading", { name: "作品匹配结果" })).toBeVisible();
    expect(screen.getByText("场景资料")).toBeVisible();
    expect(screen.getByText("巡礼地点")).toBeVisible();
    const rawBody = fetchMock.mock.calls[0]?.[1]?.body;
    if (typeof rawBody !== "string") throw new Error("Expected a JSON request body");
    const payload = JSON.parse(rawBody) as {
      request_summary: string;
      requirements: Record<string, unknown> & { subject_intents: unknown[] };
    };
    expect(payload.requirements.subject_intents).toHaveLength(2);
    expect(payload.request_summary).toContain("每天不要走太多路");
    expect(payload.requirements).not.toHaveProperty("origin");
    expect(payload.requirements).not.toHaveProperty("destination");
    expect(payload.requirements).not.toHaveProperty("walking_preference");
  });

  it("shows safe planning warnings without exposing internal implementation names", async () => {
    const warned = {
      ...workspace("awaiting_subject_confirmation", 1),
      warnings: ["SearchAPI provider transit timeout", "LLM Reviewer failed safely"],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      return url.endsWith("/messages") ? json([]) : json(warned);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<TripWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "开始规划" }));
    expect(await screen.findByRole("heading", { name: "需要留意" })).toBeVisible();
    expect(screen.getByText(/部分交通资料暂时无法核实/u)).toBeVisible();
    expect(screen.queryByText(/SearchAPI|LLM Reviewer|provider/u)).not.toBeInTheDocument();
  });

  it("allows several seasons for one title and submits them together", async () => {
    const seasons = [
      { subject_id: "1424", name: "K-On!", name_cn: "轻音少女", aliases: [] },
      { subject_id: "3774", name: "K-On!!", name_cn: "轻音少女 第二季", aliases: [] },
      { subject_id: "12426", name: "K-On! Movie", name_cn: "轻音少女 剧场版", aliases: [] },
    ];
    const started = {
      ...workspace("awaiting_subject_confirmation", 1),
      subject_groups: [{
        intent: { intent_id: intentId, query: "轻音少女", priority: 5, is_primary: true, status: "proposed", confirmed_subject_id: null, confirmed_subject_ids: [] },
        candidates: seasons, status: "ok", warning: null,
      }],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/api/workspaces")) return json(started);
      if (url.endsWith("/messages") && !init?.method) return json([]);
      if (url.includes("/subjects/confirm")) return json(workspace("ready_for_planning", 2));
      throw new Error(`unexpected ${url} ${init?.method ?? "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<TripWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "开始规划" }));
    fireEvent.click(await screen.findByRole("button", { name: "选择全部季度与版本" }));
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "确认并整理地点" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const confirmCall = fetchMock.mock.calls.find(([input]) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      return url.includes("/subjects/confirm");
    });
    const body = confirmCall?.[1]?.body;
    if (typeof body !== "string") throw new Error("Expected a confirmation JSON body");
    const payload = JSON.parse(body) as { confirmations: { selected_subject_ids: string[] }[] };
    expect(payload.confirmations[0]?.selected_subject_ids).toEqual(["1424", "3774", "12426"]);
  });

  it("returns to editable title input when no candidate is found", async () => {
    const started = {
      ...workspace("awaiting_subject_confirmation", 1),
      subject_groups: [{
        intent: { intent_id: intentId, query: "无法识别的作品", priority: 5, is_primary: true, status: "proposed", confirmed_subject_id: null, confirmed_subject_ids: [] },
        candidates: [], status: "not_found", warning: "没有找到候选",
      }],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      return url.endsWith("/messages") && !init?.method ? json([]) : json(started);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<TripWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "开始规划" }));
    fireEvent.click(await screen.findByRole("button", { name: "返回修改作品名称" }));
    expect(screen.getByLabelText("你的巡礼想法")).toBeVisible();
    expect(screen.getByRole("button", { name: "开始规划" })).toBeVisible();
  });

  it("discloses static point completeness and data version", async () => {
    const ready = workspace("ready_for_planning", 2);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      return url.endsWith("/messages") && !init?.method ? json([]) : json(ready);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<TripWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "开始规划" }));
    fireEvent.click(await screen.findByRole("button", { name: /资料说明/ }));
    expect(screen.getByText(/3 \/ 4 个点位/)).toBeVisible();
    expect(screen.getByText(/部分 · 静态地图资料 · 版本 fixture-v1/)).toBeVisible();
  });

  it("confirms subjects, plans, previews a PlanPatch, and applies it", async () => {
    const started = workspace("awaiting_subject_confirmation", 1);
    const confirmed = workspace("ready_for_planning", 2);
    const planned = workspace("planned", 3);
    const patch = {
      patch_id: "00000000-0000-4000-8000-000000000204", trip_id: tripId,
      expected_base_version: 3, rationale: "降低每日步行", requires_confirmation: false,
      status: "proposed", idempotency_key: "web:test-patch", created_at: "2030-01-01T00:00:00Z",
      operations: [{ op: "update_requirement", field: "walking_preference", value: "low" }],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/api/workspaces")) return json(started);
      if (url.endsWith("/messages") && !init?.method) return json([]);
      if (url.includes("/subjects/confirm")) return json(confirmed);
      if (url.endsWith("/plan")) return json(planned);
      if (url.endsWith("/messages") && init?.method === "POST") return json({ trip_id: tripId, messages: [], assistant_message: { message_id: "00000000-0000-4000-8000-000000000205", role: "assistant", content: "修改预览已生成", intent: "modify_plan", created_at: "2030-01-01T00:00:00Z" }, workspace: planned, preview: { patch, impact: { patch_id: patch.patch_id, invalidated_nodes: ["itinerary_planner"], invalidated_refs: [], stable_refs: ["subject:*"], validation_required: true, reviewer_required: true, confirmation_required: false } } });
      if (url.includes("/apply")) return json({ ...planned, state_version: 4, diffs: [{ from_version: 3, to_version: 4, changed_requirements: ["walking_preference"], changed_day_numbers: [] }] });
      throw new Error(`unexpected ${url} ${init?.method ?? "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<TripWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "开始规划" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认并整理地点" }));
    fireEvent.click(await screen.findByRole("button", { name: "生成层级行程" }));
    const editor = await screen.findByLabelText("继续修改行程");
    fireEvent.change(editor, { target: { value: "把步行偏好设为 low" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByRole("dialog", { name: "应用这次修改？" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "确认并重新规划" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });

  it("adds and removes works from an existing workspace with explicit previews", async () => {
    window.sessionStorage.setItem("pilgrimage-workspace-v2", tripId);
    const secondIntentId = "00000000-0000-4000-8000-000000000211";
    const existing = workspace("planned", 7);
    existing.requirements.subject_intents.push({
      intent_id: secondIntentId, query: "莉可丽丝", priority: 3, is_primary: false,
      status: "confirmed", confirmed_subject_id: "lycoris", confirmed_subject_ids: ["lycoris"],
    });
    const previewBodies: unknown[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      if (url.includes("/messages") && !init?.method) return json([]);
      if (!init?.method) return json(existing);
      if (url.includes("/patches/preview")) {
        if (typeof init.body !== "string") throw new Error("Expected a patch body");
        const request = JSON.parse(init.body) as { patch: PlanPatch };
        previewBodies.push(request.patch.operations[0]);
        return json({
          workspace: existing,
          preview: {
            patch: request.patch,
            impact: { patch_id: request.patch.patch_id, confirmation_required: true },
          },
        });
      }
      throw new Error(`unexpected ${url} ${init?.method ?? "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<TripWorkspace />);

    const addInput = await screen.findByLabelText("添加作品");
    fireEvent.change(addInput, { target: { value: "天气之子" } });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    expect(await screen.findByRole("dialog", { name: "应用这次修改？" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.click(screen.getByRole("button", { name: "移除作品 莉可丽丝" }));
    expect(await screen.findByRole("dialog", { name: "应用这次修改？" })).toBeVisible();

    expect(previewBodies).toHaveLength(2);
    expect(previewBodies[0]).toMatchObject({
      op: "subject_intent", action: "add", intent: { query: "天气之子" },
    });
    expect(previewBodies[1]).toEqual({
      op: "subject_intent", action: "remove", intent_id: secondIntentId,
    });
  });

  it("restores the trip-scoped workspace after reload", async () => {
    window.sessionStorage.setItem("pilgrimage-workspace-v2", tripId);
    const pendingPatch = {
      patch_id: "00000000-0000-4000-8000-000000000209", trip_id: tripId,
      expected_base_version: 7, rationale: "延后开始日期", requires_confirmation: true,
      status: "proposed", idempotency_key: "web:pending-reload", created_at: "2030-01-01T00:00:00Z",
      operations: [{ op: "update_requirement", field: "start_date", value: "2030-09-02" }],
    };
    const restoredWorkspace = {
      ...workspace("planned", 7),
      patches: [pendingPatch],
      pending_patch_id: pendingPatch.patch_id,
      impacts: [{ patch_id: pendingPatch.patch_id, invalidated_nodes: ["itinerary_planner"], stable_refs: ["subject:*"], confirmation_required: true }],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      return url.includes("/messages") ? json([]) : json(restoredWorkspace);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<TripWorkspace />);

    expect(await screen.findByRole("dialog", { name: "应用这次修改？" })).toBeVisible();
    expect(screen.queryByText(tripId.slice(0, 8))).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining(`/api/workspaces/${tripId}`), expect.anything());
  });

  it("edits extracted trip conditions through a typed preview", async () => {
    window.sessionStorage.setItem("pilgrimage-workspace-v2", tripId);
    const current = workspace("planned", 7);
    let previewOperation: unknown;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      if (url.includes("/messages") && !init?.method) return json([]);
      if (url.includes("/patches/preview")) {
        if (typeof init?.body !== "string") throw new Error("Expected a patch body");
        const request = JSON.parse(init.body) as { patch: PlanPatch };
        previewOperation = request.patch.operations;
        return json({
          workspace: current,
          preview: {
            patch: request.patch,
            impact: { patch_id: request.patch.patch_id, confirmation_required: true },
          },
        });
      }
      return json(current);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<TripWorkspace />);

    fireEvent.click(await screen.findByRole("button", { name: "编辑行程条件" }));
    fireEvent.change(screen.getByLabelText("出发地"), { target: { value: "大阪" } });
    fireEvent.change(screen.getByLabelText("步行偏好"), { target: { value: "low" } });
    fireEvent.click(screen.getByRole("button", { name: "预览条件修改" }));

    expect(await screen.findByRole("dialog", { name: "应用这次修改？" })).toBeVisible();
    expect(previewOperation).toEqual([
      { op: "update_requirement", field: "origin", value: "大阪" },
      { op: "update_requirement", field: "walking_preference", value: "low" },
    ]);
  });

  it("keeps close separate and requires a second click for permanent deletion", async () => {
    window.sessionStorage.setItem("pilgrimage-workspace-v2", tripId);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      if (init?.method === "DELETE") return json({ trip_id: tripId, deleted: true });
      return url.includes("/messages") ? json([]) : json(workspace("planned", 7));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<TripWorkspace />);

    const deleteButton = await screen.findByRole("button", { name: "永久删除工作区" });
    fireEvent.click(deleteButton);
    expect(screen.getByRole("alert")).toHaveTextContent("且无法撤销");
    expect(fetchMock.mock.calls.filter((call) => call[1]?.method === "DELETE")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "再次点击确认永久删除" }));
    await waitFor(() => expect(fetchMock.mock.calls.filter((call) => call[1]?.method === "DELETE")).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "开始规划" })).toBeVisible();
  });
});
