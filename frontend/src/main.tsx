import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ArrowRight, ChevronRight, Coffee, History, LayoutDashboard, ListFilter, Radio } from "lucide-react";
import "@fontsource-variable/dm-sans";
import "@fontsource/instrument-serif/400.css";
import { api, clock, Metrics, Report, SavedRun, Source } from "./api";
import { Monitor } from "./Monitor";
import { useMonitor } from "./useMonitor";
import "./styles.css";

type View = "monitor" | "evaluation" | "history";

function App() {
  const [view, setView] = useState<View>("monitor");
  const monitor = useMonitor();
  return <>
    <header className="topbar">
      <div className="nav-inner">
        <button className="brand" onClick={() => setView("monitor")} aria-label="Café Ops home">
          <span className="brand-mark"><Coffee size={18} strokeWidth={1.9} /></span>
          <span>Café Ops</span>
        </button>
        <nav className="nav-tabs" aria-label="Workspace">
          <button className={view === "monitor" ? "current" : ""} onClick={() => setView("monitor")}><LayoutDashboard size={15} /> Monitor</button>
          <button className={view === "evaluation" ? "current" : ""} onClick={() => setView("evaluation")}><ListFilter size={16} /> Evaluation</button>
          <button className={view === "history" ? "current" : ""} onClick={() => setView("history")}><History size={16} /> Run history</button>
        </nav>
        <span className="workspace-indicator"><Radio size={14} /> Local workspace</span>
      </div>
    </header>
    <div hidden={view !== "monitor"}><Monitor monitor={monitor} /></div>
    {view === "evaluation" && <Evaluation />}
    {view === "history" && <RunHistory sources={monitor.sources} open={(run) => {
      monitor.loadRun(run);
      setView("monitor");
    }} />}
  </>;
}

const METRICS: { key: keyof Metrics; label: string; format?: "percent" | "ms" }[] = [
  { key: "queue_count_mae", label: "Mean queue count error" },
  { key: "prediction_coverage", label: "Prediction coverage", format: "percent" },
  { key: "queue_membership_f1", label: "Queue membership F1", format: "percent" },
  { key: "group_pair_f1", label: "Group pair F1", format: "percent" },
  { key: "alert_precision", label: "Alert precision", format: "percent" },
  { key: "alert_recall", label: "Alert recall", format: "percent" },
  { key: "false_alerts", label: "False alerts" },
  { key: "duplicate_alerts", label: "Duplicate alerts" },
  { key: "mean_detection_delay_ms", label: "Mean detection delay", format: "ms" },
  { key: "request_p50_ms", label: "Request latency p50", format: "ms" },
  { key: "request_p95_ms", label: "Request latency p95", format: "ms" },
  { key: "api_calls", label: "Model request attempts" },
  { key: "sampled_images", label: "Frames passed to analysis" },
];

function formatMetric(value: Metrics[keyof Metrics], style?: "percent" | "ms"): string {
  if (typeof value !== "number") return "—";
  if (style === "percent") return `${Number((value * 100).toFixed(1))}%`;
  if (style === "ms") return `${value.toLocaleString()} ms`;
  return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function Evaluation() {
  const [report, setReport] = useState<Report>();
  const [error, setError] = useState("");
  useEffect(() => {
    let mounted = true;
    void api<Report>("/evaluation").then((data) => { if (mounted) setReport(data); })
      .catch((problem: Error) => { if (mounted) setError(problem.message); });
    return () => { mounted = false; };
  }, []);

  return <main className="workspace subpage">
    <section className="page-head"><div>
      <div className="section-kicker"><ListFilter size={14} /> Performance</div>
      <h1>Evaluation</h1>
      <p>Compare a single observation with the investigation strategy on the same footage.</p>
    </div>
      {report && <a className="button secondary" href="/api/evaluation" download="cafe-evaluation.json">Download report <ArrowRight size={15} /></a>}
    </section>
    {error ? <div className="notice problem" role="alert">{error}</div> : report ? <>
      <div className="notice">
        <strong>{report.dataset}</strong>
        <span>{report.provider === "fixture" ? "Authored demo outputs. These results measure workflow behavior only."
          : report.synthetic ? "Real Gemini requests on the synthetic scene." : "Real Gemini requests on reviewed footage."}</span>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <div><h2>Baseline and agent</h2>
            <p>{report.comparison.agent.clips} {report.comparison.agent.clips === 1 ? "clip" : "clips"}
              {" · "}{report.comparison.agent.windows} windows per strategy</p></div>
          <span className="pill">{report.synthetic ? "Synthetic scenario" : report.split.replace("_", " ")}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th scope="col">Metric</th><th scope="col">Baseline</th><th scope="col">Investigation agent</th></tr></thead>
            <tbody>{METRICS.map((metric) => <tr key={metric.key}>
              <th scope="row">{metric.label}</th>
              <td>{formatMetric(report.comparison.baseline[metric.key], metric.format)}</td>
              <td className="metric-agent">{formatMetric(report.comparison.agent[metric.key], metric.format)}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </section>
      {(["baseline", "agent"] as const).map((strategy) => {
        const metrics = report.comparison[strategy];
        return <section className="panel errors-panel" key={strategy}>
          <div className="panel-heading"><div><h2>{strategy === "baseline" ? "Baseline errors" : "Investigation errors"}</h2></div></div>
          {metrics.errors_to_review.length ? metrics.errors_to_review.map((item) => (
            <div className="error-row" key={`${item.clip}:${item.at_ms}`}>
              <span className="clock">{clock(item.at_ms, true)}</span>
              <div><strong>Expected {item.expected} · observed {item.predicted ?? "unknown"}</strong><p>{item.note}</p></div>
            </div>
          )) : <p className="timeline-empty">No queue count errors in this report.</p>}
        </section>;
      })}
    </> : <p className="timeline-empty">Loading evaluation…</p>}
  </main>;
}

function RunHistory({ sources, open }: { sources: Source[]; open: (run: SavedRun) => void }) {
  const [runs, setRuns] = useState<SavedRun[]>();
  const [error, setError] = useState("");
  useEffect(() => {
    let mounted = true;
    void api<SavedRun[]>("/runs").then((data) => { if (mounted) setRuns(data); })
      .catch((problem: Error) => { if (mounted) setError(problem.message); });
    return () => { mounted = false; };
  }, []);

  return <main className="workspace subpage">
    <section className="page-head"><div>
      <div className="section-kicker"><History size={14} /> Saved activity</div>
      <h1>Run history</h1>
      <p>Reopen an earlier run to review its observations, tasks, and supporting frames.</p>
    </div></section>
    <section className="panel history-list">
      {error ? <p className="timeline-empty" role="alert">{error}</p> : !runs ? (
        <p className="timeline-empty">Loading runs…</p>
      ) : !runs.length ? <p className="timeline-empty">Analysis runs will appear here.</p> : runs.map((run) => (
        <button className="history-row" key={run.id} onClick={() => open(run)}>
          <History size={17} />
          <div><strong>{sources.find((item) => item.id === run.source_id)?.label ?? "Webcam"}</strong>
            <p>{new Date(run.created_ms).toLocaleString()} · {run.config.provider === "gemini" ? "Gemini" : "Authored demo"}
              {" · "}{run.config.strategy === "agent" ? "Investigation" : "Baseline"}</p></div>
          <span className="pill">{run.status}</span><ChevronRight size={17} />
        </button>
      ))}
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<App />);
