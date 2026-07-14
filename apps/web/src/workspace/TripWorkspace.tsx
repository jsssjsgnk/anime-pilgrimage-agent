import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CalendarDays,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  Footprints,
  GitCompareArrows,
  Layers3,
  MapPinned,
  MessageSquareText,
  RefreshCw,
  Route,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import maplibregl from "maplibre-gl";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { ROUTE_MAP_STYLE_URL } from "../route-map-config";
import type {
  ConversationMessage,
  PatchPreview,
  PlanPatch,
  VisitPlace,
  WorkspaceConversationResponse,
  WorkspaceView,
} from "./types";

const OWNER_ID = "local-web-user";
const THREAD_ID = "local-workspace-thread";
const STORAGE_KEY = "pilgrimage-workspace-v2";

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
    const body = await response.json().catch(() => ({ detail: response.statusText })) as { detail?: unknown };
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    throw new Error(detail || `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

function uniqueQueries(input: string): string[] {
  return [...new Set(input.split(/[、,，;；\n]+/).map((item) => item.trim()).filter(Boolean))].slice(0, 3);
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function operationLabel(operation: { op: string; [key: string]: unknown }) {
  const detail = typeof operation.action === "string"
    ? operation.action
    : typeof operation.field === "string" ? operation.field : "update";
  return `${operation.op}:${detail}`;
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

function WorkspaceMap({ places, highlightedId, onSelect }: {
  places: VisitPlace[];
  highlightedId: string | null;
  onSelect: (placeId: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);

  useEffect(() => {
    if (!container.current || places.length === 0) return;
    markers.current.forEach((marker) => marker.remove());
    map.current?.remove();
    const bounds = new maplibregl.LngLatBounds();
    places.forEach((place) => bounds.extend([place.coordinate.longitude, place.coordinate.latitude]));
    const instance = new maplibregl.Map({
      container: container.current,
      style: ROUTE_MAP_STYLE_URL,
      bounds,
      fitBoundsOptions: { padding: 70, maxZoom: 15 },
      attributionControl: { compact: true },
      cooperativeGestures: true,
      dragRotate: false,
      pitchWithRotate: false,
    });
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = instance;
    markers.current = places.map((place, index) => {
      const button = document.createElement("button");
      button.className = `mix-map-marker${place.subject_appearances.length > 1 ? " is-shared" : ""}${place.place_id === highlightedId ? " is-active" : ""}`;
      button.type = "button";
      button.textContent = String(index + 1);
      button.title = place.canonical_name;
      button.setAttribute("aria-label", `查看地点：${place.canonical_name}`);
      button.addEventListener("click", () => onSelect(place.place_id));
      return new maplibregl.Marker({ element: button })
        .setLngLat([place.coordinate.longitude, place.coordinate.latitude])
        .addTo(instance);
    });
    return () => {
      markers.current.forEach((marker) => marker.remove());
      markers.current = [];
      instance.remove();
      map.current = null;
    };
  }, [places, highlightedId, onSelect]);

  if (places.length === 0) {
    return (
      <div className="mix-map-empty">
        <MapPinned aria-hidden="true" />
        <strong>确认作品后生成地点地图</strong>
        <span>地图只展示归并后的规范地点；原始场景证据可在右侧检查。</span>
      </div>
    );
  }
  return <div ref={container} className="mix-map" aria-label={`规范地点地图，共 ${places.length} 个地点`} />;
}

function ProgressCounts({ workspace }: { workspace: WorkspaceView }) {
  const entries = [
    ["场景证据", workspace.counts.raw_scene_records],
    ["规范地点", workspace.counts.canonical_places],
    ["真实区域", workspace.counts.areas],
    ["已排程", workspace.counts.scheduled_places],
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

function SubjectConfirmation({ workspace, busy, onConfirm }: {
  workspace: WorkspaceView;
  busy: boolean;
  onConfirm: (choices: Record<string, string>) => Promise<void>;
}) {
  const [choices, setChoices] = useState<Record<string, string>>(() => Object.fromEntries(
    workspace.subject_groups.flatMap((group) => group.candidates[0]
      ? [[group.intent.intent_id, group.candidates[0].subject_id]] : []),
  ));
  return (
    <section className="mix-confirm-card" aria-labelledby="mix-confirm-title">
      <div className="mix-section-heading">
        <div><span className="mix-kicker">需要你确认</span><h3 id="mix-confirm-title">作品匹配结果</h3></div>
        <span>{workspace.subject_groups.length} 组意图</span>
      </div>
      <p>Agent 不会把同名或近似作品静默当成你的选择。每组请选择一个目录条目。</p>
      <div className="mix-subject-groups">
        {workspace.subject_groups.map((group) => (
          <fieldset key={group.intent.intent_id}>
            <legend>{group.intent.query} · 优先级 {group.intent.priority}</legend>
            {group.candidates.length === 0 && <p className="mix-warning">当前 Provider 没有返回候选，可稍后重试。</p>}
            {group.candidates.map((candidate) => (
              <label key={candidate.subject_id} className={choices[group.intent.intent_id] === candidate.subject_id ? "is-selected" : ""}>
                <input
                  type="radio"
                  name={group.intent.intent_id}
                  value={candidate.subject_id}
                  checked={choices[group.intent.intent_id] === candidate.subject_id}
                  onChange={() => setChoices((current) => ({ ...current, [group.intent.intent_id]: candidate.subject_id }))}
                />
                <span><strong>{candidate.name_cn || candidate.name}</strong><small>{candidate.name}</small></span>
                <Check aria-hidden="true" />
              </label>
            ))}
          </fieldset>
        ))}
      </div>
      <button
        className="mix-primary-button"
        type="button"
        disabled={busy || Object.keys(choices).length !== workspace.subject_groups.length}
        onClick={() => void onConfirm(choices)}
      >
        {busy ? <RefreshCw className="is-spinning" aria-hidden="true" /> : <Check aria-hidden="true" />}
        确认作品并归并地点
      </button>
    </section>
  );
}

export function TripWorkspace() {
  const [workspace, setWorkspace] = useState<WorkspaceView | null>(null);
  const [subjects, setSubjects] = useState("孤独摇滚！\n莉可丽丝");
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
  const [showEvidence, setShowEvidence] = useState(false);

  useEffect(() => {
    const tripId = window.sessionStorage.getItem(STORAGE_KEY);
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
      })
      .catch(() => window.sessionStorage.removeItem(STORAGE_KEY))
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

  async function startWorkspace(event: FormEvent) {
    event.preventDefault();
    const queries = uniqueQueries(subjects);
    if (queries.length === 0) { setError("请至少输入一部作品。"); return; }
    setBusy(true); setError(null); setPreview(null);
    try {
      const body = await api<WorkspaceView>("/api/workspaces", {
        method: "POST",
        body: JSON.stringify({
          owner_user_id: OWNER_ID,
          thread_id: THREAD_ID,
          request_summary: `从东京出发，巡礼 ${queries.join("、")}`,
          requirements: {
            origin: "东京",
            destination: "东京",
            start_date: startDate,
            end_date: endDate,
            walking_preference: "medium",
            subject_intents: queries.map((query, index) => ({
              query, priority: Math.max(1, 5 - index), is_primary: index === 0,
            })),
          },
        }),
      });
      setWorkspace(body);
      setMessages([]);
      window.sessionStorage.setItem(STORAGE_KEY, body.trip_id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法创建工作区"); }
    finally { setBusy(false); }
  }

  async function confirmSubjects(choices: Record<string, string>) {
    if (!workspace) return;
    setBusy(true); setError(null);
    try {
      const body = await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/subjects/confirm`, {
        method: "POST",
        body: JSON.stringify({
          owner_user_id: OWNER_ID,
          thread_id: THREAD_ID,
          expected_state_version: workspace.state_version,
          confirmations: workspace.subject_groups.map((group) => ({
            intent_id: group.intent.intent_id,
            decision: "accept",
            selected_subject_id: choices[group.intent.intent_id],
          })),
        }),
      });
      setWorkspace(body); setActiveStage("map");
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
    place: VisitPlace,
    action: "include" | "exclude" | "move_day" | "reorder",
    targetDay?: number,
    targetPosition?: number,
  ) {
    if (!workspace) return;
    const patch: PlanPatch = {
      patch_id: crypto.randomUUID(),
      trip_id: workspace.trip_id,
      expected_base_version: workspace.state_version,
      rationale: action === "exclude" ? `从候选中排除 ${place.canonical_name}` : action === "include" ? `把 ${place.canonical_name} 加入候选` : action === "reorder" ? `把 ${place.canonical_name} 置于第 ${targetDay} 天首位` : `把 ${place.canonical_name} 移到第 ${targetDay} 天`,
      requires_confirmation: false,
      status: "proposed",
      idempotency_key: `web:${crypto.randomUUID()}`,
      created_at: new Date().toISOString(),
      operations: [{ op: "place", action, place_id: place.place_id, ...(targetDay ? { target_day: targetDay } : {}), ...(targetPosition !== undefined ? { target_position: targetPosition } : {}) }],
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

  async function applyPatch() {
    if (!workspace || !preview) return;
    setBusy(true); setError(null);
    try {
      const body = await api<WorkspaceView>(`/api/workspaces/${workspace.trip_id}/patches/${preview.patch.patch_id}/apply`, {
        method: "POST",
        body: JSON.stringify({ owner_user_id: OWNER_ID, thread_id: THREAD_ID, confirm: preview.impact.confirmation_required }),
      });
      setWorkspace(body); setPreview(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "应用修改失败"); }
    finally { setBusy(false); }
  }

  function reset() {
    window.sessionStorage.removeItem(STORAGE_KEY);
    setWorkspace(null); setMessages([]); setPreview(null); setError(null); setSelectedPlaceId(null);
  }

  const selectedPlace = selectedPlaceId ? placeById.get(selectedPlaceId) ?? null : null;

  return (
    <main className="mix-workspace" id="main-workspace">
      <a className="mix-skip-link" href="#mix-canvas">跳到规划画布</a>
      <header className="mix-header">
        <div>
          <span className="mix-kicker">Anime Pilgrimage Agent</span>
          <h1>多作品巡礼工作区</h1>
          <p>从场景证据归并真实地点，再按区域与日期生成可解释行程。</p>
        </div>
        <div className="mix-safety"><CircleDot aria-hidden="true" />仅提供只读规划，不执行预订或付款</div>
      </header>

      <nav className="mix-mobile-tabs" aria-label="工作区面板">
        {(["conversation", "map", "context"] as Stage[]).map((stage) => (
          <button key={stage} className={activeStage === stage ? "is-active" : ""} onClick={() => setActiveStage(stage)}>
            {stage === "conversation" ? "对话" : stage === "map" ? "地图与行程" : "上下文"}
          </button>
        ))}
      </nav>

      <div className="mix-shell">
        <aside className={`mix-pane mix-conversation ${activeStage === "conversation" ? "is-mobile-active" : ""}`} aria-label="规划对话">
          <div className="mix-pane-title"><MessageSquareText aria-hidden="true" /><div><strong>规划 Agent</strong><span>需求与 PlanPatch</span></div></div>
          {!workspace ? (
            <form className="mix-start-form" onSubmit={(event) => void startWorkspace(event)}>
              <div className="mix-agent-note"><Bot aria-hidden="true" /><p>输入 1–3 部作品，每行一部。我会先要求确认目录身份，再拉取 Anitabi 场景证据。</p></div>
              <label>作品列表<textarea value={subjects} onChange={(event) => setSubjects(event.target.value)} rows={4} /></label>
              <div className="mix-date-grid">
                <label>开始日期<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
                <label>结束日期<input type="date" value={endDate} min={startDate} onChange={(event) => setEndDate(event.target.value)} /></label>
              </div>
              <button className="mix-primary-button" disabled={busy} type="submit"><Sparkles aria-hidden="true" />创建巡礼工作区</button>
            </form>
          ) : (
            <>
              <div className="mix-agent-note"><Bot aria-hidden="true" /><p>{workspace.status === "awaiting_subject_confirmation" ? "请在画布中确认作品匹配。" : currentItinerary ? "行程已生成。你可以继续用自然语言修改，所有变更会先显示影响范围。" : "地点已经按真实坐标归并并聚类，可以生成层级行程。"}</p></div>
              <div className="mix-mini-summary">
                <span>工作区</span><code>{workspace.trip_id.slice(0, 8)}</code>
                <span>状态</span><strong>{workspace.status}</strong>
              </div>
              {messages.length > 0 && <ol className="mix-transcript" aria-label="持续对话记录">{messages.slice(-8).map((item) => <li key={item.message_id} className={item.role}><span>{item.role === "assistant" ? "Agent" : "你"}</span><p>{item.content}</p></li>)}</ol>}
              <form className="mix-message-form" onSubmit={(event) => void proposeNaturalPatch(event)}>
                <label htmlFor="mix-patch-message">继续修改行程</label>
                <textarea id="mix-patch-message" value={message} onChange={(event) => setMessage(event.target.value)} placeholder={currentItinerary ? "例如：把步行偏好设为 low" : "可询问当前进展；生成首个行程后可继续修改"} rows={4} disabled={busy} />
                <button type="submit" disabled={!message.trim() || busy}><Send aria-hidden="true" />发送给 Agent</button>
              </form>
              <button className="mix-text-button" type="button" onClick={reset}><X aria-hidden="true" />关闭当前工作区</button>
            </>
          )}
        </aside>

        <section className={`mix-pane mix-canvas ${activeStage === "map" ? "is-mobile-active" : ""}`} id="mix-canvas" aria-label="地图与行程画布">
          {workspace ? <ProgressCounts workspace={workspace} /> : <div className="mix-canvas-intro"><Layers3 aria-hidden="true" /><span>场景证据</span><ArrowRight aria-hidden="true" /><span>规范地点</span><ArrowRight aria-hidden="true" /><span>区域</span><ArrowRight aria-hidden="true" /><span>日程</span></div>}
          {workspace?.status === "awaiting_subject_confirmation" ? (
            <SubjectConfirmation workspace={workspace} busy={busy} onConfirm={confirmSubjects} />
          ) : (
            <>
              <div className="mix-canvas-toolbar">
                <div className="mix-filter-group" aria-label="地图筛选">
                  {(["all", "scheduled", "unscheduled"] as MapFilter[]).map((value) => <button key={value} className={filter === value ? "is-active" : ""} onClick={() => setFilter(value)}>{value === "all" ? "全部地点" : value === "scheduled" ? "已排程" : "未排程"}</button>)}
                </div>
                <div className="mix-map-selectors">
                  <label>作品<select value={subjectFilter} onChange={(event) => setSubjectFilter(event.target.value)}><option value="all">全部</option>{workspace?.confirmed_subjects.map((item) => <option key={item.subject.subject_id} value={item.subject.subject_id}>{item.subject.name_cn || item.subject.name}</option>)}</select></label>
                  <label>区域<select value={areaFilter} onChange={(event) => setAreaFilter(event.target.value)}><option value="all">全部</option>{workspace?.areas.map((area) => <option key={area.area_id} value={area.area_id}>{area.label}</option>)}</select></label>
                  <label>可信度<select value={confidenceFilter} onChange={(event) => setConfidenceFilter(event.target.value)}><option value="all">全部</option><option value="verified">已验证</option><option value="partial">部分</option><option value="unverified">未验证</option></select></label>
                </div>
                {workspace && !currentItinerary && <button className="mix-primary-button is-compact" type="button" disabled={busy || workspace.base_candidates.length === 0} onClick={() => void plan()}><Route aria-hidden="true" />生成层级行程</button>}
              </div>
              <WorkspaceMap places={filteredPlaces} highlightedId={selectedPlaceId} onSelect={setSelectedPlaceId} />
              {workspace && workspace.places.some((place) => place.subject_appearances.length > 1) && <p className="mix-map-legend"><span />双色点位表示多作品共享的同一真实地点</p>}
              {selectedPlace && (
                <div className="mix-place-popover">
                  <div><span>规范地点</span><strong>{selectedPlace.canonical_name}</strong><small>{selectedPlace.subject_appearances.length} 部作品 · {selectedPlace.verification_status}</small></div>
                  <button onClick={() => void previewPlacePatch(selectedPlace, "include")}>加入</button>
                  <button onClick={() => void previewPlacePatch(selectedPlace, "exclude")}>排除</button>
                  {currentItinerary?.days.map((day, index) => <span className="mix-place-day-actions" key={day.date}><button onClick={() => void previewPlacePatch(selectedPlace, "move_day", index + 1)}>移到第 {index + 1} 天</button><button onClick={() => void previewPlacePatch(selectedPlace, "reorder", index + 1, 0)}>第 {index + 1} 天置顶</button></span>)}
                </div>
              )}
              {currentItinerary && (
                <section className="mix-itinerary" aria-labelledby="mix-itinerary-title">
                  <div className="mix-section-heading"><div><span className="mix-kicker">版本 {currentItinerary.version}</span><h2 id="mix-itinerary-title">分日行程</h2></div><span>{currentItinerary.strategy}</span></div>
                  <div className="mix-day-grid">
                    {currentItinerary.days.map((day, index) => (
                      <article key={day.date}>
                        <header><span>DAY {index + 1}</span><strong>{day.date}</strong><small><Footprints aria-hidden="true" />{Math.round(day.walking_distance_meters / 100) / 10} km</small></header>
                        <ol>{day.visits.map((visit) => <li key={visit.place_id}><time>{formatTime(visit.start_at)}</time><button onClick={() => setSelectedPlaceId(visit.place_id)}>{placeById.get(visit.place_id)?.canonical_name ?? visit.place_id}</button></li>)}</ol>
                      </article>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </section>

        <aside className={`mix-pane mix-context ${activeStage === "context" ? "is-mobile-active" : ""}`} aria-label="上下文与版本">
          <div className="mix-pane-title"><GitCompareArrows aria-hidden="true" /><div><strong>上下文与版本</strong><span>可追溯的 Agent 状态</span></div></div>
          {!workspace ? <p className="mix-muted">创建工作区后，这里会显示 Agent 交接、约束、版本与证据状态。</p> : (
            <>
              <section className="mix-context-block"><h3><CalendarDays aria-hidden="true" />行程范围</h3><dl><div><dt>日期</dt><dd>{workspace.requirements.start_date ?? "未定"} — {workspace.requirements.end_date ?? "未定"}</dd></div><div><dt>作品</dt><dd>{workspace.confirmed_subjects.length} / {workspace.subject_groups.length} 已确认</dd></div><div><dt>住宿基点</dt><dd>{workspace.base_candidates.find((base) => base.base_id === workspace.selected_base_id)?.name ?? "待选择"}</dd></div></dl></section>
              <section className="mix-context-block"><h3><Bot aria-hidden="true" />Agent 交接</h3><ul className="mix-event-list">{workspace.handoffs.slice(-6).reverse().map((handoff) => <li key={handoff.handoff_id}><span>{handoff.sender} → {handoff.receiver}</span><small>{handoff.task_type} · {handoff.status}</small></li>)}</ul></section>
              <section className="mix-context-block"><h3><Clock3 aria-hidden="true" />版本记录</h3><ul className="mix-event-list">{workspace.diffs.slice().reverse().map((diff) => <li key={`${diff.from_version}-${diff.to_version}`}><span>v{diff.from_version} → v{diff.to_version}</span><small>{diff.changed_requirements.length ? `需求：${diff.changed_requirements.join("、")}` : diff.changed_day_numbers.length ? `重排第 ${diff.changed_day_numbers.join("、")} 天` : "结构更新"}</small></li>)}</ul>{workspace.diffs.length === 0 && <p className="mix-muted">尚无修改版本。</p>}</section>
              <section className="mix-context-block"><h3><GitCompareArrows aria-hidden="true" />计划版本对比</h3><ul className="mix-version-list">{workspace.itineraries.slice(0, 6).map((item) => <li key={item.itinerary_id}><strong>v{item.version}</strong><span>{item.strategy}</span><small>{item.days.reduce((total, day) => total + day.visits.length, 0)} 地点 · {item.validation_issues.length} 违规</small></li>)}</ul></section>
              <section className="mix-context-block"><button className="mix-disclosure" onClick={() => setShowEvidence((value) => !value)} aria-expanded={showEvidence}><Layers3 aria-hidden="true" />证据与规则 <span>{workspace.counts.raw_scene_records + workspace.knowledge_rules.length}</span></button>{showEvidence && <div className="mix-evidence-summary"><p>原始场景证据 {workspace.counts.raw_scene_records} 条，其中隔离 {workspace.counts.quarantined_records} 条。</p><p>已接受知识约束 {workspace.knowledge_rules.filter((rule) => rule.status === "active_constraint").length} 条。</p><p>原始证据不会直接成为地图点位。</p></div>}</section>
            </>
          )}
        </aside>
      </div>

      {preview && (
        <div className="mix-preview-backdrop" role="presentation">
          <section className="mix-preview" role="dialog" aria-modal="true" aria-labelledby="mix-preview-title">
            <div className="mix-preview-icon"><GitCompareArrows aria-hidden="true" /></div>
            <div><span className="mix-kicker">PlanPatch 预览</span><h2 id="mix-preview-title">应用这次修改？</h2><p>{preview.patch.rationale}</p></div>
            <dl><div><dt>操作</dt><dd>{preview.patch.operations.map(operationLabel).join("、")}</dd></div><div><dt>重新计算</dt><dd>{preview.impact.invalidated_nodes.join("、")}</dd></div><div><dt>保持稳定</dt><dd>{preview.impact.stable_refs.length ? preview.impact.stable_refs.join("、") : "无可复用节点"}</dd></div></dl>
            {preview.impact.confirmation_required && <p className="mix-preview-warning"><AlertTriangle aria-hidden="true" />这项变更会影响上游选择，需要明确确认。</p>}
            <div className="mix-preview-actions"><button onClick={() => setPreview(null)}>取消</button><button className="mix-primary-button" disabled={busy} onClick={() => void applyPatch()}><Check aria-hidden="true" />确认并重新规划</button></div>
          </section>
        </div>
      )}
      <div className="mix-live" aria-live="polite">{busy ? "Agent 正在处理…" : error ?? ""}</div>
    </main>
  );
}
