export type Provider = "fixture" | "gemini";
export type Strategy = "agent" | "baseline";
export type RunStatus = "running" | "completed" | "stopped" | "interrupted" | "expired" | "blocked" | "failed";

export type Source = {
  id: string;
  label: string;
  kind: "synthetic" | "cafe" | "upload" | "camera";
  duration_ms: number;
  width: number;
  height: number;
};

export type Box = { x1: number; y1: number; x2: number; y2: number };
export type Observation = {
  at_ms: number;
  frame_ms: number;
  first_frame_ms: number;
  completed_ms: number;
  queue_min: number | null;
  queue_max: number | null;
  visibility: "clear" | "uncertain";
  people: { id: string; box: Box; membership: "waiting" | "other" | "uncertain" }[];
  groups: { id: string; activity: string; members: string[] }[];
  summary: string;
  current: boolean;
  phase: "observe" | "review";
  elapsed_ms: number;
  evidence_ms: number[];
  calls: number;
};

export type Task = {
  id: string;
  kind: "queue_attention";
  status: "open" | "acknowledged" | "resolved";
  action: "create" | "update" | "resolve" | "acknowledge";
  created_ms: number;
  updated_ms: number;
  reason: string;
  evidence_ms: number[];
};

type Tool = "inspect_frames" | "inspect_region" | "compare_observations";
type Review = {
  at_ms: number;
  tool: Tool;
  outcome: "create" | "update" | "resolve" | "hold" | "monitor" | "awaiting_persistence" | "insufficient_evidence" | "stale";
  summary: string;
  evidence_ms?: number[];
};

type EventData = {
  observation: Observation;
  task: Task;
  review_started: { at_ms: number; tool: Tool };
  review_completed: Review;
  run_status: { status: RunStatus };
  error: { code: string; message: string; at_ms: number; phase: "observe" | "review" };
  decision: { at_ms: number };
};

export type RunEvent = {
  [K in keyof EventData]: { id: number; type: K; data: EventData[K]; created_ms: number }
}[keyof EventData];

export type Config = {
  gemini_ready: boolean;
  observer: string;
  verifier: string;
  demo_id: string;
  threshold: number;
  max_lag_ms: number;
  cadence_ms: number;
  max_upload_bytes: number;
  max_calls: number;
};

export type RunConfig = {
  id: string;
  provider: Provider;
  strategy: Strategy;
  observer: string;
  verifier: string;
  policy: { threshold: number; persistence_ms: number };
};

export type Run = { id: string; source: Source; config: RunConfig; status: RunStatus };
export type SavedRun = {
  id: string; source_id: string; config: RunConfig; status: RunStatus; created_ms: number;
};

export type Metrics = {
  clips: number;
  windows: number;
  queue_count_mae: number | null;
  exact_scored: number;
  prediction_coverage: number | null;
  queue_membership_f1: number | null;
  group_pair_f1: number | null;
  actor_recall: number | null;
  alert_precision: number | null;
  alert_recall: number | null;
  false_alerts: number | null;
  duplicate_alerts: number | null;
  mean_detection_delay_ms: number | null;
  request_p50_ms: number | null;
  request_p95_ms: number | null;
  api_calls: number;
  sampled_images: number;
  errors: Record<string, number>;
  errors_to_review: { clip: string; at_ms: number; expected: number; predicted: number | null; note: string }[];
};

export type Report = {
  dataset: string;
  version: string;
  split: string;
  provider: Provider;
  synthetic: boolean;
  actual_remote_attempts: number;
  comparison: Record<Strategy, Metrics>;
};

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === "string" ? data.detail : `Request failed (HTTP ${response.status}).`;
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function post<T>(path: string, value: unknown): Promise<T> {
  return api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  });
}

export const frameUrl = (source: Source, ms: number) => `/api/sources/${source.id}/frames/${ms}`;

export function clock(ms: number, detail = false): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const time = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  return detail ? `${time}.${Math.floor((Math.max(0, ms) % 1000) / 100)}` : time;
}

export function sourceKind(source: Source): string {
  return { synthetic: "Synthetic replay", cafe: "Café dataset replay", upload: "Uploaded replay", camera: "Webcam" }[source.kind];
}
