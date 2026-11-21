import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, Config, post, Provider, Run, RunEvent, RunStatus, SavedRun, Source, Strategy } from "./api";

type Advance = { runId: string; atMs: number; final: boolean };

export function useMonitor() {
  const video = useRef<HTMLVideoElement | null>(null);
  const eventSource = useRef<EventSource | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const active = useRef<Run | null>(null);
  const epoch = useRef(0);
  const statusRef = useRef<RunStatus>("stopped");
  const pending = useRef<Advance | null>(null);
  const reporting = useRef(false);
  const lastSent = useRef(-500);

  const [sources, setSources] = useState<Source[]>([]);
  const [config, setConfig] = useState<Config>();
  const [source, setSource] = useState<Source>();
  const [provider, setProvider] = useState<Provider>("fixture");
  const [strategy, setStrategy] = useState<Strategy>("agent");
  const [threshold, setThreshold] = useState(4);
  const [run, setRun] = useState<Run>();
  const [status, setStatus] = useState<RunStatus>("stopped");
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [position, setPosition] = useState(0);
  const [evidence, setEvidence] = useState<number>();
  const [playing, setPlaying] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [connectionInterrupted, setConnectionInterrupted] = useState(false);

  const closeCamera = useCallback(() => {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    if (video.current?.srcObject) video.current.srcObject = null;
  }, []);

  const stop = useCallback((clear: boolean) => {
    epoch.current++;
    pending.current = null;
    lastSent.current = -500;
    if (active.current && statusRef.current === "running") {
      void post(`/runs/${active.current.id}/stop`, {}).catch(() => {});
    }
    active.current = null;
    statusRef.current = "stopped";
    if (clear) {
      eventSource.current?.close();
      eventSource.current = null;
      setEvents([]);
      setRun(undefined);
      setStatus("stopped");
    }
    setStarting(false);
  }, []);

  useEffect(() => {
    let canceled = false;
    void Promise.all([api<Config>("/config"), api<Source[]>("/sources")]).then(([settings, list]) => {
      if (canceled) return;
      setConfig(settings);
      setSources(list);
      setThreshold(settings.threshold);
      setSource(list.find((item) => item.id === settings.demo_id) ?? list[0]);
    }).catch((problem: Error) => {
      if (!canceled) setError(problem.message);
    });
    return () => {
      canceled = true;
      const id = active.current?.id;
      eventSource.current?.close();
      closeCamera();
      if (id && statusRef.current === "running") {
        void post(`/runs/${id}/stop`, {}).catch(() => {});
      }
    };
  }, [closeCamera]);

  function attach(next: Run, historical = false) {
    eventSource.current?.close();
    setEvents([]);
    setConnectionInterrupted(false);
    setRun(next);
    setStatus(next.status);
    statusRef.current = next.status;
    active.current = historical ? null : next;
    const feed = new EventSource(`/api/runs/${next.id}/events`);
    eventSource.current = feed;
    feed.onopen = () => setConnectionInterrupted(false);
    feed.onerror = () => setConnectionInterrupted(true);
    feed.onmessage = (message) => {
      if (eventSource.current !== feed) return;
      const update = JSON.parse(message.data) as RunEvent;
      setEvents((existing) => {
        if (existing.at(-1)?.id && existing.at(-1)!.id >= update.id) return existing;
        return [...existing.slice(-799), update];
      });
      if (update.type === "run_status") {
        statusRef.current = update.data.status;
        setStatus(update.data.status);
        if (update.data.status === "blocked" || update.data.status === "failed") {
          if (active.current?.source.kind === "camera") closeCamera();
          video.current?.pause();
        }
      }
    };
  }

  async function flush() {
    if (reporting.current) return;
    reporting.current = true;
    try {
      while (pending.current) {
        const next = pending.current;
        pending.current = null;
        if (active.current?.id !== next.runId || statusRef.current !== "running") continue;
        try {
          await post(`/runs/${next.runId}/advance`, { at_ms: next.atMs, final: next.final });
        } catch (problem) {
          if (active.current?.id === next.runId && !(problem instanceof ApiError && problem.status === 409)) {
            setError((problem as Error).message);
          }
        }
      }
    } finally {
      reporting.current = false;
    }
  }

  function report(atMs: number, final = false) {
    const next = active.current;
    if (!next || statusRef.current !== "running" || next.source.kind === "camera") return;
    const time = Math.min(next.source.duration_ms, Math.max(lastSent.current, atMs));
    if (!final && time - lastSent.current < 375) return;
    lastSent.current = time;
    pending.current = { runId: next.id, atMs: time, final };
    void flush();
  }

  function mediaTime() {
    if (!video.current || source?.kind === "camera") return;
    const time = Math.max(0, Math.round(video.current.currentTime * 1000));
    setPosition(time);
    if (!video.current.paused && evidence === undefined) report(time);
  }

  function ended() {
    if (source && source.kind !== "camera") {
      setPosition(source.duration_ms);
      report(source.duration_ms, true);
    }
    setPlaying(false);
  }

  function openSource(next: Source) {
    video.current?.pause();
    closeCamera();
    stop(true);
    setEvidence(undefined);
    setPosition(0);
    setPlaying(false);
    setSource(next);
    setProvider(next.kind === "synthetic" ? "fixture" : "gemini");
    setError("");
    if (video.current && next.id === source?.id) video.current.currentTime = 0;
  }

  function setMode(next: Provider) {
    video.current?.pause();
    stop(true);
    setEvidence(undefined);
    setPlaying(false);
    setProvider(next);
  }

  function setAnalysisStrategy(next: Strategy) {
    video.current?.pause();
    stop(true);
    setEvidence(undefined);
    setPlaying(false);
    setStrategy(next);
  }

  async function upload(file: File, kind: "upload" | "cafe") {
    setError("");
    if (config && file.size > config.max_upload_bytes) {
      throw new Error("Choose a video smaller than 150 MiB.");
    }
    const data = new FormData();
    data.append("video", file);
    data.append("kind", kind);
    const next = await api<Source>("/sources", { method: "POST", body: data });
    setSources((list) => [next, ...list]);
    openSource(next);
  }

  function review(atMs: number, still: boolean) {
    if (source?.kind !== "camera") {
      video.current?.pause();
      if (active.current && statusRef.current === "running") stop(false);
      if (video.current) video.current.currentTime = atMs / 1000;
      setPosition(atMs);
    }
    setEvidence(still ? atMs : undefined);
  }

  async function startVideo() {
    if (!source || source.kind === "camera" || !video.current || starting) return;
    setError("");
    setEvidence(undefined);
    try {
      if (active.current && statusRef.current === "running") {
        if (video.current.paused) {
          await video.current.play();
          report(Math.round(video.current.currentTime * 1000));
        } else {
          video.current.pause();
        }
        return;
      }
      if (provider === "gemini" && !config?.gemini_ready) return;
      setStarting(true);
      const token = ++epoch.current;
      if (video.current.ended || position >= source.duration_ms - 150) {
        video.current.currentTime = 0;
      }
      const next = await post<Run>("/runs", { source_id: source.id, provider, strategy, threshold });
      if (token !== epoch.current) {
        void post(`/runs/${next.id}/stop`, {}).catch(() => {});
        return;
      }
      lastSent.current = -500;
      attach(next);
      if (video.current) {
        await video.current.play();
        report(Math.round(video.current.currentTime * 1000));
      }
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setStarting(false);
    }
  }

  async function togglePlayback() {
    if (!video.current || !source || source.kind === "camera") return;
    setEvidence(undefined);
    try {
      if (video.current.paused) {
        await video.current.play();
        report(Math.round(video.current.currentTime * 1000));
      } else {
        video.current.pause();
      }
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  async function startCamera() {
    if (!config?.gemini_ready || starting) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Camera access requires localhost or an HTTPS connection.");
      return;
    }
    video.current?.pause();
    stop(true);
    closeCamera();
    setStarting(true);
    setError("");
    const token = epoch.current;
    let incoming: MediaStream | null = null;
    try {
      incoming = await navigator.mediaDevices.getUserMedia({ audio: false, video: { width: { ideal: 960 } } });
      if (token !== epoch.current) {
        incoming.getTracks().forEach((track) => track.stop());
        return;
      }
      const next = await post<Run>("/runs", { source_id: "camera", provider: "gemini", strategy, threshold });
      if (token !== epoch.current) {
        incoming.getTracks().forEach((track) => track.stop());
        void post(`/runs/${next.id}/stop`, {}).catch(() => {});
        return;
      }
      stream.current = incoming;
      setProvider("gemini");
      setSource(next.source);
      setPosition(0);
      setEvidence(undefined);
      attach(next);
    } catch (problem) {
      incoming?.getTracks().forEach((track) => track.stop());
      const permission = problem instanceof DOMException && problem.name === "NotAllowedError";
      setError(permission ? "Allow camera access in your browser to use the webcam." : (problem as Error).message);
    } finally {
      setStarting(false);
    }
  }

  useEffect(() => {
    const player = video.current;
    const camera = stream.current;
    if (!camera || !player || source?.kind !== "camera" || run?.source.id !== source.id) return;

    player.srcObject = camera;
    void player.play().catch(() => setError("The webcam preview could not start."));
    const canvas = document.createElement("canvas");
    const started = performance.now();
    let sending = false;
    const timer = window.setInterval(() => {
      if (sending || statusRef.current !== "running" || !player.videoWidth) return;
      const at = Math.round(performance.now() - started);
      canvas.width = Math.min(960, player.videoWidth);
      canvas.height = Math.round(player.videoHeight * canvas.width / player.videoWidth);
      canvas.getContext("2d")?.drawImage(player, 0, 0, canvas.width, canvas.height);
      sending = true;
      canvas.toBlob((blob) => {
        if (!blob) {
          sending = false;
          return;
        }
        void api(`/runs/${run.id}/frame?at_ms=${at}`, {
          method: "POST", body: blob, headers: { "Content-Type": "image/jpeg" },
        }).then(() => setPosition(at)).catch((problem: Error) => {
          if (active.current?.id === run.id) setError(problem.message);
        }).finally(() => {
          sending = false;
        });
      }, "image/jpeg", 0.8);
    }, 625);
    return () => window.clearInterval(timer);
  }, [source, run]);

  function stopCamera() {
    closeCamera();
    stop(false);
    setPlaying(false);
  }

  function loadRun(saved: SavedRun) {
    const current = sources.find((item) => item.id === saved.source_id);
    video.current?.pause();
    closeCamera();
    stop(true);
    setPosition(0);
    setEvidence(undefined);
    setError("");
    setProvider(saved.config.provider);
    setStrategy(saved.config.strategy);
    setThreshold(saved.config.policy.threshold);
    const historical = current ?? {
      id: saved.source_id, label: "Webcam", kind: "camera", duration_ms: 0, width: 0, height: 0,
    };
    setSource(historical);
    attach({ id: saved.id, source: historical, config: saved.config, status: saved.status }, true);
  }

  function acknowledge(taskId: string) {
    if (!run) return;
    void post(`/runs/${run.id}/tasks/${taskId}/acknowledge`, {}).catch((problem: Error) => setError(problem.message));
  }

  return {
    video, source, sources, config, provider, strategy, threshold, setThreshold, run, status, events,
    position, evidence, playing, setPlaying, starting, error, setError, connectionInterrupted,
    openSource, setMode, setAnalysisStrategy, upload, mediaTime, ended, review, startVideo,
    togglePlayback, startCamera, stopCamera, loadRun, acknowledge,
  };
}
