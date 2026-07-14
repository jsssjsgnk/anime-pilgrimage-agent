import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpenCheck,
  Check,
  CircleHelp,
  Compass,
  Download,
  ExternalLink,
  Footprints,
  Map,
  MapPin,
  MessageSquareText,
  RefreshCcw,
  Route,
  ShieldCheck,
  TrainFront,
  Upload,
} from "lucide-react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createRouteMapOptions } from "./route-map-config";

interface Provenance {
  provider: string;
  source_url: string | null;
  fetched_at: string;
  status: string;
}

interface TripRequirements {
  origin: string | null;
  destination: string | null;
  start_date: string | null;
  end_date: string | null;
  anime_query: string | null;
  budget_level: "low" | "medium" | "high" | null;
  walking_preference: "low" | "medium" | "high" | null;
  max_walking_meters_per_day: number | null;
  origin_iata: string | null;
  destination_iata: string | null;
  adults: number;
  cabin_class: "economy" | "premium_economy" | "business" | "first";
  currency: string;
  must_visit_point_ids: string[];
  excluded_point_ids: string[];
}

interface SubjectCandidate {
  subject_id: string;
  name: string;
  name_cn: string | null;
  aliases: string[];
  score: number | null;
  provenance: Provenance;
}

interface Point {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  episode_refs: string[];
  confidence: string;
  source_label: string | null;
  provenance: Provenance;
}

interface RouteAResult {
  subject_id: string;
  points: Point[];
  is_complete: boolean;
  warnings: string[];
}

type ComparisonLabel = "recommended" | "fastest" | "cheapest" | "fewest_transfers";

interface AccessOption {
  option_id: string;
  mode: "flight" | "train" | "bus" | "manual";
  origin: string;
  destination: string;
  departure_at: string;
  arrival_at: string;
  price: number | null;
  currency: string | null;
  confirmation_url: string | null;
  comparison_labels: ComparisonLabel[];
  provenance: Provenance;
}

interface BaseCandidate {
  base_id: string;
  name: string;
  coordinate: { latitude: number; longitude: number };
  provenance: Provenance;
}

interface PlanningOptions {
  access_options: AccessOption[];
  base_candidates: BaseCandidate[];
  recommended_base_id: string;
  start_date: string;
  end_date: string;
}

interface ScheduledVisit {
  point_id: string;
  start_at: string;
  end_at: string;
  incoming_distance_meters: number;
}

interface DayPlan {
  date: string;
  visits: ScheduledVisit[];
  walking_distance_meters: number;
  maps_urls: string[];
}

interface RouteBPlan {
  base: BaseCandidate;
  days: DayPlan[];
  omitted_reasons: Record<string, { code: string; detail: string }>;
  matrix_status: "road" | "straight_line_estimate";
  access: { inbound: AccessOption; outbound: AccessOption } | null;
}

interface RetrievedEvidence {
  evidence_id: string;
  excerpt: string;
  title: string;
  source_url: string | null;
  authority_level: number;
  accessed_at: string;
  freshness: "current" | "unknown";
}

interface KnowledgeSearchResult {
  status: "sufficient_evidence" | "insufficient_evidence";
  evidence: RetrievedEvidence[];
  conflicts: { claim_key: string; evidence_ids: string[]; explanation: string }[];
  tool_calls_triggered: 0;
}

interface WeatherResult {
  available: boolean;
  reason: string | null;
  windows: {
    date: string;
    precipitation_probability_max: number | null;
    temperature_max_c: number | null;
  }[];
  provenance: Provenance;
}

interface WorkflowResponse {
  trip_id: string;
  thread_id: string;
  status: "waiting_confirmation" | "running" | "complete" | "partial" | "rejected";
  phase: string;
  pending_confirmation: { kind: "requirements" | "subject" | "access_and_base" } | null;
  revision_count: number;
  warnings: string[];
  requirements: TripRequirements | null;
  requirement_source: "provided" | "llm" | "deterministic_fallback" | null;
  requirement_assumptions: string[];
  effective_walking_limit: number | null;
  applied_preference_keys: string[];
  subject_candidates: SubjectCandidate[];
  confirmed_subject: { subject_id: string; name: string; name_cn: string | null } | null;
  route_a: RouteAResult | null;
  planning_options: PlanningOptions | null;
  route_b: RouteBPlan | null;
  weather: WeatherResult | null;
  knowledge: KnowledgeSearchResult | null;
  validation_issues: { code: string; detail: string }[];
  reviewer_explanation: string | null;
}

interface StoredPreference {
  preference_key: string;
  value: { value?: unknown };
}

interface ConversationAction {
  kind: "none" | "workflow_modified" | "confirmation_required" | "unsupported_change";
  target_day: number | null;
  revision_count: number | null;
}

interface ConversationMessage {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  intent: string;
  action: ConversationAction;
  created_at: string;
}

interface ConversationResponse {
  trip_id: string;
  messages: ConversationMessage[];
  assistant_message: ConversationMessage;
  workflow: WorkflowResponse;
}

const OWNER = "local-web-user";
const THREAD = "local-web-thread";
const TRIP_SESSION_KEY = "pilgrimage-current-trip";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const detail = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(detail?.detail ?? "无法读取已验证的数据，请重试或检查服务状态。");
  }
  return await response.json() as T;
}

function timeText(value: string | undefined): string {
  if (!value) return "未知";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Tokyo",
  }).format(new Date(value));
}

function modeText(mode: AccessOption["mode"]): string {
  return { flight: "航班", train: "铁路", bus: "巴士", manual: "人工交通" }[mode];
}

function labelText(label: ComparisonLabel): string {
  return {
    recommended: "推荐",
    fastest: "最快",
    cheapest: "最便宜",
    fewest_transfers: "最少换乘",
  }[label];
}

function statusText(status: string): string {
  return {
    live: "实时",
    cached: "缓存",
    estimated: "估算",
    community: "社区来源",
    needs_confirmation: "需确认",
  }[status] ?? status;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/gu, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character] ?? character);
}

function saveFile(filename: string, type: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function RouteMap({ points, routeName }: { points: Point[]; routeName: "Route A" | "Route B" }) {
  const container = useRef<HTMLDivElement>(null);
  const [styleStatus, setStyleStatus] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    if (!container.current || points.length === 0) return;
    setStyleStatus("loading");
    const bounds = new maplibregl.LngLatBounds();
    points.forEach((point) => bounds.extend([point.longitude, point.latitude]));
    const instance = new maplibregl.Map(createRouteMapOptions(container.current, bounds));
    let mounted = true;
    let styleReady = false;
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    instance.addControl(new maplibregl.FullscreenControl(), "top-right");
    instance.on("load", () => { styleReady = true; if (mounted) setStyleStatus("ready"); });
    instance.on("error", () => { if (mounted && !styleReady) setStyleStatus("unavailable"); });
    const markers = points.map((point, index) => {
      const markerElement = document.createElement("button");
      markerElement.type = "button";
      markerElement.className = "route-map-marker";
      markerElement.textContent = String(index + 1).padStart(2, "0");
      markerElement.title = point.name;
      markerElement.setAttribute("aria-label", `地图点位 ${index + 1}：${point.name}`);
      markerElement.setAttribute("aria-haspopup", "dialog");
      const popup = new maplibregl.Popup({ closeButton: false, offset: 28 })
        .setText(`${String(index + 1).padStart(2, "0")} · ${point.name}`);
      const marker = new maplibregl.Marker({ element: markerElement, anchor: "center" })
        .setLngLat([point.longitude, point.latitude]).setPopup(popup);
      markerElement.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          marker.togglePopup();
        }
      });
      return marker.addTo(instance);
    });
    return () => { mounted = false; markers.forEach((marker) => marker.remove()); instance.remove(); };
  }, [points, routeName]);

  return <div className="route-map-shell">
    <div ref={container} className="route-map" role="region"
      aria-label={`${routeName} 交互式地图，共 ${points.length} 个点；可缩放和拖动，点位详情见相邻列表`}
      data-map-provider="OpenFreeMap" data-map-status={styleStatus} />
    {styleStatus !== "ready" && <p className={styleStatus === "unavailable" ? "map-status map-status-error" : "map-status"} role="status">
      {styleStatus === "unavailable" ? "底图暂时不可用；编号点位和列表仍可使用。" : "正在加载 OpenStreetMap 底图…"}
    </p>}
  </div>;
}

export function App() {
  const queryClient = useQueryClient();
  const [request, setRequest] = useState("我从京都出发，九月去东京三天，想巡礼《孤独摇滚！》，预算中等，希望少走路。");
  const [submitted, setSubmitted] = useState(false);
  const [workflow, setWorkflow] = useState<WorkflowResponse | null>(null);
  const [draft, setDraft] = useState<TripRequirements | null>(null);
  const [inboundId, setInboundId] = useState<string | null>(null);
  const [outboundId, setOutboundId] = useState<string | null>(null);
  const [baseId, setBaseId] = useState<string | null>(null);
  const [modification, setModification] = useState("第二天少走 30%, 并保留其他天安排");
  const [mapMode, setMapMode] = useState<"Route A" | "Route B">("Route A");
  const [applyPreferences, setApplyPreferences] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [tripId, setTripId] = useState<string | null>(() => (
    typeof window === "undefined" ? null : window.sessionStorage.getItem(TRIP_SESSION_KEY)
  ));

  const preferences = useQuery({
    queryKey: ["preferences", OWNER],
    queryFn: () => fetchJson<StoredPreference[]>(`/api/preferences?owner_user_id=${OWNER}`),
  });

  const acceptWorkflow = useCallback((result: WorkflowResponse) => {
    setWorkflow(result);
    setTripId(result.trip_id);
    setSubmitted(true);
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(TRIP_SESSION_KEY, result.trip_id);
    }
    if (result.requirements) setDraft(result.requirements);
    if (result.planning_options) {
      const requirements = result.requirements;
      const inbound = result.planning_options.access_options.find((item) => item.origin === requirements?.origin);
      const outbound = result.planning_options.access_options.find((item) => item.origin === requirements?.destination);
      setInboundId((current) => current ?? inbound?.option_id ?? null);
      setOutboundId((current) => current ?? outbound?.option_id ?? null);
      setBaseId((current) => current ?? result.planning_options?.recommended_base_id ?? null);
    }
  }, []);

  const recoveredWorkflow = useQuery({
    queryKey: ["workflow", tripId],
    queryFn: () => fetchJson<WorkflowResponse>(
      `/api/workflows/${tripId ?? ""}?owner_user_id=${OWNER}&thread_id=${THREAD}`,
    ),
    enabled: Boolean(tripId) && workflow === null,
    retry: false,
  });

  useEffect(() => {
    if (recoveredWorkflow.data) acceptWorkflow(recoveredWorkflow.data);
  }, [acceptWorkflow, recoveredWorkflow.data]);

  useEffect(() => {
    if (!recoveredWorkflow.error) return;
    window.sessionStorage.removeItem(TRIP_SESSION_KEY);
    setTripId(null);
  }, [recoveredWorkflow.error]);

  const startMutation = useMutation({
    mutationFn: () => fetchJson<WorkflowResponse>("/api/workflows", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ owner_user_id: OWNER, thread_id: THREAD, request_summary: request, apply_saved_preferences: applyPreferences }),
    }),
    onSuccess: acceptWorkflow,
  });
  const resumeMutation = useMutation({
    mutationFn: (decision: Record<string, unknown>) => fetchJson<WorkflowResponse>(`/api/workflows/${workflow?.trip_id ?? ""}/resume`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ owner_user_id: OWNER, thread_id: THREAD, decision }),
    }),
    onSuccess: acceptWorkflow,
  });
  const modifyMutation = useMutation({
    mutationFn: () => fetchJson<WorkflowResponse>(`/api/workflows/${workflow?.trip_id ?? ""}/modify`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ owner_user_id: OWNER, thread_id: THREAD, instruction: modification }),
    }),
    onSuccess: acceptWorkflow,
  });
  const messages = useQuery({
    queryKey: ["conversation", workflow?.trip_id],
    queryFn: () => fetchJson<ConversationMessage[]>(
      `/api/workflows/${workflow?.trip_id ?? ""}/messages?owner_user_id=${OWNER}&thread_id=${THREAD}`,
    ),
    enabled: Boolean(workflow?.trip_id),
    retry: false,
  });
  const chatMutation = useMutation({
    mutationFn: (message: string) => fetchJson<ConversationResponse>(
      `/api/workflows/${workflow?.trip_id ?? ""}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ owner_user_id: OWNER, thread_id: THREAD, message }),
      },
    ),
    onSuccess: (result) => {
      acceptWorkflow(result.workflow);
      queryClient.setQueryData(
        ["conversation", result.trip_id],
        result.messages,
      );
      setChatInput("");
    },
  });
  const preferenceMutation = useMutation({
    mutationFn: (value: number) => fetchJson(`/api/preferences/max_walking_meters_per_day`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ owner_user_id: OWNER, value, explicit_consent: true }),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["preferences", OWNER] }),
  });
  const deletePreferences = useMutation({
    mutationFn: () => fetchJson(`/api/preferences?owner_user_id=${OWNER}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["preferences", OWNER] }),
  });
  const uploadMutation = useMutation({
    mutationFn: async (file: File) => fetchJson("/api/knowledge/documents", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        owner_user_id: OWNER, scope: "trip", trip_id: workflow?.trip_id,
        title: file.name, filename: file.name,
        media_type: file.type === "text/markdown" ? "text/markdown" : "text/plain",
        content: await file.text(), content_is_base64: false, source_type: "user_note",
        authority_level: 1, language: "und", accessed_at: new Date().toISOString().slice(0, 10),
      }),
    }),
  });

  const routeA = workflow?.route_a ?? null;
  const plan = workflow?.route_b ?? null;
  const selectedIds = useMemo(() => new Set(plan?.days.flatMap((day) => day.visits.map((visit) => visit.point_id)) ?? []), [plan]);
  const mapPoints = routeA?.points.filter((point) => mapMode === "Route A" || selectedIds.has(point.id)) ?? [];
  const activeStage = plan ? 4 : workflow?.planning_options ? 2 : workflow?.subject_candidates.length ? 1 : submitted ? 0 : 0;
  const busy = startMutation.isPending || resumeMutation.isPending
    || modifyMutation.isPending || chatMutation.isPending;
  const error = startMutation.error ?? resumeMutation.error ?? modifyMutation.error
    ?? chatMutation.error;

  const beginWorkflow = () => {
    setSubmitted(true);
    setWorkflow(null);
    setDraft(null);
    setTripId(null);
    window.sessionStorage.removeItem(TRIP_SESSION_KEY);
    startMutation.mutate();
  };

  const sendChat = (message: string) => {
    const normalized = message.trim();
    if (!normalized || !workflow) return;
    chatMutation.mutate(normalized);
  };

  const updateDraft = <K extends keyof TripRequirements>(key: K, value: TripRequirements[K]) => {
    setDraft((current) => current ? { ...current, [key]: value } : current);
  };
  const togglePoint = (kind: "must_visit_point_ids" | "excluded_point_ids", pointId: string) => {
    if (!draft) return;
    const opposite = kind === "must_visit_point_ids" ? "excluded_point_ids" : "must_visit_point_ids";
    const current = new Set(draft[kind]);
    if (current.has(pointId)) current.delete(pointId); else current.add(pointId);
    setDraft({ ...draft, [kind]: [...current], [opposite]: draft[opposite].filter((id) => id !== pointId) });
  };

  const exportPlan = (format: "json" | "geojson" | "html") => {
    if (!plan || !routeA || !workflow) return;
    const exportData = {
      schema_version: "1", plan_version: workflow.revision_count + 1,
      subject_id: workflow.confirmed_subject?.subject_id, generated_at: new Date().toISOString(),
      route_a_point_ids: routeA.points.map((point) => point.id), route_b: plan,
      evidence_ids: workflow.knowledge?.evidence.map((item) => item.evidence_id) ?? [],
      reconfirm_before_departure: ["transport", "weather", "opening and photography rules"],
    };
    if (format === "json") return saveFile("pilgrimage-plan.json", "application/json", JSON.stringify(exportData, null, 2));
    if (format === "geojson") {
      const geojson = { type: "FeatureCollection", schema_version: "1", features: routeA.points.filter((point) => selectedIds.has(point.id)).map((point) => ({
        type: "Feature", geometry: { type: "Point", coordinates: [point.longitude, point.latitude] },
        properties: { id: point.id, name: point.name, source_url: point.provenance.source_url },
      })) };
      return saveFile("pilgrimage-route.geojson", "application/geo+json", JSON.stringify(geojson, null, 2));
    }
    const dayHtml = plan.days.map((day) => `<section><h2>${escapeHtml(day.date)}</h2><p>${(day.walking_distance_meters / 1000).toFixed(1)} km estimated walking</p><ol>${day.visits.map((visit) => `<li>${escapeHtml(timeText(visit.start_at))} — ${escapeHtml(routeA.points.find((point) => point.id === visit.point_id)?.name ?? "Unknown")}</li>`).join("")}</ol></section>`).join("");
    return saveFile("pilgrimage-plan.html", "text/html", `<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>Pilgrimage Plan</title></head><body><h1>Pilgrimage Plan</h1><p>Read-only. Reconfirm all live conditions.</p>${dayHtml}</body></html>`);
  };

  const stages = [
    { label: "说出想法", icon: MessageSquareText }, { label: "确认作品", icon: Check },
    { label: "选择交通", icon: Compass }, { label: "生成路线", icon: Route },
    { label: "修改与导出", icon: Download },
  ];

  return <div className="app-shell">
    <a className="skip-link" href="#planner">跳到规划区</a>
    <header className="topbar">
      <a className="brand" href="/" aria-label="Pilgrimage Atlas 首页"><span className="brand-mark"><Map size={22} /></span><span><strong>Pilgrimage Atlas</strong><small>可验证的动漫巡礼计划</small></span></a>
      <div className="safety-note"><ShieldCheck size={18} /><span>只读规划 · 不预订 · 不付款</span></div>
    </header>
    <main id="planner" className="planner" tabIndex={-1}>
      <section className="intro" aria-labelledby="intro-title"><p className="eyebrow">从灵感到可执行路线</p><h1 id="intro-title">把想去的场景，整理成真正走得完的旅程。</h1><p className="lede">主流程由可恢复 Agent 驱动。Bangumi 确认作品，Anitabi 读取可用候选点并核对完整性，MCP 只提供九个只读工具。</p></section>
      <nav className="stage-nav" aria-label="规划进度"><ol>{stages.map(({ label, icon: Icon }, index) => <li key={label} className={index === activeStage ? "active" : index < activeStage ? "complete" : "upcoming"}><span className="stage-icon"><Icon size={18} /></span><span><small>0{index + 1}</small>{label}</span></li>)}</ol></nav>

      <div className="workspace">
        <section className="request-card" aria-labelledby="request-title"><div className="section-heading"><div><p className="eyebrow">开放式输入</p><h2 id="request-title">你想怎样巡礼？</h2></div><CircleHelp size={20} /></div>
          <form onSubmit={(event) => { event.preventDefault(); beginWorkflow(); }}>
            <label htmlFor="trip-request">旅行想法</label><textarea id="trip-request" rows={6} value={request} onChange={(event) => { setRequest(event.target.value); setSubmitted(false); }} />
            <p className="helper-text">建议写明出发地、目的地、日期、作品、预算与步行偏好。抽取结果必须由你确认。</p>
            <label className="inline-check"><input type="checkbox" checked={applyPreferences} onChange={(event) => setApplyPreferences(event.target.checked)} />本次应用已保存偏好（可在条件卡覆盖）</label>
            <button className="primary-button" type="submit" disabled={!request.trim() || busy}>整理旅行条件<ArrowRight size={19} /></button>
            <p className="submit-status" aria-live="polite">{submitted ? "已收到。不会静默确认关键选择；请检查并确认条件卡。" : ""}</p>
          </form>
        </section>
        <aside className="principles" aria-labelledby="principles-title"><div className="atlas-grid" /><p className="eyebrow">项目记忆 · 默认关闭</p><h2 id="principles-title">偏好由你控制。</h2>
          <p>{preferences.data?.length ? `已保存 ${preferences.data.length} 项；仅在勾选时应用。` : "没有长期偏好。"}</p>
          <button className="export-button" type="button" onClick={() => preferenceMutation.mutate(draft?.max_walking_meters_per_day ?? 5000)}>明确同意并保存当前步行上限</button>
          <button className="export-button" type="button" onClick={() => deletePreferences.mutate()}>删除全部长期偏好</button>
        </aside>
      </div>

      {error && <section className="error-state" role="alert"><strong>这一步没有完成：</strong> {error.message}<button type="button" onClick={() => startMutation.mutate()}>重试安全读取</button></section>}

      {workflow?.status === "partial" && <section className="recovery-state" role="status">
        <div><p className="eyebrow">已保留当前可用数据</p><h2>规划停在可恢复状态</h2><p>阶段：{workflow.phase}。不会用猜测补齐缺失结果。</p></div>
        {workflow.warnings.map((item) => <p className="unknown-state" key={item}>{item}</p>)}
        <button className="secondary-button" type="button" disabled={busy} onClick={() => startMutation.mutate()}>从当前输入重新安全读取</button>
      </section>}

      {workflow && <section className="conversation-panel" aria-labelledby="conversation-title">
        <div className="results-heading"><div><p className="eyebrow">行程级持续上下文</p><h2 id="conversation-title">和规划 Agent 继续聊</h2></div><span className="source-chip verified">已持久化 · 可恢复</span></div>
        <p className="section-intro">可以追问安排原因、点位完整度、天气和证据，也可以直接说“第二天少走 30%”。关键确认不会在聊天中被静默代替。</p>
        <div className="conversation-prompts" aria-label="对话建议">
          {["现在还缺什么？", "为什么这样安排？", "点位数据完整吗？"].map((prompt) => <button key={prompt} type="button" disabled={busy} onClick={() => sendChat(prompt)}>{prompt}</button>)}
        </div>
        <div className="conversation-log" role="log" aria-live="polite" aria-label="行程对话记录">
          {messages.isLoading && <p className="helper-text">正在恢复对话…</p>}
          {messages.data?.map((message) => <article className={`conversation-message ${message.role}`} key={message.message_id}>
            <header><strong>{message.role === "assistant" ? "规划 Agent" : "你"}</strong><small>{new Date(message.created_at).toLocaleString("zh-CN")}</small></header>
            <p>{message.content}</p>
            {message.action.kind === "workflow_modified" && <span className="conversation-action">已更新计划 · 第 {message.action.target_day} 天 · 修订 {message.action.revision_count}/3</span>}
            {message.action.kind === "confirmation_required" && <span className="conversation-action pending">等待你在卡片中明确确认</span>}
          </article>)}
        </div>
        <form className="conversation-form" onSubmit={(event) => { event.preventDefault(); sendChat(chatInput); }}>
          <label htmlFor="conversation-input">继续询问或提出修改</label>
          <div><textarea id="conversation-input" rows={3} maxLength={2000} value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder="例如：为什么第二天这样排？或：第二天少走 30%" /><button className="primary-button" type="submit" disabled={busy || !chatInput.trim()}>发送<MessageSquareText size={18} /></button></div>
        </form>
      </section>}

      {workflow?.pending_confirmation?.kind === "requirements" && draft && <section className="results-section" aria-labelledby="requirements-title">
        <div className="results-heading"><div><p className="eyebrow">可编辑条件卡 · {workflow.requirement_source === "llm" ? "LLM 严格抽取" : "本地保守抽取"}</p><h2 id="requirements-title">确认所有关键旅行条件</h2></div><span className="source-chip">必须显式确认</span></div>
        {workflow.requirement_assumptions.map((item) => <p className="unknown-state" key={item}>{item}</p>)}
        {workflow.applied_preference_keys.length > 0 && <p className="route-note">本次已应用偏好：{workflow.applied_preference_keys.join("、")}。修改下方字段即可仅覆盖本次。</p>}
        <div className="condition-grid">
          <label>出发地<input value={draft.origin ?? ""} onChange={(event) => updateDraft("origin", event.target.value || null)} /></label>
          <label>目的地<input value={draft.destination ?? ""} onChange={(event) => updateDraft("destination", event.target.value || null)} /></label>
          <label>开始日期<input type="date" value={draft.start_date ?? ""} onChange={(event) => updateDraft("start_date", event.target.value || null)} /></label>
          <label>结束日期<input type="date" value={draft.end_date ?? ""} onChange={(event) => updateDraft("end_date", event.target.value || null)} /></label>
          <label>作品<input value={draft.anime_query ?? ""} onChange={(event) => updateDraft("anime_query", event.target.value || null)} /></label>
          <label>每日步行上限（米）<input type="number" min={500} max={50000} value={draft.max_walking_meters_per_day ?? 5000} onChange={(event) => updateDraft("max_walking_meters_per_day", Number(event.target.value))} /></label>
          <label>出发机场代码（可选）<input maxLength={3} value={draft.origin_iata ?? ""} onChange={(event) => updateDraft("origin_iata", event.target.value.toUpperCase() || null)} /></label>
          <label>目的机场代码（可选）<input maxLength={3} value={draft.destination_iata ?? ""} onChange={(event) => updateDraft("destination_iata", event.target.value.toUpperCase() || null)} /></label>
        </div>
        <button className="primary-button" type="button" disabled={busy} onClick={() => resumeMutation.mutate({ decision: "accept", requirements: draft })}>确认条件并查询 Bangumi<ArrowRight size={19} /></button>
      </section>}

      {workflow?.subject_candidates.length ? <section className="results-section" aria-labelledby="subjects-title"><div className="results-heading"><div><p className="eyebrow">Bangumi 只读候选</p><h2 id="subjects-title">确认你要巡礼的作品</h2></div><span className="source-chip">查询结果 · 需确认</span></div>
        <div className="candidate-grid">{workflow.subject_candidates.map((candidate) => <article key={candidate.subject_id} className={workflow.confirmed_subject?.subject_id === candidate.subject_id ? "candidate-card selected" : "candidate-card"}><div><span className="subject-id">Bangumi #{candidate.subject_id}</span><h3>{candidate.name_cn ?? candidate.name}</h3><p>{candidate.name}{candidate.aliases.length ? ` · ${candidate.aliases.join(" / ")}` : ""}</p></div><button className="secondary-button" type="button" aria-pressed={workflow.confirmed_subject?.subject_id === candidate.subject_id} disabled={busy || Boolean(workflow.confirmed_subject)} onClick={() => resumeMutation.mutate({ decision: "accept", selected_subject_id: candidate.subject_id })}>{workflow.confirmed_subject?.subject_id === candidate.subject_id ? <><Check size={18} />已确认此作品</> : "确认并查看 Route A"}</button></article>)}</div>
      </section> : null}

      {routeA && <section className="route-section" aria-labelledby="route-a-title"><div className="results-heading"><div><p className="eyebrow">Anitabi 官方 Open API</p><h2 id="route-a-title">Route A · {routeA.points.length} 个有来源点位</h2></div><span className={routeA.is_complete ? "source-chip verified" : "source-chip"}>{routeA.is_complete ? "官方详情返回完整" : "部分数据 · 不宣称完整"}</span></div>
        <div className="map-mode-switch" role="group" aria-label="路线地图切换"><button type="button" aria-pressed={mapMode === "Route A"} onClick={() => setMapMode("Route A")}>Route A 全部候选</button><button type="button" disabled={!plan} aria-pressed={mapMode === "Route B"} onClick={() => setMapMode("Route B")}>Route B 已选子集</button></div>
        <div className="source-legend"><span>Anitabi / 原始投稿来源</span><span>Route B 仅取自 Route A</span><span>社区点位出发前复核</span></div>
        <div className="route-layout"><RouteMap points={mapPoints} routeName={mapMode} /><ol className="point-list">{routeA.points.map((point, index) => <li key={point.id}><span className="point-index"><MapPin size={16} />{String(index + 1).padStart(2, "0")}</span><div><strong>{point.name}</strong><small>{point.episode_refs.join(" · ") || "集数待确认"} · {point.source_label ?? point.confidence}</small><small>{statusText(point.provenance.status)} · {new Date(point.provenance.fetched_at).toLocaleString("zh-CN")}</small><label><input type="checkbox" checked={draft?.must_visit_point_ids.includes(point.id) ?? false} onChange={() => togglePoint("must_visit_point_ids", point.id)} />必去</label><label><input type="checkbox" checked={draft?.excluded_point_ids.includes(point.id) ?? false} onChange={() => togglePoint("excluded_point_ids", point.id)} />排除</label></div>{point.provenance.source_url && <a href={point.provenance.source_url} target="_blank" rel="noreferrer" aria-label={`${point.name} 来源`}><ExternalLink size={17} /></a>}</li>)}</ol></div>
        <p className="route-note">完整性按 Anitabi `/lite` 的总数与 `/points/detail` 返回量核对。若接口失败并降级到合法导入，页面会明确显示“部分数据”。</p>
      </section>}

      {workflow?.planning_options && draft && !plan && <section className="access-section" aria-labelledby="access-title"><div className="results-heading"><div><p className="eyebrow">Access / Base Plan</p><h2 id="access-title">选择抵离交通与住宿基地</h2></div><span className="source-chip">航班与人工候选并列 · 不预订</span></div><p className="section-intro">价格、班次和人工时间都必须复核；未知价格不会被填造。</p>
        <div className="selection-layout">{(["inbound", "outbound"] as const).map((direction) => {
          const origin = direction === "inbound" ? draft.origin : draft.destination;
          const selected = direction === "inbound" ? inboundId : outboundId;
          return <fieldset className="selection-group" key={direction}><legend>{direction === "inbound" ? "去程" : "返程"} · {origin}</legend>{workflow.planning_options?.access_options.filter((option) => option.origin === origin).map((option) => <button key={option.option_id} className={selected === option.option_id ? "option-card selected" : "option-card"} type="button" role="radio" aria-label={`选择${direction === "inbound" ? "去程" : "返程"} ${modeText(option.mode)}`} aria-checked={selected === option.option_id} onClick={() => direction === "inbound" ? setInboundId(option.option_id) : setOutboundId(option.option_id)}><span className="option-icon"><TrainFront size={19} /></span><span><strong>{modeText(option.mode)} {option.comparison_labels.map(labelText).join(" · ")}</strong><small>{timeText(option.departure_at)} → {timeText(option.arrival_at)} · {option.price === null ? "价格未知 · 需确认" : `${option.price.toLocaleString("zh-CN")} ${option.currency}`}</small><small>{statusText(option.provenance.status)} · {new Date(option.provenance.fetched_at).toLocaleString("zh-CN")}</small></span><Check size={18} className="option-check" /></button>)}</fieldset>;
        })}<fieldset className="selection-group"><legend>住宿基地</legend>{workflow.planning_options.base_candidates.map((candidate) => <button key={candidate.base_id} className={baseId === candidate.base_id ? "option-card selected" : "option-card"} type="button" role="radio" aria-label={`选择基地 ${candidate.name}`} aria-checked={baseId === candidate.base_id} onClick={() => setBaseId(candidate.base_id)}><span className="option-icon"><MapPin size={19} /></span><span><strong>{candidate.name}</strong><small>{candidate.base_id === workflow.planning_options?.recommended_base_id ? "按 Route A 距离推荐" : "可选中心基地"}</small></span><Check size={18} className="option-check" /></button>)}</fieldset></div>
        <div className="planning-action"><label><Footprints size={18} />每日步行上限 {((draft.max_walking_meters_per_day ?? 5000) / 1000).toFixed(1)} km</label><button className="primary-button" type="button" disabled={!inboundId || !outboundId || !baseId || busy} onClick={() => resumeMutation.mutate({ decision: "accept", inbound_option_id: inboundId, outbound_option_id: outboundId, base_id: baseId, requirements: draft })}>{busy ? "正在验证约束…" : "生成可执行 Route B"}<ArrowRight size={19} /></button></div>
      </section>}

      {plan && routeA && workflow && <section className="timeline-section" role="region" aria-label="Route B · 三日可执行时间轴" aria-labelledby="timeline-title"><div className="results-heading"><div><p className="eyebrow">确定性验证完成 · 计划版本 {workflow.revision_count + 1}</p><h2 id="timeline-title">Route B · 三日可执行时间轴</h2></div><span className="source-chip verified">{plan.matrix_status === "road" ? "ORS 道路估算" : "直线估算 · 已降级"}</span></div>
        <div className="trip-summary"><div><TrainFront size={20} /><span><small>抵达</small><strong>{timeText(plan.access?.inbound.arrival_at)}</strong></span></div><div><MapPin size={20} /><span><small>基地</small><strong>{plan.base.name}</strong></span></div><div><Footprints size={20} /><span><small>有效日上限</small><strong>{((workflow.effective_walking_limit ?? draft?.max_walking_meters_per_day ?? 5000) / 1000).toFixed(1)} km</strong></span></div></div>
        {workflow.weather && <div className="source-legend"><span>天气：{workflow.weather.available ? "可用" : `未知 · ${workflow.weather.reason ?? "超出预报范围"}`}</span>{workflow.weather.windows.map((window) => <span key={window.date}>{window.date} · 降雨 {window.precipitation_probability_max ?? "?"}%</span>)}</div>}
        <div className="timeline-grid">{plan.days.map((day, dayIndex) => <article key={day.date} className="day-card"><header><span>DAY {String(dayIndex + 1).padStart(2, "0")}</span><div><strong>{day.date}</strong><small>{(day.walking_distance_meters / 1000).toFixed(1)} km 步行估算</small></div></header>{day.visits.length ? <ol>{day.visits.map((visit) => { const point = routeA.points.find((item) => item.id === visit.point_id); return <li key={visit.point_id}><time>{timeText(visit.start_at)}</time><span><strong>{point?.name ?? "未知点位"}</strong><small>抵达段 {(visit.incoming_distance_meters / 1000).toFixed(1)} km</small></span></li>; })}</ol> : <p className="rest-day">抵离缓冲日 · 未安排巡礼点</p>}<footer>{day.maps_urls.map((url, index) => <a key={url} href={url} target="_blank" rel="noreferrer">现场导航 {index + 1}<ExternalLink size={15} /></a>)}</footer></article>)}</div>
        {Object.entries(plan.omitted_reasons).length > 0 && <section className="evidence-panel"><h3>未纳入 Route B 的点</h3><ul>{Object.entries(plan.omitted_reasons).map(([pointId, reason]) => <li key={pointId}><strong>{routeA.points.find((point) => point.id === pointId)?.name ?? pointId}</strong> · {reason.code} · {reason.detail}</li>)}</ul></section>}
        {(workflow.warnings.length > 0 || workflow.validation_issues.length > 0 || workflow.reviewer_explanation) && <section className="evidence-panel"><h3>验证与 Reviewer 说明</h3>{workflow.reviewer_explanation && <p>{workflow.reviewer_explanation}</p>}{workflow.warnings.map((item) => <p className="unknown-state" key={item}>{item}</p>)}{workflow.validation_issues.map((item) => <p className="error-state" key={`${item.code}-${item.detail}`}>{item.code} · {item.detail}</p>)}</section>}
        <div className="revision-export-grid"><form className="revision-card" onSubmit={(event) => { event.preventDefault(); modifyMutation.mutate(); }}><div><p className="eyebrow">自然语言局部修改</p><h3>只重算受影响日期</h3></div><label htmlFor="plan-modification">修改要求</label><textarea id="plan-modification" rows={3} value={modification} onChange={(event) => setModification(event.target.value)} /><button className="secondary-button" type="submit" disabled={busy || workflow.revision_count >= 3}><RefreshCcw size={17} />应用为版本 {workflow.revision_count + 2}</button><p className="helper-text">“第二天少走 30%”会真实减少该日路线；第 1、3 天保持稳定。最多三轮。</p></form><section className="export-card"><p className="eyebrow">可移交成果</p><h3>导出独立计划</h3><button className="export-button" type="button" onClick={() => exportPlan("json")}><Download size={17} />导出 JSON</button><button className="export-button" type="button" onClick={() => exportPlan("geojson")}><Map size={17} />导出 GeoJSON</button><button className="export-button" type="button" onClick={() => exportPlan("html")}><BookOpenCheck size={17} />打印 HTML</button></section></div>
        <section className="evidence-panel" aria-labelledby="evidence-title"><div className="results-heading"><div><p className="eyebrow">项目 RAG · 动态命名空间检索</p><h3 id="evidence-title">访问与礼仪依据</h3></div><label className="export-button"><Upload size={16} />上传本次 Markdown/TXT<input className="visually-hidden" type="file" accept="text/plain,text/markdown,.md,.txt" onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadMutation.mutate(file); }} /></label></div>
          {workflow.knowledge?.status === "insufficient_evidence" && <p className="unknown-state">没有足够来源，未生成访问规则。请以上传资料和场所当日公告为准。</p>}
          {workflow.knowledge?.conflicts.map((conflict) => <p className="error-state" key={conflict.claim_key}><strong>证据冲突：</strong>{conflict.explanation}（{conflict.evidence_ids.join("、")}）</p>)}
          <div className="evidence-list">{workflow.knowledge?.evidence.map((item) => <article key={item.evidence_id}><div><span>{item.evidence_id}</span><strong>{item.title}</strong></div><p>{item.excerpt}</p><footer><small>权威 {item.authority_level}/5 · 访问 {item.accessed_at} · {item.freshness === "current" ? "当前有效" : "时效未知，需确认"}</small>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">查看来源<ExternalLink size={14} /></a>}</footer></article>)}</div>
        </section>
      </section>}
    </main>
  </div>;
}
