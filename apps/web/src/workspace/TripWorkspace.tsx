import {
  AlertTriangle,
  Bot,
  CalendarDays,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  ExternalLink,
  Footprints,
  GitCompareArrows,
  Layers3,
  ListChecks,
  MapPinned,
  MessageSquareText,
  Plus,
  RefreshCw,
  Route,
  Send,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import maplibregl from "maplibre-gl";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { ROUTE_MAP_STYLE_URL } from "../route-map-config";
import { extractSubjectQueries } from "./intake";
import { getWorkspaceSession } from "./session";
import type {
  ConversationMessage,
  PatchPreview,
  PlanPatch,
  SceneEvidence,
  VisitPlace,
  WorkspaceConversationResponse,
  WorkspaceEvidenceView,
  WorkspaceView,
} from "./types";
import { safeApiErrorMessage } from "./api-error";
import { buildPlacePatchOperation } from "./patch-operations";

const DEVELOPMENT_SESSION = getWorkspaceSession();
const OWNER_ID = DEVELOPMENT_SESSION.ownerUserId;
const THREAD_ID = DEVELOPMENT_SESSION.threadId;
const STORAGE_KEY = DEVELOPMENT_SESSION.tripStorageKey;
const LEGACY_STORAGE_KEY = "pilgrimage-workspace-v2";

type Stage = "conversation" | "map" | "context";
type MapFilter = "all" | "scheduled" | "unscheduled";

function tomorrowIso(offset = 30) {
  const value = new Date();
  value.setDate(value.getDate() + offset);
  return value.toISOString().slice(0, 10);
}

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    throw new Error(await safeApiErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function mobileSceneImage(value: string): string {
  const url = new URL(value);
  url.searchParams.set("plan", "h360");
  return url.toString();
}

function sourceLabel(value: string | null): string {
  return value && !value.toLocaleLowerCase().includes("anitabi") ? value : "场景资料来源";
}

function pointSourceLabel(value: string): string {
  if (value === "anitabi_static") return "静态地图资料";
  if (value === "anitabi_detail") return "详情资料回退";
  if (value.includes("fixture")) return "离线验收资料";
  return "导入资料";
}

function strategyLabel(value: string): string {
  return value === "low_walking" ? "少走路" : value === "primary_subject_first" ? "优先主要作品" : "综合安排";
}

function userFacingWarning(value: string): string {
  const normalized = value.toLocaleLowerCase();
  if (normalized.includes("weather") || normalized.includes("forecast")) {
    return "旅行日期的天气资料目前不在可靠范围内，请在出发前刷新确认。";
  }
  if (normalized.includes("walking") || normalized.includes("matrix")) {
    return "部分步行时间暂时只能估算，实际游览时请以现场路线为准。";
  }
  if (normalized.includes("transit") || normalized.includes("flight") || normalized.includes("access")) {
    return "部分交通资料暂时无法核实，出发前需要重新确认班次与耗时。";
  }
  if (normalized.includes("point") || normalized.includes("scene") || normalized.includes("evidence")) {
    return "部分场景资料不完整，未核实的内容不会作为确定事实安排。";
  }
  return "部分辅助资料暂时不可用；当前行程只采用已经核实的内容。";
}

function operationLabel(operation: { op: string; [key: string]: unknown }) {
  if (operation.op === "subject_intent") {
    return operation.action === "add" ? "添加作品" : operation.action === "remove" ? "移除作品" : "调整作品";
  }
  if (operation.op === "place" || operation.op === "place_batch") {
    const count = Array.isArray(operation.place_ids) ? operation.place_ids.length : 1;
    const prefix = count > 1 ? `${count} 个地点：` : "";
    const dayLabel = typeof operation.target_day === "number"
      ? operation.target_day.toString()
      : "?";
    const labels: Record<string, string> = {
      include: "加入行程候选",
      exclude: "从行程中排除",
      move_day: `移到第 ${dayLabel} 天`,
      reorder: `调整第 ${dayLabel} 天的顺序`,
    };
    return `${prefix}${labels[String(operation.action)] ?? "调整地点"}`;
  }
  const fields: Record<string, string> = {
    start_date: "修改开始日期",
    end_date: "修改结束日期",
    walking_preference: "修改步行偏好",
    max_walking_meters_per_day: "修改每日步行上限",
  };
  return fields[String(operation.field)] ?? "更新行程要求";
}

function pendingPreview(workspace: WorkspaceView): PatchPreview["preview"] | null {
  if (!workspace.pending_patch_id) return null;
  const patch = workspace.patches.find(
    (item) => item.patch_id === workspace.pending_patch_id && item.status === "proposed",
  );
  const impact = workspace.impacts.find(
    (item) => item.patch_id === workspace.pending_patch_id,
  );
  return patch && impact ? { patch, impact } : null;
}

function preferredAreaId(workspace: WorkspaceView): string {
  return [...workspace.areas]
    .sort((left, right) => right.place_ids.length - left.place_ids.length
      || left.label.localeCompare(right.label))[0]?.area_id ?? "all";
}

function WorkspaceMap({ places, focusPlaceIds, highlightedIds, onSelect }: {
  places: VisitPlace[];
  focusPlaceIds: Set<string>;
  highlightedIds: Set<string>;
  onSelect: (placeId: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const onSelectRef = useRef(onSelect);

  useEffect(() => { onSelectRef.current = onSelect; }, [onSelect]);

  useEffect(() => {
    if (!container.current || places.length === 0) return;
    markers.current.forEach((marker) => marker.remove());
    map.current?.remove();
    const focusPlaces = places.filter((place) => focusPlaceIds.has(place.place_id));
    const cameraPlaces = focusPlaces.length > 0 ? focusPlaces : places;
    const bounds = new maplibregl.LngLatBounds();
    cameraPlaces.forEach((place) => bounds.extend([place.coordinate.longitude, place.coordinate.latitude]));
    const firstFocus = cameraPlaces[0];
    if (!firstFocus) return;
    const instance = new maplibregl.Map({
      container: container.current,
      style: ROUTE_MAP_STYLE_URL,
      center: [firstFocus.coordinate.longitude, firstFocus.coordinate.latitude],
      zoom: 11,
      attributionControl: { compact: true },
      cooperativeGestures: true,
      dragRotate: false,
      pitchWithRotate: false,
    });
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = instance;
    markers.current = places.map((place, index) => {
      const button = document.createElement("button");
      button.className = `mix-map-marker${place.subject_appearances.length > 1 ? " is-shared" : ""}`;
      button.type = "button";
      button.textContent = String(index + 1);
      button.title = place.canonical_name;
      button.setAttribute("aria-label", `查看地点：${place.canonical_name}`);
      button.addEventListener("click", () => onSelectRef.current(place.place_id));
      return new maplibregl.Marker({ element: button })
        .setLngLat([place.coordinate.longitude, place.coordinate.latitude])
        .addTo(instance);
    });
    const fitCamera = () => {
      instance.resize();
      if (cameraPlaces.length === 1) {
        instance.jumpTo({
          center: [firstFocus.coordinate.longitude, firstFocus.coordinate.latitude],
          zoom: 14,
        });
      } else {
        instance.fitBounds(bounds, { padding: 70, maxZoom: 15, duration: 0 });
      }
    };
    if (instance.loaded()) fitCamera(); else void instance.once("load", fitCamera);
    return () => {
      markers.current.forEach((marker) => marker.remove());
      markers.current = [];
      instance.remove();
      map.current = null;
    };
  }, [focusPlaceIds, places]);

  useEffect(() => {
    markers.current.forEach((marker, index) => {
      const place = places[index];
      if (place) marker.getElement().classList.toggle("is-active", highlightedIds.has(place.place_id));
    });
  }, [highlightedIds, places]);

  if (places.length === 0) {
    return (
      <div className="mix-map-empty">
        <MapPinned aria-hidden="true" />
        <strong>确认作品后生成地点地图</strong>
        <span>我会先整理重复地点，再把适合查看的位置放到地图上。</span>
      </div>
    );
  }
  return <div ref={container} className="mix-map" aria-label={`巡礼地点地图，共 ${places.length} 个地点`} />;
}

function ProgressCounts({ workspace }: { workspace: WorkspaceView }) {
  const entries = [
    ["场景资料", workspace.counts.raw_scene_records],
    ["巡礼地点", workspace.counts.canonical_places],
    ["游览区域", workspace.counts.areas],
    ["已安排", workspace.counts.scheduled_places],
  ] as const;
  return (
    <ol className="mix-count-flow" aria-label="数据归并进度">
      {entries.map(([label, count], index) => (
        <li key={label}>
          <span>{label}</span><strong>{count}</strong>
          {index < entries.length - 1 && <ChevronRight aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

function SubjectConfirmation({ workspace, busy, onConfirm, onRemove, onRestart, onDone }: {
  workspace: WorkspaceView;
  busy: boolean;
  onConfirm: (choices: Record<string, string[]>) => Promise<void>;
  onRemove: (intentId: string, query: string) => Promise<void>;
  onRestart: () => void;
  onDone?: (() => void) | undefined;
}) {
  const [choices, setChoices] = useState<Record<string, string[]>>(() => Object.fromEntries(
    workspace.subject_groups.flatMap((group) => {
      if (group.intent.confirmed_subject_ids.length > 0) {
        return [[group.intent.intent_id, group.intent.confirmed_subject_ids]];
      }
      return group.candidates[0]
        ? [[group.intent.intent_id, [group.candidates[0].subject_id]]]
        : [];
    }),
  ));
  const hasMissingCandidates = workspace.subject_groups.some((group) => group.candidates.length === 0);
  const canConfirm = workspace.subject_groups.every(
    (group) => group.candidates.length > 0 && (choices[group.intent.intent_id]?.length ?? 0) > 0,
  );
  const selectedCount = Object.values(choices).reduce((total, selected) => total + selected.length, 0);
  function toggleCandidate(intentId: string, subjectId: string) {
    setChoices((current) => {
      const selected = current[intentId] ?? [];
      const next = selected.includes(subjectId)
        ? selected.filter((item) => item !== subjectId)
        : [...selected, subjectId];
      return { ...current, [intentId]: next };
    });
  }
  return (
    <section className="mix-confirm-card" aria-labelledby="mix-confirm-title">
      <div className="mix-section-heading">
        <div><span className="mix-kicker">需要你确认</span><h3 id="mix-confirm-title">作品匹配结果</h3></div>
        <span>已选 {selectedCount} 个条目</span>
      </div>
      <p>请勾选你想巡礼的条目；不同季度和剧场版可以同时选择。</p>
      <div className="mix-subject-groups">
        {workspace.subject_groups.map((group) => (
          <fieldset key={group.intent.intent_id}>
            <legend><span>{group.intent.query} · 优先级 {group.intent.priority}</span>{workspace.subject_groups.length > 1 && <button className="mix-subject-remove" type="button" disabled={busy} onClick={() => void onRemove(group.intent.intent_id, group.intent.query)}><Trash2 aria-hidden="true" />移除这部作品</button>}</legend>
            {group.candidates.length === 0 && <p className="mix-warning">暂时没有找到匹配作品，请返回修改名称后重试。</p>}
            {group.candidates.length > 1 && (
              <button
                className="mix-subject-select-all"
                type="button"
                onClick={() => setChoices((current) => ({
                  ...current,
                  [group.intent.intent_id]: group.candidates.map((candidate) => candidate.subject_id),
                }))}
              >
                选择全部季度与版本
              </button>
            )}
            {group.candidates.map((candidate) => (
              <label key={candidate.subject_id} className={choices[group.intent.intent_id]?.includes(candidate.subject_id) ? "is-selected" : ""}>
                <input
                  type="checkbox"
                  name={group.intent.intent_id}
                  value={candidate.subject_id}
                  checked={choices[group.intent.intent_id]?.includes(candidate.subject_id) ?? false}
                  onChange={() => toggleCandidate(group.intent.intent_id, candidate.subject_id)}
                />
                <span><strong>{candidate.name_cn || candidate.name}</strong><small>{candidate.name}</small></span>
                <Check aria-hidden="true" />
              </label>
            ))}
          </fieldset>
        ))}
      </div>
      <div className="mix-confirm-actions">
        <button
          className="mix-primary-button"
          type="button"
          disabled={busy || !canConfirm}
          onClick={() => void onConfirm(choices)}
        >
          {busy ? <RefreshCw className="is-spinning" aria-hidden="true" /> : <Check aria-hidden="true" />}
          确认并整理地点
        </button>
        {onDone && <button className="mix-text-button" type="button" disabled={busy} onClick={onDone}>取消编辑</button>}
        {hasMissingCandidates && workspace.subject_groups.length === 1 && <button className="mix-text-button" type="button" onClick={onRestart}>返回修改作品名称</button>}
      </div>
    </section>
  );
}

export function TripWorkspace() {
  const [workspace, setWorkspace] = useState<WorkspaceView | null>(null);
  const [subjects, setSubjects] = useState("我想用三天巡礼《孤独摇滚！》和《莉可丽丝》，每天不要走太多路。");
  const [startDate, setStartDate] = useState(tomorrowIso());
  const [endDate, setEndDate] = useState(tomorrowIso(32));
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [preview, setPreview] = useState<PatchPreview["preview"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeStage, setActiveStage] = useState<Stage>("conversation");
  const [filter, setFilter] = useState<MapFilter>("all");
  const [subjectFilter, setSubjectFilter] = useState("all");
  const [areaFilter, setAreaFilter] = useState("all");
  const [confidenceFilter, setConfidenceFilter] = useState("all");
  const [selectedPlaceId, setSelectedPlaceId] = useState<string | null>(null);
  const [selectedPlaceIds, setSelectedPlaceIds] = useState<Set<string>>(new Set());
  const [multiSelect, setMultiSelect] = useState(false);
  const [evidence, setEvidence] = useState<SceneEvidence[] | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const [editingSubjects, setEditingSubjects] = useState(false);
  const [newSubject, setNewSubject] = useState("");
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [editingRequirements, setEditingRequirements] = useState(false);

  useEffect(() => {
    const tripId = window.sessionStorage.getItem(STORAGE_KEY)
      ?? window.sessionStorage.getItem(LEGACY_STORAGE_KEY);
    if (!tripId) return;
    setBusy(true);
    void Promise.all([
      api<WorkspaceView>(`/api/workspaces/${tripId}?owner_user_id=${OWNER_ID}&thread_id=${THREAD_ID}`),
      api<ConversationMessage[]>(`/api/workspaces/${tripId}/messages?owner_user_id=${OWNER_ID}&thread_id=${THREAD_ID}`),
    ])
      .then(([restoredWorkspace, restoredMessages]) => {
        setWorkspace(restoredWorkspace);
        setMessages(restoredMessages);
        setPreview(pendingPreview(restoredWorkspace));
        if (restoredWorkspace.itineraries.length > 0) setFilter("scheduled");
        else setAreaFilter(preferredAreaId(restoredWorkspace));
      })
      .catch(() => {
        window.sessionStorage.removeItem(STORAGE_KEY);
        window.sessionStorage.removeItem(LEGACY_STORAGE_KEY);
      })
      .finally(() => setBusy(false));
  }, []);

  const currentItinerary = workspace?.itineraries[0] ?? null;
  const scheduledIds = useMemo(() => new Set(
    currentItinerary?.days.flatMap((day) => day.visits.map((visit) => visit.place_id)) ?? [],
  ), [currentItinerary]);
  const filteredPlaces = useMemo(() => (workspace?.places ?? []).filter((place) => {
    if (filter === "scheduled" && !scheduledIds.has(place.place_id)) return false;
    if (filter === "unscheduled" && scheduledIds.has(place.place_id)) return false;
    if (subjectFilter !== "all" && !place.subject_appearances.some((item) => item.subject_id === subjectFilter)) return false;
    if (areaFilter !== "all" && !workspace?.areas.find((area) => area.area_id === areaFilter)?.place_ids.includes(place.place_id)) return false;
    if (confidenceFilter !== "all" && place.verification_status !== confidenceFilter) return false;
    return true;
  }), [areaFilter, confidenceFilter, filter, scheduledIds, subjectFilter, workspace]);
  const placeById = useMemo(() => new Map((workspace?.places ?? []).map((place) => [place.place_id, place])), [workspace]);
  const mapFocusIds = useMemo(() => {
    if (!workspace) return new Set<string>();
    if (areaFilter !== "all") {
      return new Set(workspace.areas.find((area) => area.area_id === areaFilter)?.place_ids ?? []);
    }
    if (filter === "scheduled" && scheduledIds.size > 0) return scheduledIds;
    const preferred = preferredAreaId(workspace);
    return new Set(workspace.areas.find((area) => area.area_id === preferred)?.place_ids ?? []);
  }, [areaFilter, filter, scheduledIds, workspace]);

  async function startWorkspace(event: FormEvent) {
    event.preventDefault();
    const queries = extractSubjectQueries(subjects);
    if (queries.length === 0) {
      setError("我还没认出作品名。可以像“巡礼《孤独摇滚！》和《莉可丽丝》”这样告诉我。");
      return;
    }
    setBusy(true); setError(null); setPreview(null);
    try {
      const body = await api<WorkspaceView>("/api/workspaces", {
        method: "POST",
        body: JSON.stringify({
          owner_user_id: OWNER_ID,
          thread_id: THREAD_ID,
          request_summary: subjects.trim(),
          requirements: {
            start_date: startDate,
            end_date: endDate,
            subject_intents: queries.map((query, index) => ({
              query, priority: Math.max(1, 5 - index), is_primary: index === 0,
            })),
          },
        }),
      });
      setWorkspace(body);
      setMessages(await api<ConversationMessage[]>(`/api/workspaces/${body.trip_id}/messages?owner_user_id=${OWNER_ID}&thread_id=${THREAD_ID}`));
      window.sessionStorage.setItem(STORAGE_KEY, body.trip_id);
      setActiveStage("map");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法创建工作区"); }
    finally { setBusy(false); }
  }

  async function confirmSubjects(choices: Record<string, string[]>) {
    if (!workspace) return;
    const confirmations = workspace.subject_groups.flatMap((group) => {
      const selected = choices[group.intent.intent_id] ?? [];
      const current = group.intent.confirmed_subject_ids;
      const unchanged = selected.length === current.length
        && selected.every((subjectId) => current.includes(subjectId));
      return unchanged ? [] : [{
        intent_id: group.intent.intent_id,
        decision: "accept",
        selected_subject_ids: selected,
      }];
    });
    if (confirmations.length === 0) {
      setEditingSubjects(false);
      return;
    }
    setBusy(true); setError(null);
    try {
      const body = await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/subjects/confirm`, {
        method: "POST",
        body: JSON.stringify({
          owner_user_id: OWNER_ID,
          thread_id: THREAD_ID,
          expected_state_version: workspace.state_version,
          confirmations,
        }),
      });
      setWorkspace(body); setAreaFilter(preferredAreaId(body)); setActiveStage("map"); setEditingSubjects(false); setEvidence(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "确认失败"); }
    finally { setBusy(false); }
  }

  async function plan() {
    if (!workspace || workspace.base_candidates.length === 0) return;
    const firstBase = workspace.base_candidates[0];
    if (!firstBase) return;
    setBusy(true); setError(null);
    try {
      const body = await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/plan`, {
        method: "POST",
        body: JSON.stringify({
          owner_user_id: OWNER_ID,
          thread_id: THREAD_ID,
          expected_state_version: workspace.state_version,
          base_id: workspace.selected_base_id ?? firstBase.base_id,
        }),
      });
      setWorkspace(body);
      setFilter("scheduled"); setAreaFilter("all");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "规划失败"); }
    finally { setBusy(false); }
  }

  async function proposeNaturalPatch(event: FormEvent) {
    event.preventDefault();
    if (!workspace || !message.trim()) return;
    setBusy(true); setError(null);
    try {
      const body = await api<WorkspaceConversationResponse>(`/api/workspaces/${workspace.trip_id}/messages`, {
        method: "POST",
        body: JSON.stringify({
          owner_user_id: OWNER_ID,
          thread_id: THREAD_ID,
          message: message.trim(),
        }),
      });
      setWorkspace(body.workspace); setMessages(body.messages); setPreview(body.preview); setMessage("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法理解这次修改"); }
    finally { setBusy(false); }
  }

  async function previewPlacePatch(
    places: VisitPlace[],
    action: "include" | "exclude" | "move_day" | "reorder",
    targetDay?: number,
    targetPosition?: number,
  ) {
    if (!workspace || places.length === 0) return;
    const subject = places.length === 1 ? places[0]?.canonical_name : `${places.length} 个地点`;
    const patch: PlanPatch = {
      patch_id: crypto.randomUUID(),
      trip_id: workspace.trip_id,
      expected_base_version: workspace.state_version,
      rationale: action === "exclude" ? `从候选中排除 ${subject}` : action === "include" ? `把 ${subject} 加入候选` : action === "reorder" ? `把 ${subject} 置于第 ${targetDay} 天首位` : `把 ${subject} 移到第 ${targetDay} 天`,
      requires_confirmation: false,
      status: "proposed",
      idempotency_key: `web:${crypto.randomUUID()}`,
      created_at: new Date().toISOString(),
      operations: [buildPlacePatchOperation(places, action, targetDay, targetPosition)],
    };
    setBusy(true); setError(null);
    try {
      const body = await api<PatchPreview>(`/api/workspaces/${workspace.trip_id}/patches/preview`, {
        method: "POST",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, patch }),
      });
      setWorkspace(body.workspace); setPreview(body.preview);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法预览修改"); }
    finally { setBusy(false); }
  }

  async function previewSubjectPatch(action: "add" | "remove", value: string, query?: string) {
    if (!workspace) return;
    const normalizedQuery = value.trim();
    if (action === "add" && !normalizedQuery) return;
    const operation = action === "add" ? {
      op: "subject_intent",
      action: "add",
      intent: {
        intent_id: crypto.randomUUID(),
        query: normalizedQuery,
        confirmed_subject_id: null,
        confirmed_subject_ids: [],
        priority: 3,
        minimum_place_count: null,
        is_primary: false,
        status: "proposed",
      },
    } : { op: "subject_intent", action: "remove", intent_id: value };
    const label = action === "add" ? normalizedQuery : query ?? "这部作品";
    const patch: PlanPatch = {
      patch_id: crypto.randomUUID(),
      trip_id: workspace.trip_id,
      expected_base_version: workspace.state_version,
      rationale: action === "add" ? `添加作品《${label}》并核对匹配条目` : `从本次巡礼中移除《${label}》`,
      requires_confirmation: true,
      status: "proposed",
      idempotency_key: `web-subject:${crypto.randomUUID()}`,
      created_at: new Date().toISOString(),
      operations: [operation],
    };
    setBusy(true); setError(null);
    try {
      const body = await api<PatchPreview>(`/api/workspaces/${workspace.trip_id}/patches/preview`, {
        method: "POST",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, patch }),
      });
      setWorkspace(body.workspace); setPreview(body.preview);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法预览作品修改"); }
    finally { setBusy(false); }
  }

  async function addSubject(event: FormEvent) {
    event.preventDefault();
    if (!newSubject.trim()) return;
    await previewSubjectPatch("add", newSubject);
  }

  async function previewRequirementPatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workspace) return;
    const form = new FormData(event.currentTarget);
    const fields = [
      ["origin", workspace.requirements.origin],
      ["destination", workspace.requirements.destination],
      ["base_preference", workspace.requirements.base_preference],
      ["start_date", workspace.requirements.start_date],
      ["end_date", workspace.requirements.end_date],
      ["walking_preference", workspace.requirements.walking_preference],
    ] as const;
    const operations = fields.flatMap(([field, current]) => {
      const formValue = form.get(field);
      const raw = typeof formValue === "string" ? formValue.trim() : "";
      const value = raw || null;
      return value === (current ?? null) ? [] : [{ op: "update_requirement", field, value }];
    });
    if (operations.length === 0) { setEditingRequirements(false); return; }
    const patch: PlanPatch = {
      patch_id: crypto.randomUUID(),
      trip_id: workspace.trip_id,
      expected_base_version: workspace.state_version,
      rationale: "更新可编辑的行程条件",
      requires_confirmation: true,
      status: "proposed",
      idempotency_key: `web-requirements:${crypto.randomUUID()}`,
      created_at: new Date().toISOString(),
      operations,
    };
    setBusy(true); setError(null);
    try {
      const body = await api<PatchPreview>(`/api/workspaces/${workspace.trip_id}/patches/preview`, {
        method: "POST",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, patch }),
      });
      setWorkspace(body.workspace); setPreview(body.preview); setEditingRequirements(false);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法预览条件修改"); }
    finally { setBusy(false); }
  }

  async function applyPatch() {
    if (!workspace || !preview) return;
    setBusy(true); setError(null);
    try {
      const body = await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/patches/${preview.patch.patch_id}/apply`, {
        method: "POST",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, confirm: preview.impact.confirmation_required }),
      });
      setWorkspace(body); setPreview(null); setSelectedPlaceIds(new Set()); setEvidence(null);
      if (body.status === "awaiting_subject_confirmation") {
        setEditingSubjects(true);
        setActiveStage("map");
      }
      setNewSubject("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "应用修改失败"); }
    finally { setBusy(false); }
  }

  async function clearSchedule() {
    if (!workspace) return;
    setBusy(true); setError(null);
    try {
      const body = await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/schedule/clear`, {
        method: "POST",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, expected_state_version: workspace.state_version }),
      });
      setWorkspace(body); setFilter("all"); setPreview(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法清空行程"); }
    finally { setBusy(false); }
  }

  async function clearDay(dayNumber: number) {
    if (!workspace) return;
    setBusy(true); setError(null);
    try {
      const body = await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/days/${dayNumber}/clear`, {
        method: "POST",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, expected_state_version: workspace.state_version }),
      });
      setWorkspace(body); setPreview(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法清空当天安排"); }
    finally { setBusy(false); }
  }

  async function restoreItinerary(itineraryId: string) {
    if (!workspace) return;
    setBusy(true); setError(null);
    try {
      const body = await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/itineraries/${itineraryId}/restore`, {
        method: "POST",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, expected_state_version: workspace.state_version }),
      });
      setWorkspace(body);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法恢复这个版本"); }
    finally { setBusy(false); }
  }

  async function deleteItinerary(itineraryId: string) {
    if (!workspace) return;
    setBusy(true); setError(null);
    try {
      const body = await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/itineraries/${itineraryId}`, {
        method: "DELETE",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, expected_state_version: workspace.state_version }),
      });
      setWorkspace(body);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法删除这个版本"); }
    finally { setBusy(false); }
  }

  async function acceptKnowledgeRule(ruleId: string) {
    if (!workspace) return;
    setBusy(true); setError(null);
    try {
      const body = await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/knowledge/rules/${ruleId}/accept`, {
        method: "POST",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, expected_base_version: workspace.state_version, idempotency_key: `web-rule:${crypto.randomUUID()}`, confirm: true }),
      });
      setWorkspace(body);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法启用这条资料规则"); }
    finally { setBusy(false); }
  }

  async function changeKnowledgeRule(ruleId: string, action: "deactivate" | "delete") {
    if (!workspace) return;
    setBusy(true); setError(null);
    try {
      const suffix = action === "deactivate" ? `/${ruleId}/deactivate` : `/${ruleId}`;
      const body = await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/knowledge/rules${suffix}`, {
        method: action === "deactivate" ? "POST" : "DELETE",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, expected_state_version: workspace.state_version }),
      });
      setWorkspace(body);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法更新这条资料规则"); }
    finally { setBusy(false); }
  }

  async function archiveAndClose() {
    if (!workspace) return;
    setBusy(true); setError(null);
    try {
      await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/archive`, {
        method: "POST",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, expected_state_version: workspace.state_version }),
      });
      reset();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法归档工作区"); }
    finally { setBusy(false); }
  }

  async function permanentlyDelete() {
    if (!workspace) return;
    if (!deleteArmed) { setDeleteArmed(true); return; }
    setBusy(true); setError(null);
    try {
      await api<{ trip_id: string; deleted: true }>(`/api/workspaces/${workspace.trip_id}?owner_user_id=${OWNER_ID}&thread_id=${THREAD_ID}`, { method: "DELETE" });
      reset();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法永久删除工作区"); }
    finally { setBusy(false); }
  }

  function reset() {
    window.sessionStorage.removeItem(STORAGE_KEY);
    window.sessionStorage.removeItem(LEGACY_STORAGE_KEY);
    setWorkspace(null); setMessages([]); setPreview(null); setError(null); setSelectedPlaceId(null);
    setSelectedPlaceIds(new Set()); setMultiSelect(false); setEvidence(null);
    setFilter("all"); setSubjectFilter("all"); setAreaFilter("all"); setConfidenceFilter("all");
    setDeleteArmed(false);
  }

  function selectMapPlace(placeId: string) {
    setSelectedPlaceId(placeId);
    if (!multiSelect) return;
    setSelectedPlaceIds((current) => {
      const next = new Set(current);
      if (next.has(placeId)) next.delete(placeId); else next.add(placeId);
      return next;
    });
  }

  function toggleMultiSelect() {
    setMultiSelect((current) => !current);
    setSelectedPlaceIds(new Set());
  }

  const selectedPlace = selectedPlaceId ? placeById.get(selectedPlaceId) ?? null : null;
  const highlightedIds = useMemo(
    () => multiSelect ? selectedPlaceIds : new Set(selectedPlaceId ? [selectedPlaceId] : []),
    [multiSelect, selectedPlaceId, selectedPlaceIds],
  );
  const batchPlaces = useMemo(
    () => [...selectedPlaceIds].flatMap((placeId) => {
      const place = placeById.get(placeId);
      return place ? [place] : [];
    }),
    [placeById, selectedPlaceIds],
  );
  const selectedEvidence = useMemo(
    () => selectedPlace && evidence
      ? evidence.filter((item) => selectedPlace.scene_evidence_ids.includes(item.evidence_id))
      : [],
    [evidence, selectedPlace],
  );
  const subjectNames = useMemo(() => new Map(
    (workspace?.confirmed_subjects ?? []).map((item) => [
      item.subject.subject_id,
      item.subject.name_cn || item.subject.name,
    ]),
  ), [workspace]);
  const userWarnings = useMemo(
    () => [...new Set((workspace?.warnings ?? []).map(userFacingWarning))],
    [workspace],
  );

  useEffect(() => {
    if (!workspace || !selectedPlaceId || evidence !== null || evidenceLoading) return;
    setEvidenceLoading(true);
    void api<WorkspaceEvidenceView>(`/api/workspaces/${workspace.trip_id}/evidence?owner_user_id=${OWNER_ID}&thread_id=${THREAD_ID}`)
      .then((body) => setEvidence(body.evidence))
      .catch(() => setError("暂时无法加载这个地点的场景详情，请稍后重试。"))
      .finally(() => setEvidenceLoading(false));
  }, [evidence, evidenceLoading, selectedPlaceId, workspace]);

  return (
    <main className="mix-workspace" id="main-workspace">
      <a className="mix-skip-link" href="#mix-canvas">跳到规划画布</a>
      <header className="mix-header">
        <div>
          <span className="mix-kicker">巡礼规划助手</span>
          <h1>多作品巡礼工作区</h1>
          <p>告诉我想去的作品和旅行节奏，我会整理地点并安排每天的路线。</p>
        </div>
        <div className="mix-safety"><CircleDot aria-hidden="true" />仅提供只读规划，不执行预订或付款</div>
      </header>

      <nav className="mix-mobile-tabs" aria-label="工作区面板">
        {(["conversation", "map", "context"] as Stage[]).map((stage) => (
          <button key={stage} className={activeStage === stage ? "is-active" : ""} onClick={() => setActiveStage(stage)}>
            {stage === "conversation" ? "对话" : stage === "map" ? "地图与行程" : "行程信息"}
          </button>
        ))}
      </nav>

      <div className={`mix-shell${workspace ? "" : " is-empty"}`}>
        <aside className={`mix-pane mix-conversation ${activeStage === "conversation" ? "is-mobile-active" : ""}`} aria-label="规划对话">
          <div className="mix-pane-title"><MessageSquareText aria-hidden="true" /><div><strong>规划助手</strong><span>聊聊你的行程</span></div></div>
          {!workspace ? (
            <form className="mix-start-form" onSubmit={(event) => void startWorkspace(event)}>
              <div className="mix-agent-note"><Bot aria-hidden="true" /><p>直接告诉我你想巡礼哪些作品、准备玩几天，以及希望少走路还是多看地点。</p></div>
              <label>你的巡礼想法<textarea value={subjects} onChange={(event) => setSubjects(event.target.value)} rows={5} placeholder="例如：我想三天巡礼《孤独摇滚！》和《莉可丽丝》，住在新宿附近，每天少走一点。" /></label>
              <div className="mix-date-grid">
                <label>开始日期<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
                <label>结束日期<input type="date" value={endDate} min={startDate} onChange={(event) => setEndDate(event.target.value)} /></label>
              </div>
              <button className="mix-primary-button" disabled={busy} type="submit"><Sparkles aria-hidden="true" />开始规划</button>
            </form>
          ) : (
            <>
              <div className="mix-agent-note"><Bot aria-hidden="true" /><p>{workspace.status === "awaiting_subject_confirmation" ? "请在地图区域确认作品是否匹配。" : currentItinerary ? "行程已生成。你可以继续用自然语言修改，所有变更会先显示影响范围。" : "地点已经整理好了，现在可以生成每天的行程。"}</p></div>
              {messages.length > 0 && <ol className="mix-transcript" aria-label="持续对话记录">{messages.slice(-8).map((item) => <li key={item.message_id} className={item.role}><span>{item.role === "assistant" ? "助手" : "你"}</span><p>{item.content}</p></li>)}</ol>}
              <form className="mix-message-form" onSubmit={(event) => void proposeNaturalPatch(event)}>
                <label htmlFor="mix-patch-message">继续修改行程</label>
                <textarea id="mix-patch-message" value={message} onChange={(event) => setMessage(event.target.value)} placeholder={currentItinerary ? "例如：第二天少走一点，把车站附近的地点放在一起" : "可以继续补充住宿、交通或步行偏好"} rows={4} disabled={busy} />
                <button type="submit" disabled={!message.trim() || busy}><Send aria-hidden="true" />发送</button>
              </form>
              {currentItinerary && <button className="mix-text-button" type="button" disabled={busy} onClick={() => void clearSchedule()}><Trash2 aria-hidden="true" />清空已安排行程</button>}
              <button className="mix-text-button" type="button" disabled={busy} onClick={() => void archiveAndClose()}><X aria-hidden="true" />归档并关闭</button>
              <button className="mix-text-button" type="button" disabled={busy} onClick={() => void permanentlyDelete()}><Trash2 aria-hidden="true" />{deleteArmed ? "再次点击确认永久删除" : "永久删除工作区"}</button>
              {deleteArmed && <p className="mix-warning" role="alert">永久删除会清除当前工作区的对话、行程版本和资料关联，且无法撤销。</p>}
              <button className="mix-text-button" type="button" onClick={reset}><X aria-hidden="true" />仅关闭当前页面</button>
            </>
          )}
        </aside>

        <section className={`mix-pane mix-canvas ${activeStage === "map" ? "is-mobile-active" : ""}`} id="mix-canvas" aria-label="地图与行程画布">
          {!workspace ? (
            <div className="mix-canvas-empty">
              <div className="mix-canvas-empty-icon"><Layers3 aria-hidden="true" /></div>
              <span className="mix-kicker">准备开始</span>
              <h2>地点地图会在这里生成</h2>
              <p>提交左侧的巡礼想法后，我会先请你确认作品，再把场景整理成可规划的真实地点。</p>
              <ol>
                <li><strong>1</strong><span><b>确认作品</b><small>避免同名或相似作品混淆</small></span></li>
                <li><strong>2</strong><span><b>整理地点</b><small>合并重复场景并聚焦主要区域</small></span></li>
                <li><strong>3</strong><span><b>安排日程</b><small>按日期和步行偏好生成路线</small></span></li>
              </ol>
            </div>
          ) : (
            <>
              <ProgressCounts workspace={workspace} />
          {workspace.status === "awaiting_subject_confirmation" || editingSubjects ? (
            <SubjectConfirmation key={workspace.state_version} workspace={workspace} busy={busy} onConfirm={confirmSubjects} onRemove={(intentId, query) => previewSubjectPatch("remove", intentId, query)} onRestart={reset} onDone={workspace.status === "awaiting_subject_confirmation" ? undefined : () => setEditingSubjects(false)} />
          ) : (
            <>
              <div className="mix-canvas-toolbar">
                <div className="mix-filter-group" aria-label="地图筛选">
                  {(["all", "scheduled", "unscheduled"] as MapFilter[]).map((value) => <button key={value} className={filter === value ? "is-active" : ""} onClick={() => setFilter(value)}>{value === "all" ? "全部地点" : value === "scheduled" ? "已排程" : "未排程"}</button>)}
                </div>
                <div className="mix-map-selectors">
                  <label>作品<select value={subjectFilter} onChange={(event) => setSubjectFilter(event.target.value)}><option value="all">全部</option>{workspace?.confirmed_subjects.map((item) => <option key={item.subject.subject_id} value={item.subject.subject_id}>{item.subject.name_cn || item.subject.name}</option>)}</select></label>
                  <label>区域<select value={areaFilter} onChange={(event) => setAreaFilter(event.target.value)}><option value="all">全部</option>{workspace?.areas.map((area) => <option key={area.area_id} value={area.area_id}>{area.label}</option>)}</select></label>
                  <label>资料状态<select value={confidenceFilter} onChange={(event) => setConfidenceFilter(event.target.value)}><option value="all">全部</option><option value="verified">已核实</option><option value="community">社区资料</option><option value="unverified">待核实</option></select></label>
                </div>
                {workspace && workspace.places.length > 0 && <button className={multiSelect ? "mix-text-button is-active" : "mix-text-button"} type="button" onClick={toggleMultiSelect}><ListChecks aria-hidden="true" />{multiSelect ? "退出多选" : "批量选择"}</button>}
                {workspace && !currentItinerary && <button className="mix-primary-button is-compact" type="button" disabled={busy || workspace.base_candidates.length === 0} onClick={() => void plan()}><Route aria-hidden="true" />生成层级行程</button>}
              </div>
              {multiSelect && <div className="mix-bulk-bar" aria-live="polite">
                <div className="mix-bulk-heading"><div><strong>已选 {selectedPlaceIds.size} 个地点</strong><span>可在列表中连续勾选，也可以点击地图标记</span></div><div><button type="button" onClick={() => setSelectedPlaceIds(new Set(filteredPlaces.map((place) => place.place_id)))}>全选当前列表</button><button type="button" disabled={selectedPlaceIds.size === 0} onClick={() => setSelectedPlaceIds(new Set())}>清空选择</button></div></div>
                <ul className="mix-bulk-options" aria-label="批量选择地点">{filteredPlaces.map((place) => <li key={place.place_id}><label><input type="checkbox" checked={selectedPlaceIds.has(place.place_id)} onChange={() => { setSelectedPlaceId(place.place_id); setSelectedPlaceIds((current) => { const next = new Set(current); if (next.has(place.place_id)) next.delete(place.place_id); else next.add(place.place_id); return next; }); }} /><span>{place.canonical_name}</span></label></li>)}</ul>
                <div className="mix-bulk-actions"><button disabled={batchPlaces.length === 0} onClick={() => void previewPlacePatch(batchPlaces, "include")}>批量加入</button><button disabled={batchPlaces.length === 0} onClick={() => void previewPlacePatch(batchPlaces, "exclude")}>批量排除</button>{currentItinerary?.days.map((day, index) => <button disabled={batchPlaces.length === 0} key={day.date} onClick={() => void previewPlacePatch(batchPlaces, "move_day", index + 1)}>移到第 {index + 1} 天</button>)}</div>
              </div>}
              <WorkspaceMap places={filteredPlaces} focusPlaceIds={mapFocusIds} highlightedIds={highlightedIds} onSelect={selectMapPlace} />
              {areaFilter === "all" && filter !== "scheduled" && <p className="mix-map-focus-note">地图先聚焦点位最集中的区域；选择“区域”可查看其他地点。</p>}
              {filteredPlaces.length > 0 && <details className="mix-point-browser"><summary>浏览当前地点（{filteredPlaces.length}）</summary><ul>{filteredPlaces.map((place) => <li key={place.place_id}><button type="button" onClick={() => setSelectedPlaceId(place.place_id)}>{place.canonical_name}</button></li>)}</ul></details>}
              {workspace && workspace.places.some((place) => place.subject_appearances.length > 1) && <p className="mix-map-legend"><span />双色点位表示多作品共享的同一真实地点</p>}
              {selectedPlace && (
                <section className="mix-place-detail" aria-labelledby="mix-place-detail-title">
                  <header><div><span className="mix-kicker">巡礼地点</span><h2 id="mix-place-detail-title">{selectedPlace.canonical_name}</h2><p>{selectedPlace.subject_appearances.map((item) => subjectNames.get(item.subject_id) ?? "相关作品").join(" · ")}</p></div><button type="button" aria-label="关闭地点详情" onClick={() => setSelectedPlaceId(null)}><X aria-hidden="true" /></button></header>
                  {evidenceLoading && <p className="mix-muted">正在加载场景详情…</p>}
                  {!evidenceLoading && selectedEvidence.length === 0 && <p className="mix-muted">这个地点暂时没有可展示的场景图片，仍可加入行程。</p>}
                  {selectedEvidence.length > 0 && <div className="mix-scene-grid">{selectedEvidence.map((item) => <article key={item.evidence_id}>{item.image_url && <img src={mobileSceneImage(item.image_url)} alt={`${subjectNames.get(item.subject_id) ?? "作品"}中的场景`} loading="lazy" />}<div><strong>{subjectNames.get(item.subject_id) ?? "相关作品"}</strong><span>{item.episode_refs.length ? item.episode_refs.join(" · ") : "集数时间待补充"}</span>{item.description && <p>{item.description}</p>}{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">{sourceLabel(item.source_label)}<ExternalLink aria-hidden="true" /></a>}</div></article>)}</div>}
                  <footer><button onClick={() => void previewPlacePatch([selectedPlace], "include")}>加入行程</button><button onClick={() => void previewPlacePatch([selectedPlace], "exclude")}>暂不安排</button>{currentItinerary?.days.map((day, index) => <span className="mix-place-day-actions" key={day.date}><button onClick={() => void previewPlacePatch([selectedPlace], "move_day", index + 1)}>移到第 {index + 1} 天</button><button onClick={() => void previewPlacePatch([selectedPlace], "reorder", index + 1, 0)}>当天置顶</button></span>)}</footer>
                </section>
              )}
              {currentItinerary && (
                <section className="mix-itinerary" aria-labelledby="mix-itinerary-title">
                  <div className="mix-section-heading"><div><span className="mix-kicker">版本 {currentItinerary.version}</span><h2 id="mix-itinerary-title">分日行程</h2></div><span>{strategyLabel(currentItinerary.strategy)}</span></div>
                  <div className="mix-day-grid">
                    {currentItinerary.days.map((day, index) => (
                      <article key={day.date}>
                        <header><span>DAY {index + 1}</span><strong>{day.date}</strong><small><Footprints aria-hidden="true" />{Math.round(day.walking_distance_meters / 100) / 10} km</small><button type="button" disabled={busy} onClick={() => void clearDay(index + 1)}>清空当天</button></header>
                        <ol>{day.visits.map((visit) => <li key={visit.place_id}><time>{formatTime(visit.start_at)}</time><button onClick={() => setSelectedPlaceId(visit.place_id)}>{placeById.get(visit.place_id)?.canonical_name ?? visit.place_id}</button></li>)}</ol>
                      </article>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
            </>
          )}
        </section>

        <aside className={`mix-pane mix-context ${activeStage === "context" ? "is-mobile-active" : ""}`} aria-label="行程信息与历史">
          <div className="mix-pane-title"><GitCompareArrows aria-hidden="true" /><div><strong>行程信息</strong><span>日期、版本与资料说明</span></div></div>
          {!workspace ? <p className="mix-muted">开始规划后，这里会显示日期、住宿、行程版本和资料说明。</p> : (
            <>
              <section className="mix-context-block mix-requirements"><h3><CalendarDays aria-hidden="true" />行程条件</h3><dl><div><dt>出发地</dt><dd>{workspace.requirements.origin ?? "待补充"}</dd></div><div><dt>目的地</dt><dd>{workspace.requirements.destination ?? "待补充"}</dd></div><div><dt>日期</dt><dd>{workspace.requirements.start_date ?? "未定"} — {workspace.requirements.end_date ?? "未定"}</dd></div><div><dt>住宿偏好</dt><dd>{workspace.requirements.base_preference ?? workspace.base_candidates.find((base) => base.base_id === workspace.selected_base_id)?.name ?? "待选择"}</dd></div><div><dt>步行</dt><dd>{workspace.requirements.walking_preference === "low" ? "尽量少走" : workspace.requirements.walking_preference === "high" ? "可以多走" : workspace.requirements.walking_preference === "medium" ? "适中" : "待补充"}</dd></div></dl><button type="button" onClick={() => setEditingRequirements((value) => !value)}>{editingRequirements ? "收起编辑" : "编辑行程条件"}</button>{editingRequirements && <form className="mix-requirement-form" onSubmit={(event) => void previewRequirementPatch(event)}><label>出发地<input name="origin" defaultValue={workspace.requirements.origin ?? ""} /></label><label>目的地<input name="destination" defaultValue={workspace.requirements.destination ?? ""} /></label><label>住宿区域<input name="base_preference" defaultValue={workspace.requirements.base_preference ?? ""} /></label><label>开始日期<input name="start_date" type="date" defaultValue={workspace.requirements.start_date ?? ""} /></label><label>结束日期<input name="end_date" type="date" defaultValue={workspace.requirements.end_date ?? ""} /></label><label>步行偏好<select name="walking_preference" defaultValue={workspace.requirements.walking_preference ?? ""}><option value="">待补充</option><option value="low">尽量少走</option><option value="medium">适中</option><option value="high">可以多走</option></select></label><button className="mix-primary-button is-compact" type="submit" disabled={busy}>预览条件修改</button></form>}</section>
              <section className="mix-context-block mix-work-manager"><h3><MapPinned aria-hidden="true" />作品管理</h3><ul>{workspace.requirements.subject_intents.map((intent) => <li key={intent.intent_id}><span><strong>{intent.query}</strong><small>{intent.confirmed_subject_ids.length ? `${intent.confirmed_subject_ids.length} 个条目` : "等待确认"}</small></span>{workspace.requirements.subject_intents.length > 1 && <button type="button" aria-label={`移除作品 ${intent.query}`} disabled={busy} onClick={() => void previewSubjectPatch("remove", intent.intent_id, intent.query)}><Trash2 aria-hidden="true" /></button>}</li>)}</ul><div className="mix-work-manager-actions"><button type="button" disabled={busy} onClick={() => { setEditingSubjects(true); setActiveStage("map"); }}>编辑已选版本</button><form onSubmit={(event) => void addSubject(event)}><label htmlFor="mix-add-subject">添加作品</label><div><input id="mix-add-subject" value={newSubject} onChange={(event) => setNewSubject(event.target.value)} placeholder="输入作品名称" maxLength={100} disabled={busy || workspace.requirements.subject_intents.length >= 12} /><button type="submit" disabled={busy || !newSubject.trim() || workspace.requirements.subject_intents.length >= 12}><Plus aria-hidden="true" />添加</button></div></form></div>{workspace.requirements.subject_intents.length >= 12 && <p className="mix-muted">一个工作区最多管理 12 部作品；可以先移除不需要的作品再添加。</p>}</section>
              {userWarnings.length > 0 && <section className="mix-context-block" aria-labelledby="mix-warning-title"><h3 id="mix-warning-title"><AlertTriangle aria-hidden="true" />需要留意</h3><ul className="mix-event-list">{userWarnings.map((warning) => <li key={warning}><span>{warning}</span></li>)}</ul></section>}
              <section className="mix-context-block"><h3><Clock3 aria-hidden="true" />修改记录</h3><ul className="mix-event-list">{workspace.diffs.slice().reverse().map((diff) => <li key={`${diff.from_version}-${diff.to_version}`}><span>行程版本 {diff.to_version}</span><small>{diff.changed_day_numbers.length ? `调整第 ${diff.changed_day_numbers.join("、")} 天` : "更新了行程要求"}</small></li>)}</ul>{workspace.diffs.length === 0 && <p className="mix-muted">还没有修改记录。</p>}</section>
              <section className="mix-context-block"><h3><GitCompareArrows aria-hidden="true" />行程版本</h3><ul className="mix-version-list">{workspace.itineraries.slice(0, 6).map((item, index) => <li key={item.itinerary_id}><strong>v{item.version}</strong><span>{strategyLabel(item.strategy)}</span><small>{item.days.reduce((total, day) => total + day.visits.length, 0)} 个地点{item.validation_issues.length ? ` · ${item.validation_issues.length} 项需调整` : " · 安排可行"}</small>{index >= (workspace.planning_strategies?.length ?? 2) && <span className="mix-version-actions"><button type="button" disabled={busy} onClick={() => void restoreItinerary(item.itinerary_id)}>恢复</button><button type="button" disabled={busy} onClick={() => void deleteItinerary(item.itinerary_id)}>删除</button></span>}</li>)}</ul></section>
              {(workspace.knowledge_evidence?.length ?? 0) > 0 && <section className="mix-context-block"><h3><Layers3 aria-hidden="true" />访问资料与规则</h3><ul className="mix-knowledge-list">{workspace.knowledge_evidence?.slice(0, 6).map((item) => <li key={item.evidence_id}><strong>{item.title}</strong><small>{item.excerpt}</small><span>{item.source_type === "official_notice" || item.source_type === "official_guide" ? "官方资料" : "参考资料"} · {item.accessed_at}</span>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">查看来源<ExternalLink aria-hidden="true" /></a>}</li>)}</ul>{workspace.knowledge_rules.length > 0 && <ul className="mix-rule-list">{workspace.knowledge_rules.map((rule) => <li key={rule.rule_id}><span>{rule.rule_type === "photography_restriction" ? "拍摄限制" : rule.rule_type === "closure_date_range" ? "关闭日期" : rule.rule_type}</span><small>{rule.status === "active_constraint" ? "已启用并进入行程校验" : rule.status === "proposed" ? "等待你确认" : "仅作参考，不会自动约束行程"}</small><span className="mix-version-actions">{rule.status === "proposed" && <button type="button" disabled={busy} onClick={() => void acceptKnowledgeRule(rule.rule_id)}>确认启用</button>}{rule.status === "active_constraint" && <button type="button" disabled={busy} onClick={() => void changeKnowledgeRule(rule.rule_id, "deactivate")}>停用</button>}<button type="button" disabled={busy} onClick={() => void changeKnowledgeRule(rule.rule_id, "delete")}>删除</button></span></li>)}</ul>}</section>}
              <section className="mix-context-block"><button className="mix-disclosure" onClick={() => setShowEvidence((value) => !value)} aria-expanded={showEvidence}><Layers3 aria-hidden="true" />资料说明 <span>{workspace.counts.raw_scene_records}</span></button>{showEvidence && <div className="mix-evidence-summary"><p>已整理 {workspace.counts.raw_scene_records} 条场景资料，形成 {workspace.counts.canonical_places} 个巡礼地点。</p><ul>{workspace.confirmed_subjects.map((item) => item.point_collection && <li key={item.subject.subject_id}><strong>{item.subject.name_cn || item.subject.name}</strong><span>{item.point_collection.loaded_count} / {item.point_collection.expected_count} 个点位 · {item.point_collection.is_complete ? "完整" : "部分"} · {pointSourceLabel(item.point_collection.provider)}{item.point_collection.data_version ? ` · 版本 ${item.point_collection.data_version}` : ""}</span></li>)}</ul>{workspace.counts.quarantined_records > 0 && <p>{workspace.counts.quarantined_records} 条资料因位置不明确而未加入地图。</p>}<p>出发前请再次确认开放时间和现场规则。</p></div>}</section>
            </>
          )}
        </aside>
      </div>

      {preview && (
        <div className="mix-preview-backdrop" role="presentation">
          <section className="mix-preview" role="dialog" aria-modal="true" aria-labelledby="mix-preview-title">
            <div className="mix-preview-icon"><GitCompareArrows aria-hidden="true" /></div>
            <div><span className="mix-kicker">修改预览</span><h2 id="mix-preview-title">应用这次修改？</h2><p>{preview.patch.rationale}</p></div>
            <dl><div><dt>准备修改</dt><dd>{preview.patch.operations.map(operationLabel).join("、")}</dd></div><div><dt>影响范围</dt><dd>{preview.impact.confirmation_required ? "旅行日期或整体安排会重新计算" : "只重新计算受影响的行程"}</dd></div><div><dt>保持不变</dt><dd>已确认的作品和地点资料</dd></div></dl>
            {preview.impact.confirmation_required && <p className="mix-preview-warning"><AlertTriangle aria-hidden="true" />这项变更会影响上游选择，需要明确确认。</p>}
            <div className="mix-preview-actions"><button onClick={() => setPreview(null)}>取消</button><button className="mix-primary-button" disabled={busy} onClick={() => void applyPatch()}><Check aria-hidden="true" />确认并重新规划</button></div>
          </section>
        </div>
      )}
      <div className="mix-live" aria-live="polite">{busy ? "正在处理…" : error ?? ""}</div>
    </main>
  );
}
