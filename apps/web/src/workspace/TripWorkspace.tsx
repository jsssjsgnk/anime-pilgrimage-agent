import {
  AlertTriangle,
  ArrowRight,
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
  RefreshCw,
  Route,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import maplibregl from "maplibre-gl";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { ROUTE_MAP_STYLE_URL } from "../route-map-config";
import { extractSubjectQueries } from "./intake";
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

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function mobileSceneImage(value: string): string {
  return value.replace(/([?&])plan=h160(?=&|$)/u, "$1plan=h360");
}

function sourceLabel(value: string | null): string {
  return value && !value.toLocaleLowerCase().includes("anitabi") ? value : "场景资料来源";
}

function strategyLabel(value: string): string {
  return value === "low_walking" ? "少走路" : value === "primary_subject_first" ? "优先主要作品" : "综合安排";
}

function operationLabel(operation: { op: string; [key: string]: unknown }) {
  if (operation.op === "place") {
    const dayLabel = typeof operation.target_day === "number"
      ? operation.target_day.toString()
      : "?";
    const labels: Record<string, string> = {
      include: "加入行程候选",
      exclude: "从行程中排除",
      move_day: `移到第 ${dayLabel} 天`,
      reorder: `调整第 ${dayLabel} 天的顺序`,
    };
    return labels[String(operation.action)] ?? "调整地点";
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

function WorkspaceMap({ places, highlightedIds, onSelect }: {
  places: VisitPlace[];
  highlightedIds: Set<string>;
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
      button.className = `mix-map-marker${place.subject_appearances.length > 1 ? " is-shared" : ""}${highlightedIds.has(place.place_id) ? " is-active" : ""}`;
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
  }, [places, highlightedIds, onSelect]);

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
        <span>{workspace.subject_groups.length} 部作品</span>
      </div>
      <p>有些作品名称很相近，请确认下面是否是你想去的作品。</p>
      <div className="mix-subject-groups">
        {workspace.subject_groups.map((group) => (
          <fieldset key={group.intent.intent_id}>
            <legend>{group.intent.query} · 优先级 {group.intent.priority}</legend>
            {group.candidates.length === 0 && <p className="mix-warning">暂时没有找到匹配作品，请返回修改名称后重试。</p>}
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
        确认并整理地点
      </button>
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
        if (restoredWorkspace.itineraries.length > 0) setFilter("scheduled");
        else setAreaFilter(restoredWorkspace.areas[0]?.area_id ?? "all");
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
      setMessages(await api<ConversationMessage[]>(`/api/workspaces/${body.trip_id}/messages?owner_user_id=${OWNER_ID}&thread_id=${THREAD_ID}`));
      window.sessionStorage.setItem(STORAGE_KEY, body.trip_id);
      setActiveStage("map");
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
      setWorkspace(body); setAreaFilter(body.areas[0]?.area_id ?? "all"); setActiveStage("map");
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
      operations: places.map((place) => ({ op: "place", action, place_id: place.place_id, ...(targetDay ? { target_day: targetDay } : {}), ...(targetPosition !== undefined ? { target_position: targetPosition } : {}) })),
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
      setWorkspace(body); setPreview(null); setSelectedPlaceIds(new Set());
    } catch (cause) { setError(cause instanceof Error ? cause.message : "应用修改失败"); }
    finally { setBusy(false); }
  }

  function reset() {
    window.sessionStorage.removeItem(STORAGE_KEY);
    setWorkspace(null); setMessages([]); setPreview(null); setError(null); setSelectedPlaceId(null);
    setSelectedPlaceIds(new Set()); setMultiSelect(false); setEvidence(null);
    setFilter("all"); setSubjectFilter("all"); setAreaFilter("all"); setConfidenceFilter("all");
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

      <div className="mix-shell">
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
              <button className="mix-text-button" type="button" onClick={reset}><X aria-hidden="true" />关闭当前工作区</button>
            </>
          )}
        </aside>

        <section className={`mix-pane mix-canvas ${activeStage === "map" ? "is-mobile-active" : ""}`} id="mix-canvas" aria-label="地图与行程画布">
          {workspace ? <ProgressCounts workspace={workspace} /> : <div className="mix-canvas-intro"><Layers3 aria-hidden="true" /><span>场景资料</span><ArrowRight aria-hidden="true" /><span>巡礼地点</span><ArrowRight aria-hidden="true" /><span>游览区域</span><ArrowRight aria-hidden="true" /><span>日程</span></div>}
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
              <WorkspaceMap places={filteredPlaces} highlightedIds={highlightedIds} onSelect={selectMapPlace} />
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

        <aside className={`mix-pane mix-context ${activeStage === "context" ? "is-mobile-active" : ""}`} aria-label="行程信息与历史">
          <div className="mix-pane-title"><GitCompareArrows aria-hidden="true" /><div><strong>行程信息</strong><span>日期、版本与资料说明</span></div></div>
          {!workspace ? <p className="mix-muted">开始规划后，这里会显示日期、住宿、行程版本和资料说明。</p> : (
            <>
              <section className="mix-context-block"><h3><CalendarDays aria-hidden="true" />行程范围</h3><dl><div><dt>日期</dt><dd>{workspace.requirements.start_date ?? "未定"} — {workspace.requirements.end_date ?? "未定"}</dd></div><div><dt>作品</dt><dd>{workspace.confirmed_subjects.length} / {workspace.subject_groups.length} 已确认</dd></div><div><dt>住宿基点</dt><dd>{workspace.base_candidates.find((base) => base.base_id === workspace.selected_base_id)?.name ?? "待选择"}</dd></div></dl></section>
              <section className="mix-context-block"><h3><Clock3 aria-hidden="true" />修改记录</h3><ul className="mix-event-list">{workspace.diffs.slice().reverse().map((diff) => <li key={`${diff.from_version}-${diff.to_version}`}><span>行程版本 {diff.to_version}</span><small>{diff.changed_day_numbers.length ? `调整第 ${diff.changed_day_numbers.join("、")} 天` : "更新了行程要求"}</small></li>)}</ul>{workspace.diffs.length === 0 && <p className="mix-muted">还没有修改记录。</p>}</section>
              <section className="mix-context-block"><h3><GitCompareArrows aria-hidden="true" />行程版本</h3><ul className="mix-version-list">{workspace.itineraries.slice(0, 6).map((item) => <li key={item.itinerary_id}><strong>v{item.version}</strong><span>{strategyLabel(item.strategy)}</span><small>{item.days.reduce((total, day) => total + day.visits.length, 0)} 个地点{item.validation_issues.length ? ` · ${item.validation_issues.length} 项需调整` : " · 安排可行"}</small></li>)}</ul></section>
              <section className="mix-context-block"><button className="mix-disclosure" onClick={() => setShowEvidence((value) => !value)} aria-expanded={showEvidence}><Layers3 aria-hidden="true" />资料说明 <span>{workspace.counts.raw_scene_records}</span></button>{showEvidence && <div className="mix-evidence-summary"><p>已整理 {workspace.counts.raw_scene_records} 条场景资料，形成 {workspace.counts.canonical_places} 个巡礼地点。</p>{workspace.counts.quarantined_records > 0 && <p>{workspace.counts.quarantined_records} 条资料因位置不明确而未加入地图。</p>}<p>出发前请再次确认开放时间和现场规则。</p></div>}</section>
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
