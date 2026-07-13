import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Check,
  CircleHelp,
  Compass,
  BookOpenCheck,
  Download,
  Footprints,
  ExternalLink,
  Map,
  MapPin,
  MessageSquareText,
  Route,
  RefreshCcw,
  ShieldCheck,
  TrainFront,
} from "lucide-react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";

interface Provenance {
  provider: string;
  source_url: string | null;
  fetched_at: string;
  status: string;
}

interface SubjectCandidate {
  subject_id: string;
  name: string;
  name_cn: string | null;
  aliases: string[];
  score: number | null;
  provenance: Provenance;
}

interface SubjectSearchResult {
  candidates: SubjectCandidate[];
}

interface Point {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  episode_refs: string[];
  confidence: string;
  provenance: Provenance;
}

interface RouteAResult {
  subject_id: string;
  points: Point[];
  is_complete: boolean;
  warnings: string[];
}

interface AccessOption {
  option_id: string;
  mode: "flight" | "train" | "bus" | "manual";
  origin: string;
  destination: string;
  departure_at: string;
  arrival_at: string;
  price: number | null;
  currency: string | null;
  provenance: Provenance;
}

interface BaseCandidate {
  base_id: string;
  name: string;
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
  tool_calls_triggered: 0;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error("无法读取已验证的数据，请稍后重试。");
  return (await response.json()) as T;
}

function animeFromRequest(request: string): string {
  return request.match(/[《「](.*?)[》」]/u)?.[1]?.trim() || request.trim();
}

function timeText(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Tokyo",
  }).format(new Date(value));
}

function modeText(mode: AccessOption["mode"]): string {
  return { flight: "航班", train: "新干线", bus: "夜行巴士", manual: "人工候选" }[mode];
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

function RouteMap({ points }: { points: Point[] }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!container.current || points.length === 0) return;
    const bounds = new maplibregl.LngLatBounds();
    points.forEach((point) => bounds.extend([point.longitude, point.latitude]));
    const instance = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: "canvas", type: "background", paint: { "background-color": "#e7eee8" } }],
      },
      bounds,
      fitBoundsOptions: { padding: 56, maxZoom: 15 },
      attributionControl: false,
      interactive: false,
    });
    instance.on("load", () => {
      instance.addSource("route-a", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: points.map((point) => ({
            type: "Feature",
            geometry: { type: "Point", coordinates: [point.longitude, point.latitude] },
            properties: { name: point.name },
          })),
        },
      });
      instance.addLayer({
        id: "route-a-points",
        type: "circle",
        source: "route-a",
        paint: {
          "circle-radius": 9,
          "circle-color": "#b93625",
          "circle-stroke-color": "#fffdf8",
          "circle-stroke-width": 3,
        },
      });
    });
    map.current = instance;
    return () => {
      instance.remove();
      map.current = null;
    };
  }, [points]);

  return <div ref={container} className="route-map" aria-label={`Route A 地图，共 ${points.length} 个点`} />;
}

export function App() {
  const [request, setRequest] = useState(
    "我从京都出发，九月去东京三天，想巡礼《孤独摇滚！》，预算中等，希望少走路。",
  );
  const [submitted, setSubmitted] = useState(false);
  const [confirmedId, setConfirmedId] = useState<string | null>(null);
  const [inboundId, setInboundId] = useState<string | null>(null);
  const [outboundId, setOutboundId] = useState<string | null>(null);
  const [baseId, setBaseId] = useState<string | null>(null);
  const [walkingLimit, setWalkingLimit] = useState(5_000);
  const [modification, setModification] = useState("第二天少走路，并保留其他天安排");
  const [planVersion, setPlanVersion] = useState(1);
  const [displayedPlan, setDisplayedPlan] = useState<RouteBPlan | null>(null);
  const [dayTwoWalkingLimit, setDayTwoWalkingLimit] = useState<number | null>(null);

  const subjectQuery = useQuery({
    queryKey: ["subjects", animeFromRequest(request)],
    queryFn: () =>
      fetchJson<SubjectSearchResult>(
        `/api/subjects/search?query=${encodeURIComponent(animeFromRequest(request))}&limit=5`,
      ),
    enabled: submitted,
  });
  const routeQuery = useQuery({
    queryKey: ["route-a", confirmedId],
    queryFn: () => fetchJson<RouteAResult>(`/api/subjects/${confirmedId ?? ""}/route-a`),
    enabled: confirmedId !== null,
  });
  const planningQuery = useQuery({
    queryKey: ["planning-options"],
    queryFn: () => fetchJson<PlanningOptions>("/api/planning/options"),
    enabled: confirmedId !== null,
  });
  const routeBMutation = useMutation({
    mutationFn: ({ limit }: { limit: number; localDay?: number }) =>
      fetchJson<RouteBPlan>(`/api/subjects/${confirmedId ?? ""}/route-b`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          inbound_option_id: inboundId,
          outbound_option_id: outboundId,
          base_id: baseId,
          max_walking_meters_per_day: limit,
          must_visit_point_ids: [],
          excluded_point_ids: [],
        }),
      }),
    onSuccess: (nextPlan, variables) => {
      if (variables.localDay === 2) {
        setDisplayedPlan((currentPlan) => {
          if (!currentPlan) return nextPlan;
          return {
            ...currentPlan,
            days: currentPlan.days.map((day, index) =>
              index === 1 ? (nextPlan.days[index] ?? day) : day,
            ),
          };
        });
        setDayTwoWalkingLimit(variables.limit);
        setPlanVersion((version) => version + 1);
        return;
      }
      setDisplayedPlan(nextPlan);
      setDayTwoWalkingLimit(null);
      setPlanVersion(1);
    },
  });
  const evidenceQuery = useQuery({
    queryKey: ["knowledge", confirmedId, displayedPlan?.base.base_id],
    queryFn: () =>
      fetchJson<KnowledgeSearchResult>("/api/knowledge/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          owner_user_id: "demo-user",
          question: "Shimokitazawa venue photography rules and neighborhood visit guidance",
          subject_ids: [confirmedId],
          aliases: ["孤独摇滚", "Bocchi the Rock"],
          location_tags: ["Shimokitazawa", "Tokyo"],
          top_k: 3,
        }),
      }),
    enabled: Boolean(displayedPlan),
  });

  const resetRouteB = () => {
    routeBMutation.reset();
    setDisplayedPlan(null);
    setDayTwoWalkingLimit(null);
    setPlanVersion(1);
  };

  const confirmCandidate = async (subjectId: string) => {
    await fetchJson(`/api/subjects/${subjectId}/confirm`, { method: "POST" });
    resetRouteB();
    setInboundId(null);
    setOutboundId(null);
    setBaseId(null);
    setConfirmedId(subjectId);
  };

  const activeStage = displayedPlan ? 4 : confirmedId ? 2 : submitted ? 1 : 0;
  const stages = [
    { label: "说出想法", icon: MessageSquareText },
    { label: "确认作品", icon: Check },
    { label: "选择交通", icon: Compass },
    { label: "生成路线", icon: Route },
    { label: "修改与导出", icon: Download },
  ];

  const applyModification = () => {
    const nextLimit = modification.includes("少走路") ? 3_000 : walkingLimit;
    routeBMutation.mutate({ limit: nextLimit, localDay: 2 });
  };

  const exportPlan = (format: "json" | "geojson" | "html") => {
    if (!displayedPlan || !routeQuery.data) return;
    const selectedIds = new Set(
      displayedPlan.days.flatMap((day) => day.visits.map((visit) => visit.point_id)),
    );
    const exportData = {
      schema_version: "1",
      plan_version: planVersion,
      subject_id: confirmedId,
      generated_at: new Date().toISOString(),
      route_a_point_ids: routeQuery.data.points.map((point) => point.id),
      route_b: displayedPlan,
      local_constraints: dayTwoWalkingLimit === null
        ? []
        : [{ day: 2, max_walking_meters: dayTwoWalkingLimit }],
      evidence_ids: evidenceQuery.data?.evidence.map((item) => item.evidence_id) ?? [],
      reconfirm_before_departure: ["transport", "weather", "opening and photography rules"],
    };
    if (format === "json") {
      saveFile("pilgrimage-plan.json", "application/json", JSON.stringify(exportData, null, 2));
      return;
    }
    if (format === "geojson") {
      const geojson = {
        type: "FeatureCollection",
        schema_version: "1",
        features: routeQuery.data.points.filter((point) => selectedIds.has(point.id)).map((point) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [point.longitude, point.latitude] },
          properties: { id: point.id, name: point.name, source_url: point.provenance.source_url },
        })),
      };
      saveFile("pilgrimage-route.geojson", "application/geo+json", JSON.stringify(geojson, null, 2));
      return;
    }
    const dayHtml = displayedPlan.days.map((day) => `<section><h2>${escapeHtml(day.date)}</h2><p>${(day.walking_distance_meters / 1000).toFixed(1)} km estimated walking</p><ol>${day.visits.map((visit) => `<li>${escapeHtml(timeText(visit.start_at))} — ${escapeHtml(routeQuery.data.points.find((point) => point.id === visit.point_id)?.name ?? "Unknown")}</li>`).join("")}</ol></section>`).join("");
    const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Pilgrimage Plan v${planVersion}</title><style>body{font:16px/1.6 system-ui;max-width:800px;margin:40px auto;padding:0 24px;color:#17231f}h1,h2{color:#164d44}.notice{border-left:4px solid #b93625;padding:12px;background:#fff3ed}</style></head><body><h1>Pilgrimage Plan · Version ${planVersion}</h1><p class="notice">Read-only plan. Reconfirm transport, weather, opening, access and photography rules before departure.</p>${dayHtml}</body></html>`;
    saveFile("pilgrimage-plan.html", "text/html", html);
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#planner">跳到规划区</a>
      <header className="topbar">
        <a className="brand" href="/" aria-label="Pilgrimage Atlas 首页">
          <span className="brand-mark" aria-hidden="true"><Map size={22} strokeWidth={1.8} /></span>
          <span><strong>Pilgrimage Atlas</strong><small>可验证的动漫巡礼计划</small></span>
        </a>
        <div className="safety-note"><ShieldCheck size={18} aria-hidden="true" /><span>只读规划 · 不预订 · 不付款</span></div>
      </header>

      <main id="planner" className="planner" tabIndex={-1}>
        <section className="intro" aria-labelledby="intro-title">
          <p className="eyebrow">从灵感到可执行路线</p>
          <h1 id="intro-title">把想去的场景，整理成真正走得完的旅程。</h1>
          <p className="lede">先描述计划，再亲自确认作品。Route A 会保留每个有来源、坐标有效的候选点；无法核验的数据会明确标为未知。</p>
        </section>

        <nav className="stage-nav" aria-label="规划进度">
          <ol>
            {stages.map(({ label, icon: Icon }, index) => (
              <li key={label} className={index === activeStage ? "active" : index < activeStage ? "complete" : "upcoming"} aria-current={index === activeStage ? "step" : undefined}>
                <span className="stage-icon" aria-hidden="true"><Icon size={18} /></span>
                <span><small>0{index + 1}</small>{label}</span>
              </li>
            ))}
          </ol>
        </nav>

        <div className="workspace">
          <section className="request-card" aria-labelledby="request-title">
            <div className="section-heading">
              <div><p className="eyebrow">开放式输入</p><h2 id="request-title">你想怎样巡礼？</h2></div>
              <CircleHelp size={20} aria-label="提示：请包含出发地、日期、作品和偏好" />
            </div>
            <form onSubmit={(event) => { event.preventDefault(); resetRouteB(); setConfirmedId(null); setSubmitted(true); }}>
              <label htmlFor="trip-request">旅行想法</label>
              <textarea id="trip-request" value={request} onChange={(event) => { setRequest(event.target.value); setSubmitted(false); setConfirmedId(null); resetRouteB(); }} aria-describedby="trip-request-help" rows={6} />
              <p id="trip-request-help" className="helper-text">建议写明出发地、目的地、日期、作品、预算与步行偏好。任何关键默认值都会显示出来。</p>
              <button className="primary-button" type="submit" disabled={!request.trim()}>整理旅行条件<ArrowRight size={19} aria-hidden="true" /></button>
              <p className="submit-status" aria-live="polite">{submitted ? "已收到。请在候选中明确确认作品；不会静默确认关键选择。" : ""}</p>
            </form>
          </section>

          <aside className="principles" aria-labelledby="principles-title">
            <div className="atlas-grid" aria-hidden="true" />
            <p className="eyebrow">规划承诺</p><h2 id="principles-title">每一步都有依据，也留有余地。</h2>
            <ul>
              <li><span>01</span><div><strong>点位不靠猜</strong><p>Route A 只收录带来源、坐标有效的巡礼点。</p></div></li>
              <li><span>02</span><div><strong>路线一定可解释</strong><p>未选点会说明时间、距离、天气或访问冲突。</p></div></li>
              <li><span>03</span><div><strong>实时数据需复核</strong><p>价格、天气与营业规则显示查询时间和状态。</p></div></li>
            </ul>
          </aside>
        </div>

        {submitted && (
          <section className="results-section" aria-labelledby="subjects-title">
            <div className="results-heading">
              <div><p className="eyebrow">Bangumi 只读候选</p><h2 id="subjects-title">确认你要巡礼的作品</h2></div>
              <span className="source-chip">查询结果 · 需确认</span>
            </div>
            {subjectQuery.isPending && <p role="status">正在读取作品候选…</p>}
            {subjectQuery.isError && <p className="error-state" role="alert">{subjectQuery.error.message}</p>}
            {subjectQuery.data?.candidates.length === 0 && <p>没有找到候选。请修改作品名称后重试。</p>}
            <div className="candidate-grid">
              {subjectQuery.data?.candidates.map((candidate) => (
                <article key={candidate.subject_id} className={confirmedId === candidate.subject_id ? "candidate-card selected" : "candidate-card"}>
                  <div><span className="subject-id">Bangumi #{candidate.subject_id}</span><h3>{candidate.name_cn ?? candidate.name}</h3><p>{candidate.name}{candidate.aliases.length ? ` · ${candidate.aliases.join(" / ")}` : ""}</p></div>
                  <button className="secondary-button" type="button" aria-pressed={confirmedId === candidate.subject_id} onClick={() => { void confirmCandidate(candidate.subject_id); }}>
                    {confirmedId === candidate.subject_id ? <><Check size={18} />已确认此作品</> : "确认并查看 Route A"}
                  </button>
                </article>
              ))}
            </div>
          </section>
        )}

        {confirmedId && routeQuery.data && (
          <section className="route-section" aria-labelledby="route-a-title">
            <div className="results-heading">
              <div><p className="eyebrow">完整候选集</p><h2 id="route-a-title">Route A · {routeQuery.data.points.length} 个有来源点位</h2></div>
              <span className={routeQuery.data.is_complete ? "source-chip verified" : "source-chip"}>{routeQuery.data.is_complete ? "导入完整" : "部分数据"}</span>
            </div>
            <div className="route-layout">
              <RouteMap points={routeQuery.data.points} />
              <ol className="point-list">
                {routeQuery.data.points.map((point, index) => (
                  <li key={point.id}>
                    <span className="point-index"><MapPin size={16} />{String(index + 1).padStart(2, "0")}</span>
                    <div><strong>{point.name}</strong><small>{point.episode_refs.join(" · ") || "集数待确认"} · {point.confidence}</small></div>
                    {point.provenance.source_url && <a href={point.provenance.source_url} target="_blank" rel="noreferrer" aria-label={`${point.name} 来源`}><ExternalLink size={17} /></a>}
                  </li>
                ))}
              </ol>
            </div>
            <p className="route-note">这些点尚未按时间删减。下一阶段只会从 Route A 选择可执行子集，并解释每个遗漏。</p>
          </section>
        )}

        {confirmedId && planningQuery.data && routeQuery.data && (
          <section className="access-section" aria-labelledby="access-title">
            <div className="results-heading">
              <div><p className="eyebrow">Access / Base Plan</p><h2 id="access-title">选择抵离交通与住宿基地</h2></div>
              <span className="source-chip">人工候选 · 采用前确认</span>
            </div>
            <p className="section-intro">价格和班次是带查询时间的候选，不会触发预订。抵达后预留 90 分钟，离开前预留 120 分钟。</p>
            <div className="selection-layout">
              <fieldset className="selection-group">
                <legend>去程 · 京都 → 东京</legend>
                {planningQuery.data.access_options.filter((option) => option.destination === "东京").map((option) => (
                  <button key={option.option_id} className={inboundId === option.option_id ? "option-card selected" : "option-card"} type="button" role="radio" aria-label={`选择去程 ${modeText(option.mode)}`} aria-checked={inboundId === option.option_id} onClick={() => { setInboundId(option.option_id); resetRouteB(); }}>
                    <span className="option-icon"><TrainFront size={19} /></span>
                    <span><strong>{modeText(option.mode)}</strong><small>{timeText(option.departure_at)} → {timeText(option.arrival_at)} · {option.price?.toLocaleString("zh-CN")} {option.currency}</small></span>
                    <Check size={18} className="option-check" />
                  </button>
                ))}
              </fieldset>
              <fieldset className="selection-group">
                <legend>返程 · 东京 → 京都</legend>
                {planningQuery.data.access_options.filter((option) => option.origin === "东京").map((option) => (
                  <button key={option.option_id} className={outboundId === option.option_id ? "option-card selected" : "option-card"} type="button" role="radio" aria-label={`选择返程 ${modeText(option.mode)}`} aria-checked={outboundId === option.option_id} onClick={() => { setOutboundId(option.option_id); resetRouteB(); }}>
                    <span className="option-icon"><TrainFront size={19} /></span>
                    <span><strong>{modeText(option.mode)}</strong><small>{timeText(option.departure_at)} → {timeText(option.arrival_at)} · {option.price?.toLocaleString("zh-CN")} {option.currency}</small></span>
                    <Check size={18} className="option-check" />
                  </button>
                ))}
              </fieldset>
              <fieldset className="selection-group">
                <legend>住宿基地</legend>
                {planningQuery.data.base_candidates.map((candidate) => (
                  <button key={candidate.base_id} className={baseId === candidate.base_id ? "option-card selected" : "option-card"} type="button" role="radio" aria-label={`选择基地 ${candidate.name}`} aria-checked={baseId === candidate.base_id} onClick={() => { setBaseId(candidate.base_id); resetRouteB(); }}>
                    <span className="option-icon"><MapPin size={19} /></span>
                    <span><strong>{candidate.name}</strong><small>{candidate.base_id === planningQuery.data.recommended_base_id ? "按 Route A 距离推荐" : "可选中心基地"}</small></span>
                    <Check size={18} className="option-check" />
                  </button>
                ))}
              </fieldset>
            </div>
            <div className="planning-action">
              <label htmlFor="walking-limit"><Footprints size={18} />每日步行上限</label>
              <select id="walking-limit" value={walkingLimit} onChange={(event) => { setWalkingLimit(Number(event.target.value)); resetRouteB(); }}>
                <option value={3000}>3 公里 · 极少步行</option>
                <option value={5000}>5 公里 · 少步行</option>
                <option value={8000}>8 公里 · 标准</option>
              </select>
              <button className="primary-button" type="button" disabled={!inboundId || !outboundId || !baseId || routeBMutation.isPending} onClick={() => { routeBMutation.mutate({ limit: walkingLimit }); }}>
                {routeBMutation.isPending ? "正在验证约束…" : "生成可执行 Route B"}<ArrowRight size={19} />
              </button>
            </div>
            {routeBMutation.isError && <p className="error-state" role="alert">{routeBMutation.error.message}</p>}
          </section>
        )}

        {displayedPlan && routeQuery.data && (
          <section className="timeline-section" aria-labelledby="timeline-title">
            <div className="results-heading">
              <div><p className="eyebrow">确定性验证通过 · 计划版本 {planVersion}</p><h2 id="timeline-title">Route B · 三日可执行时间轴</h2></div>
              <span className="source-chip verified">{displayedPlan.matrix_status === "road" ? "ORS 道路估算" : "直线估算 · 已降级"}</span>
            </div>
            <div className="trip-summary">
              <div><TrainFront size={20} /><span><small>抵达</small><strong>{timeText(displayedPlan.access?.inbound.arrival_at ?? "")}</strong></span></div>
              <div><MapPin size={20} /><span><small>基地</small><strong>{displayedPlan.base.name}</strong></span></div>
              <div><Footprints size={20} /><span><small>日上限</small><strong>{walkingLimit / 1000} km</strong></span></div>
            </div>
            <div className="timeline-grid">
              {displayedPlan.days.map((day, dayIndex) => (
                <article key={day.date} className="day-card">
                  <header><span>DAY {String(dayIndex + 1).padStart(2, "0")}</span><div><strong>{day.date}</strong><small>{(day.walking_distance_meters / 1000).toFixed(1)} km 步行估算</small></div></header>
                  {day.visits.length ? (
                    <ol>
                      {day.visits.map((visit) => {
                        const matchedPoint = routeQuery.data.points.find((point) => point.id === visit.point_id);
                        return <li key={visit.point_id}><time>{timeText(visit.start_at)}</time><span><strong>{matchedPoint?.name ?? "未知点位"}</strong><small>抵达段 {(visit.incoming_distance_meters / 1000).toFixed(1)} km · 停留 35 分钟</small></span></li>;
                      })}
                    </ol>
                  ) : <p className="rest-day">抵离缓冲日 · 未安排巡礼点</p>}
                  <footer>
                    {day.maps_urls.map((url, index) => <a key={url} href={url} target="_blank" rel="noreferrer">现场导航 {index + 1}<ExternalLink size={15} /></a>)}
                  </footer>
                </article>
              ))}
            </div>
            <p className="route-note">Route B 仅从 Route A 取点；地图链接用于现场导航，时间和距离仍以 ORS 计划估算为准。出发前请复核交通、天气、营业与拍摄规则。</p>
            <div className="revision-export-grid">
              <form className="revision-card" onSubmit={(event) => { event.preventDefault(); applyModification(); }}>
                <div><p className="eyebrow">局部修改</p><h3>只重算受影响的部分</h3></div>
                <label htmlFor="plan-modification">修改要求</label>
                <textarea id="plan-modification" rows={3} value={modification} onChange={(event) => { setModification(event.target.value); }} />
                <button className="secondary-button" type="submit" disabled={routeBMutation.isPending}><RefreshCcw size={17} />应用为版本 {planVersion + 1}</button>
                <p className="helper-text">
                  {dayTwoWalkingLimit === null
                    ? "“第二天少走路”只会重算第 2 天；Route A 与未受影响日期保持稳定。"
                    : `第 2 天已按 ${(dayTwoWalkingLimit / 1000).toFixed(0)} km 局部上限重算；第 1、3 天保持稳定。`}
                </p>
              </form>
              <section className="export-card" aria-labelledby="export-title">
                <p className="eyebrow">可移交成果</p><h3 id="export-title">导出独立计划</h3>
                <button className="export-button" type="button" onClick={() => { exportPlan("json"); }}><Download size={17} />导出 JSON</button>
                <button className="export-button" type="button" onClick={() => { exportPlan("geojson"); }}><Map size={17} />导出 GeoJSON</button>
                <button className="export-button" type="button" onClick={() => { exportPlan("html"); }}><BookOpenCheck size={17} />打印 HTML</button>
                <p>JSON 和 GeoJSON 带 schema version；HTML 无外部脚本，可独立打印。</p>
              </section>
            </div>
            <section className="evidence-panel" aria-labelledby="evidence-title">
              <div className="results-heading"><div><p className="eyebrow">不可信资料 · 已隔离检索</p><h3 id="evidence-title">访问与礼仪依据</h3></div><span className="source-chip">访问日期 · 权威等级</span></div>
              {evidenceQuery.isPending && <p role="status">正在检索允许的资料命名空间…</p>}
              {evidenceQuery.isError && <p className="error-state" role="alert">资料检索暂不可用；规则保持未知，请出发前复核。</p>}
              {evidenceQuery.data?.status === "insufficient_evidence" && <p className="unknown-state">没有足够来源，未生成访问规则。请以场所当日公告为准。</p>}
              <div className="evidence-list">
                {evidenceQuery.data?.evidence.map((item) => <article key={item.evidence_id}><div><span>{item.evidence_id}</span><strong>{item.title}</strong></div><p>{item.excerpt}</p><footer><small>权威 {item.authority_level}/5 · 访问 {item.accessed_at} · {item.freshness === "current" ? "当前有效" : "时效未知，需确认"}</small>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">查看来源<ExternalLink size={14} /></a>}</footer></article>)}
              </div>
            </section>
          </section>
        )}
      </main>
    </div>
  );
}
