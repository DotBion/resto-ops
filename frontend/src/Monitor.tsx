import { useEffect, useRef, useState } from "react";
import {
  Activity, ArrowDownToLine, ArrowUpRight, Check, ChevronDown, CircleAlert, Clock3,
  Crosshair, Eye, EyeOff, Film, ListChecks, Maximize, Pause, Play, ScanLine,
  Search, Users, Video, X,
} from "lucide-react";
import { clock, frameUrl, Observation, Provider, RunEvent, sourceKind, Strategy, Task } from "./api";
import { useMonitor } from "./useMonitor";

type MonitorData = ReturnType<typeof useMonitor>;
type Filter = "all" | "observations" | "reviews" | "tasks";

const OUTCOMES = {
  create: "Queue confirmed",
  update: "Task updated",
  resolve: "Queue cleared",
  hold: "Alert held",
  monitor: "Keep monitoring",
  awaiting_persistence: "Checking persistence",
  insufficient_evidence: "Insufficient evidence",
  stale: "Review expired",
};

const TOOLS = {
  inspect_frames: "More frames",
  inspect_region: "Closer look",
  compare_observations: "Earlier observations",
};

function countText(observation?: Observation): string {
  if (observation?.queue_min === null || observation?.queue_min === undefined) return "—";
  return observation.queue_min === observation.queue_max
    ? String(observation.queue_min)
    : `${observation.queue_min}–${observation.queue_max}`;
}

function byLatestTask(events: RunEvent[]): Task[] {
  const tasks = new Map<string, Task>();
  for (const event of events) {
    if (event.type === "task") tasks.set(event.data.id, event.data);
  }
  return [...tasks.values()].reverse();
}

function StatusDot({ active = false }: { active?: boolean }) {
  return <span className={`status-dot ${active ? "active" : ""}`} aria-hidden="true" />;
}

export function Monitor({ monitor: m }: { monitor: MonitorData }) {
  const [filters, setFilters] = useState<Filter>("all");
  const [boxes, setBoxes] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadKind, setUploadKind] = useState<"upload" | "cafe">("upload");
  const [preparing, setPreparing] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadFile, setUploadFile] = useState<File>();
  const playerSurface = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!uploadOpen) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !preparing) setUploadOpen(false);
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [uploadOpen, preparing]);

  const observations = m.events.flatMap((event) => event.type === "observation" ? [event.data] : []);
  const recent = observations.findLast((observation) => observation.current);
  const lastReview = m.events.findLast((event) => event.type === "review_started" || event.type === "review_completed");
  const reviewing = lastReview?.type === "review_started" && m.status === "running";
  const review = m.events.findLast((event) => event.type === "review_completed");
  const observeError = m.events.findLast((event) => event.type === "error" && event.data.phase === "observe");
  const lastSuccessful = m.events.findLast((event) => event.type === "observation" && event.data.current);
  const failed = observeError?.type === "error" && (!lastSuccessful || observeError.id > lastSuccessful.id)
    ? observeError.data.message : "";
  const stale = recent && Math.abs(m.position - recent.frame_ms) > (m.config?.max_lag_ms ?? 20000);
  const current = failed || stale ? undefined : recent;
  const tasks = byLatestTask(m.events);
  const activeTasks = tasks.filter((task) => task.status !== "resolved");
  const camera = m.source?.kind === "camera";
  const ready = m.provider === "fixture" || m.config?.gemini_ready;
  const runningCamera = camera && m.status === "running";
  const finishing = !!m.run && !camera && !m.playing && m.status === "running"
    && m.position >= (m.source?.duration_ms ?? Infinity) - 100;
  const reviewFrame = m.evidence;
  const reference = reviewFrame === undefined
    ? current
    : observations.findLast((observation) => observation.frame_ms === reviewFrame);
  const visibleBoxes = boxes && reference && (reviewFrame !== undefined || (
    !camera && Math.abs(reference.frame_ms - m.position) < 320
  )) ? reference.people : [];
  const renderStatus = m.connectionInterrupted ? "Reconnecting"
    : reviewing ? "Investigating"
    : m.status === "blocked" ? "Analysis blocked"
    : finishing ? "Finishing analysis"
    : m.playing && m.run && m.status === "running" ? "Analyzing"
    : m.playing ? "Playing"
    : m.status === "completed" ? "Complete"
    : reviewFrame !== undefined ? "Reviewing evidence"
    : m.run ? "Paused"
    : "Ready";

  async function onUpload(event: React.FormEvent) {
    event.preventDefault();
    if (!uploadFile || preparing) return;
    setPreparing(true);
    setUploadError("");
    try {
      await m.upload(uploadFile, uploadKind);
      setUploadOpen(false);
      setUploadFile(undefined);
    } catch (problem) {
      setUploadError((problem as Error).message);
    } finally {
      setPreparing(false);
    }
  }

  function seek(position: number) {
    m.review(position, false);
  }

  let tooltip = "Play the synthetic demo";
  if (camera) tooltip = runningCamera ? "Stop camera" : "Start camera";
  else if (m.playing) tooltip = "Pause";
  else if (!ready) tooltip = "Preview video";
  else if (m.provider === "gemini") tooltip = "Analyze video";
  else if (m.run && m.status === "running") tooltip = "Resume demo";

  const start = () => {
    if (camera) {
      if (runningCamera) m.stopCamera();
      else void m.startCamera();
    } else if (m.playing || !ready) {
      void m.togglePlayback();
    } else {
      void m.startVideo();
    }
  };

  return (
    <main className="workspace">
      <section className="page-head">
        <div>
          <div className="section-kicker"><StatusDot active={m.status === "running" && m.playing} /> Operations</div>
          <h1>Floor monitor</h1>
          <p>Watch the queue, review the evidence, and see when staff attention is needed.</p>
        </div>
        <div className="head-controls">
          <label className="select-control source-select">
            <Film size={15} />
            <select aria-label="Video source" value={camera ? "camera" : m.source?.id ?? ""}
              onChange={(event) => {
                if (event.target.value === "camera") {
                  void m.startCamera();
                } else {
                  const next = m.sources.find((item) => item.id === event.target.value);
                  if (next) m.openSource(next);
                }
              }}>
              {!m.source && <option value="">Choose a source</option>}
              {m.sources.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}
              {(m.config?.gemini_ready || camera) && <option value="camera">Webcam</option>}
            </select>
            <ChevronDown size={13} />
          </label>
          <button className="button secondary" onClick={() => {
            setUploadFile(undefined);
            setUploadError("");
            setUploadKind("upload");
            setUploadOpen(true);
          }}>
            <ArrowDownToLine size={15} /> Upload
          </button>
          <button className="button primary" onClick={start} disabled={!m.source || m.starting || finishing || preparing}>
            {m.playing ? <Pause size={15} /> : camera ? <Video size={15} /> : <Play size={15} />}
            {m.starting ? "Starting…" : finishing ? "Finishing…" : tooltip}
          </button>
        </div>
      </section>

      {(m.error || failed || (!ready && m.source)) && (
        <div className={`notice ${m.error || failed ? "problem" : ""}`} role={m.error || failed ? "alert" : "status"}>
          <CircleAlert size={16} />
          <span>{m.error || failed ||
            "Set GEMINI_API_KEY in the backend environment to analyze video. You can still preview this source."}</span>
          {m.error && <button className="icon-button" aria-label="Dismiss message" onClick={() => m.setError("")}><X size={15} /></button>}
        </div>
      )}

      <section className="stats" aria-label="Current scene">
        <div className="stat">
          <span className="stat-icon"><Users size={17} /></span>
          <div><p>Queue estimate</p><strong>{countText(current)}</strong></div>
          {current && <span className={`stat-note ${current.visibility === "clear" ? "accent" : ""}`}>
            {current.visibility === "clear" ? "visible" : "uncertain"}
          </span>}
        </div>
        <div className="stat">
          <span className="stat-icon"><ScanLine size={17} /></span>
          <div><p>Observed groups</p><strong>{current ? current.groups.length : "—"}</strong></div>
        </div>
        <div className="stat">
          <span className="stat-icon warm"><ListChecks size={17} /></span>
          <div><p>Active staff tasks</p><strong>{tasks.length || m.run ? activeTasks.length : "—"}</strong></div>
        </div>
        <div className="stat">
          <span className="stat-icon muted"><Clock3 size={17} /></span>
          <div><p>Observation age</p><strong>{recent ? `${(Math.max(0, m.position - recent.frame_ms) / 1000).toFixed(1)}s` : "—"}</strong></div>
          {stale && <span className="stat-note">stale</span>}
        </div>
      </section>

      <div className="main-grid">
        <section className="panel player-panel" aria-label="Video and evidence">
          <div className="panel-heading">
            <div><h2>{m.source?.label ?? "Video source"}</h2>
              <p>{m.source ? sourceKind(m.source) : "Load a video to begin"}</p></div>
            <div className="inline-controls">
              <span className="pill status"><StatusDot active={m.status === "running" && m.playing} />{renderStatus}</span>
              <button className="icon-button border" title={boxes ? "Hide boxes" : "Show boxes"}
                aria-label={boxes ? "Hide boxes" : "Show boxes"} aria-pressed={boxes} onClick={() => setBoxes(!boxes)}>
                {boxes ? <Eye size={16} /> : <EyeOff size={16} />}
              </button>
            </div>
          </div>
          <div className="video-wrap" ref={playerSurface}>
            {m.source ? (
              <div className="video-surface" style={{
                "--video-ratio": m.source.width && m.source.height ? m.source.width / m.source.height : 1.6,
              } as React.CSSProperties}>
                <video ref={m.video} key={m.source.id} muted playsInline preload="metadata"
                  src={camera ? undefined : `/api/sources/${m.source.id}/video`}
                  poster={camera ? undefined : frameUrl(m.source, 0)}
                  onTimeUpdate={m.mediaTime} onPlay={() => m.setPlaying(true)} onPause={() => m.setPlaying(false)}
                  onEnded={m.ended} aria-label={camera ? "Webcam preview" : "Replay video"} />
                {reviewFrame !== undefined && <img className="evidence-frame" src={frameUrl(m.source, reviewFrame)}
                  alt={`Evidence frame at ${clock(reviewFrame, true)}`} />}
                {visibleBoxes.length > 0 && <div className="overlays" aria-hidden="true">
                  {visibleBoxes.map(({ id, box, membership }) => (
                    <span key={id} className={`person-box ${membership}`} style={{
                      left: `${box.x1 * 100}%`, top: `${box.y1 * 100}%`,
                      width: `${(box.x2 - box.x1) * 100}%`, height: `${(box.y2 - box.y1) * 100}%`,
                    }} />
                  ))}
                </div>}
                <div className="video-caption">
                  <span>{reviewFrame !== undefined ? "EVIDENCE" : camera ? "CAMERA" : m.source.kind === "synthetic" ? "SYNTHETIC" : "REPLAY"}</span>
                  <span>{clock(reviewFrame ?? m.position, true)}</span>
                </div>
              </div>
            ) : <div className="video-empty"><Film size={30} /><p>Choose a video source</p></div>}
          </div>
          <div className="playbar">
            <button className="icon-button" onClick={start} disabled={!m.source || m.starting || finishing} aria-label={tooltip}>
              {m.playing ? <Pause size={18} /> : <Play size={18} />}
            </button>
            <span className="clock">{clock(m.position)}</span>
            {camera ? <span className="camera-track">{runningCamera ? "Capturing webcam frames" : "Camera stopped"}</span> : (
              <input type="range" className="seek" aria-label="Playback position" min={0} max={m.source?.duration_ms || 1}
                step={50} value={Math.min(m.position, m.source?.duration_ms || 1)} disabled={!m.source}
                onChange={(event) => seek(Number(event.target.value))} />
            )}
            {!camera && <span className="clock total">{clock(m.source?.duration_ms ?? 0)}</span>}
            {reviewFrame !== undefined && camera && (
              <button className="quiet-link" onClick={() => m.review(m.position, false)}>Back to camera</button>
            )}
            <button className="icon-button" title="Fullscreen" aria-label="Fullscreen" onClick={() => {
              if (document.fullscreenElement) void document.exitFullscreen();
              else void playerSurface.current?.requestFullscreen().catch(() => {});
            }}><Maximize size={16} /></button>
          </div>
        </section>

        <aside className="right-column">
          <section className="panel observation-panel">
            <div className="panel-heading compact">
              <div className="heading-with-icon"><Activity size={17} /><h2>Observations</h2></div>
              <span className="pill">{m.provider === "fixture" ? "Authored demo" : "Gemini"}</span>
            </div>
            <div className="observation-body">
              {current ? <>
                <p className="observation-summary">{current.summary}</p>
                <div className="tag-row">
                  {current.groups.length ? current.groups.map((group) => (
                    <span className="activity-tag" key={group.id}>{group.activity} · {group.members.length}</span>
                  )) : <span className="muted-text">No groups in view.</span>}
                </div>
                <button className="evidence-link" onClick={() => m.review(current.frame_ms, true)}>
                  <Crosshair size={14} /> Open frame {clock(current.frame_ms, true)} <ArrowUpRight size={13} />
                </button>
              </> : <p className="empty-text">{failed ? "Waiting for a usable observation." : stale
                ? "The last estimate is too old for the current playback position."
                : "Observations will appear here when analysis starts."}</p>}
              {(reviewing || review?.type === "review_completed") && <div className={`review-note ${reviewing ? "in-progress" : ""}`}>
                <Search size={16} />
                {reviewing && lastReview?.type === "review_started" ? (
                  <div><strong>Investigating</strong><p>{TOOLS[lastReview.data.tool]}</p></div>
                ) : review?.type === "review_completed" ? (
                  <div><strong>{OUTCOMES[review.data.outcome]}</strong><p>{review.data.summary}</p></div>
                ) : null}
              </div>}
            </div>
          </section>

          <section className="panel tasks-panel">
            <div className="panel-heading compact">
              <div className="heading-with-icon"><ListChecks size={17} /><h2>Staff tasks</h2></div>
              <span className="pill">{activeTasks.length} active</span>
            </div>
            <div className="task-body">
              {tasks.length === 0 ? <div className="task-empty"><Check size={19} /><div>
                <strong>No open tasks</strong><p>Tasks appear when there is enough evidence to act.</p>
              </div></div> : tasks.slice(0, 5).map((task) => (
                <article className={`task ${task.status}`} key={task.id}>
                  <div className="task-heading"><strong>Queue needs attention</strong>
                    <span className="task-state">{task.status === "open" ? "Open" : task.status === "resolved" ? "Resolved" : "Acknowledged"}</span>
                  </div>
                  <p>{task.reason}</p>
                  <div className="task-actions">
                    {task.evidence_ms.length > 0 && <button className="evidence-link" onClick={() => {
                      m.review(task.evidence_ms.at(-1)!, true);
                    }}>Evidence {clock(task.evidence_ms.at(-1)!, true)} <ArrowUpRight size={13} /></button>}
                    {task.status === "open" && <button className="button mini secondary" onClick={() => m.acknowledge(task.id)}>Acknowledge</button>}
                  </div>
                </article>
              ))}
            </div>
          </section>
        </aside>
      </div>

      <section className="panel timeline-panel">
        <div className="panel-heading timeline-head">
          <div className="heading-with-icon"><Clock3 size={17} /><h2>Evidence timeline</h2></div>
          <div className="tabs small" aria-label="Timeline filter">
            {(["all", "observations", "reviews", "tasks"] as const).map((filter) => (
              <button key={filter} className={filters === filter ? "selected" : ""} onClick={() => setFilters(filter)}
                aria-pressed={filters === filter}>{filter === "all" ? "All" : filter[0].toUpperCase() + filter.slice(1)}</button>
            ))}
          </div>
        </div>
        <Timeline events={m.events} filter={filters} review={m.review} />
      </section>

      <section className="run-options" aria-label="Analysis settings">
        <label>Analysis mode
          <select value={m.provider} disabled={camera || m.source?.kind !== "synthetic"}
            onChange={(event) => m.setMode(event.target.value as Provider)}>
            <option value="fixture">Authored demo</option><option value="gemini">Gemini</option>
          </select>
        </label>
        <label>Strategy
          <select value={m.strategy} disabled={camera && m.status === "running"}
            onChange={(event) => m.setAnalysisStrategy(event.target.value as Strategy)}>
            <option value="agent">Investigate before alerting</option><option value="baseline">Single observation baseline</option>
          </select>
        </label>
        <label>Queue threshold
          <input type="number" min={2} max={30} value={m.threshold} disabled={m.status === "running"}
            onChange={(event) => {
              const next = event.target.valueAsNumber;
              if (Number.isInteger(next) && next >= 2 && next <= 30) m.setThreshold(next);
            }} />
        </label>
        {m.config?.gemini_ready && (
          <button className="button secondary" onClick={() => void m.startCamera()} disabled={m.starting || runningCamera}>
            <Video size={15} /> Use webcam
          </button>
        )}
      </section>

      {uploadOpen && <div className="modal-backdrop" onClick={() => !preparing && setUploadOpen(false)}>
        <form className="modal" role="dialog" aria-modal="true" aria-labelledby="upload-title"
          onSubmit={onUpload} onClick={(event) => event.stopPropagation()}>
          <div className="modal-heading"><h2 id="upload-title">Upload video</h2>
            <button type="button" className="icon-button" disabled={preparing} onClick={() => setUploadOpen(false)} aria-label="Close upload"><X size={18} /></button>
          </div>
          <p>Choose an MP4 or WebM up to 10 minutes and 150 MiB.</p>
          <label className="file-field"><Film size={17} /><span>{uploadFile?.name ?? "Choose a video file"}</span>
            <input autoFocus type="file" accept="video/*,.mp4,.webm,.mkv,.mov" required disabled={preparing}
              onChange={(event) => setUploadFile(event.target.files?.[0])} />
          </label>
          <label className="modal-label">Source label
            <select value={uploadKind} disabled={preparing}
              onChange={(event) => setUploadKind(event.target.value as "upload" | "cafe")}>
              <option value="upload">Uploaded replay</option><option value="cafe">Café dataset replay</option>
            </select>
          </label>
          {uploadError && <p className="form-error" role="alert">{uploadError}</p>}
          <div className="modal-actions">
            <button type="button" className="button secondary" disabled={preparing} onClick={() => setUploadOpen(false)}>Cancel</button>
            <button className="button primary" disabled={!uploadFile || preparing}>{preparing ? "Preparing video…" : "Open video"}</button>
          </div>
        </form>
      </div>}
    </main>
  );
}

function Timeline({ events, filter, review }: { events: RunEvent[]; filter: Filter; review: MonitorData["review"] }) {
  const items = events.flatMap((event) => {
    if (event.type === "observation" && event.data.phase === "observe" && (filter === "all" || filter === "observations")) {
      const obs = event.data;
      return [{ id: event.id, at: obs.at_ms, frame: obs.frame_ms, icon: Activity, tone: "observation",
        label: obs.current ? "Observation" : "Late observation", summary: obs.summary }];
    }
    if (event.type === "review_completed" && (filter === "all" || filter === "reviews")) {
      return [{ id: event.id, at: event.data.at_ms, frame: event.data.evidence_ms?.at(-1), icon: Search, tone: "review",
        label: OUTCOMES[event.data.outcome], summary: event.data.summary }];
    }
    if (event.type === "task" && (filter === "all" || filter === "tasks")) {
      const labels = { create: "Task created", update: "Task updated", resolve: "Task resolved", acknowledge: "Task acknowledged" };
      return [{ id: event.id, at: event.data.updated_ms, frame: event.data.evidence_ms?.at(-1), icon: ListChecks, tone: "task",
        label: labels[event.data.action], summary: event.data.reason }];
    }
    if (event.type === "error" && filter === "all") {
      return [{ id: event.id, at: event.data.at_ms, frame: undefined, icon: CircleAlert, tone: "task",
        label: "Analysis error", summary: event.data.message }];
    }
    return [];
  }).reverse();

  if (!items.length) return <p className="timeline-empty">No events to show.</p>;

  return <div className="timeline-list">
    {items.map(({ id, at, frame, icon: Icon, tone, label, summary }) => (
      <div className="timeline-row" key={id}>
        <span className="clock">{clock(at, true)}</span>
        <span className={`timeline-icon ${tone}`}><Icon size={15} /></span>
        <div className="timeline-content"><strong>{label}</strong><p>{summary}</p></div>
        {frame !== undefined && <button className="icon-button border" title="Open evidence"
          aria-label={`Open evidence at ${clock(frame, true)}`} onClick={() => review(frame, true)}>
          <ArrowUpRight size={15} />
        </button>}
      </div>
    ))}
  </div>;
}
