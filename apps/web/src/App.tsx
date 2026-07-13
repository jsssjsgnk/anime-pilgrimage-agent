import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Check,
  CircleHelp,
  Compass,
  ExternalLink,
  Map,
  MapPin,
  MessageSquareText,
  Route,
  ShieldCheck,
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

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error("无法读取已验证的数据，请稍后重试。");
  return (await response.json()) as T;
}

function animeFromRequest(request: string): string {
  return request.match(/[《「](.*?)[》」]/u)?.[1]?.trim() || request.trim();
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

  const confirmCandidate = async (subjectId: string) => {
    await fetchJson(`/api/subjects/${subjectId}/confirm`, { method: "POST" });
    setConfirmedId(subjectId);
  };

  const activeStage = confirmedId ? 2 : submitted ? 1 : 0;
  const stages = [
    { label: "说出想法", icon: MessageSquareText },
    { label: "确认作品", icon: Check },
    { label: "选择交通", icon: Compass },
    { label: "生成路线", icon: Route },
  ];

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
            <form onSubmit={(event) => { event.preventDefault(); setConfirmedId(null); setSubmitted(true); }}>
              <label htmlFor="trip-request">旅行想法</label>
              <textarea id="trip-request" value={request} onChange={(event) => { setRequest(event.target.value); setSubmitted(false); setConfirmedId(null); }} aria-describedby="trip-request-help" rows={6} />
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
      </main>
    </div>
  );
}
