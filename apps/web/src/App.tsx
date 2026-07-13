import {
  ArrowRight,
  Check,
  CircleHelp,
  Compass,
  Map,
  MessageSquareText,
  Route,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";

const stages = [
  { label: "说出想法", icon: MessageSquareText, status: "active" },
  { label: "确认作品", icon: Check, status: "upcoming" },
  { label: "选择交通", icon: Compass, status: "upcoming" },
  { label: "生成路线", icon: Route, status: "upcoming" },
] as const;

export function App() {
  const [request, setRequest] = useState(
    "我从京都出发，九月去东京三天，想巡礼《孤独摇滚！》，预算中等，希望少走路。",
  );
  const [submitted, setSubmitted] = useState(false);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#planner">
        跳到规划区
      </a>
      <header className="topbar">
        <a className="brand" href="/" aria-label="Pilgrimage Atlas 首页">
          <span className="brand-mark" aria-hidden="true">
            <Map size={22} strokeWidth={1.8} />
          </span>
          <span>
            <strong>Pilgrimage Atlas</strong>
            <small>可验证的动漫巡礼计划</small>
          </span>
        </a>
        <div className="safety-note">
          <ShieldCheck size={18} aria-hidden="true" />
          <span>只读规划 · 不预订 · 不付款</span>
        </div>
      </header>

      <main id="planner" className="planner" tabIndex={-1}>
        <section className="intro" aria-labelledby="intro-title">
          <p className="eyebrow">从灵感到可执行路线</p>
          <h1 id="intro-title">把想去的场景，整理成真正走得完的旅程。</h1>
          <p className="lede">
            先用自然语言描述计划。作品、日期、长途交通和住宿基地都会在采用前请你确认；无法核验的数据会明确标为未知。
          </p>
        </section>

        <nav className="stage-nav" aria-label="规划进度">
          <ol>
            {stages.map(({ label, icon: Icon, status }, index) => (
              <li key={label} className={status} aria-current={status === "active" ? "step" : undefined}>
                <span className="stage-icon" aria-hidden="true">
                  <Icon size={18} />
                </span>
                <span>
                  <small>0{index + 1}</small>
                  {label}
                </span>
              </li>
            ))}
          </ol>
        </nav>

        <div className="workspace">
          <section className="request-card" aria-labelledby="request-title">
            <div className="section-heading">
              <div>
                <p className="eyebrow">开放式输入</p>
                <h2 id="request-title">你想怎样巡礼？</h2>
              </div>
              <CircleHelp size={20} aria-label="提示：请包含出发地、日期、作品和偏好" />
            </div>

            <form
              onSubmit={(event) => {
                event.preventDefault();
                setSubmitted(true);
              }}
            >
              <label htmlFor="trip-request">旅行想法</label>
              <textarea
                id="trip-request"
                value={request}
                onChange={(event) => {
                  setRequest(event.target.value);
                  setSubmitted(false);
                }}
                aria-describedby="trip-request-help"
                rows={6}
              />
              <p id="trip-request-help" className="helper-text">
                建议写明出发地、目的地、日期、作品、预算与步行偏好。任何关键默认值都会显示出来。
              </p>
              <button className="primary-button" type="submit" disabled={!request.trim()}>
                整理旅行条件
                <ArrowRight size={19} aria-hidden="true" />
              </button>
              <p className="submit-status" aria-live="polite">
                {submitted ? "已收到。下一步会展示可编辑条件卡，不会静默确认关键选择。" : ""}
              </p>
            </form>
          </section>

          <aside className="principles" aria-labelledby="principles-title">
            <div className="atlas-grid" aria-hidden="true" />
            <p className="eyebrow">规划承诺</p>
            <h2 id="principles-title">每一步都有依据，也留有余地。</h2>
            <ul>
              <li>
                <span>01</span>
                <div>
                  <strong>点位不靠猜</strong>
                  <p>Route A 只收录带来源、坐标有效的巡礼点。</p>
                </div>
              </li>
              <li>
                <span>02</span>
                <div>
                  <strong>路线一定可解释</strong>
                  <p>未选点会说明时间、距离、天气或访问冲突。</p>
                </div>
              </li>
              <li>
                <span>03</span>
                <div>
                  <strong>实时数据需复核</strong>
                  <p>价格、天气与营业规则显示查询时间和状态。</p>
                </div>
              </li>
            </ul>
          </aside>
        </div>
      </main>
    </div>
  );
}

