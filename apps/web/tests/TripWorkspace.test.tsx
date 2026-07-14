import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TripWorkspace } from "../src/workspace/TripWorkspace";
import type { WorkspaceView } from "../src/workspace/types";

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
      start_date: "2030-09-01",
      end_date: "2030-09-03",
      walking_preference: "medium",
      subject_intents: [{ intent_id: intentId, query: "孤独摇滚！", priority: 5, is_primary: true, status: status === "awaiting_subject_confirmation" ? "proposed" : "confirmed" }],
    },
    subject_groups: [{
      intent: { intent_id: intentId, query: "孤独摇滚！", priority: 5, is_primary: true, status: "proposed" },
      candidates: [subject], status: "ok", warning: null,
    }],
    confirmed_subjects: status === "awaiting_subject_confirmation" ? [] : [{ intent_id: intentId, subject, evidence_status: "ok" }],
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
    const payload = JSON.parse(rawBody) as { requirements: { subject_intents: unknown[] } };
    expect(payload.requirements.subject_intents).toHaveLength(2);
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
});
