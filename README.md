# Café Ops

Café Ops monitors a video feed for customers waiting to order. It checks additional frames when a queue may need staff attention, and records the resulting task with links to the underlying evidence.

The dashboard includes a 32-second synthetic replay with authored observations. It runs without credentials and shows a false alert being held, a sustained queue creating a task, and the task resolving when the line clears.

## Run locally

Install Python 3.11+, Node.js 22+ (22.12 or newer), and FFmpeg with `ffprobe` and the `libx264` encoder.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open [the local dashboard](http://127.0.0.1:8000) and select **Play the synthetic demo**. To compare strategies on the same replay, switch **Strategy** to **Single observation baseline** and restart playback from the beginning. **Run history** opens saved tasks and evidence.

For frontend development, run the backend on port 8000 and start `npm --prefix frontend run dev`.

## Run Gemini analysis

Set `GEMINI_API_KEY` in the server environment or in a local `.env` based on `.env.example`, then restart the backend. The default observer and verifier are `gemini-4-hydrogen`. Each can be set independently. Only the backend calls Google.

Choose **Gemini** for the synthetic video, upload an MP4 or WebM, or select **Webcam**. Start analysis to send sampled frames to Gemini. Test with footage you are permitted to process. Webcam capture requires browser permission and starts only after you select it. Webcam evidence opens the sampled still. Replay evidence opens the sampled still and moves the video playhead to that position.

The app defaults to 30 Gemini request attempts per run and 100 per server process, including retries. Sessions use a two-second minimum cadence and a 20-second maximum observation lag by default. These settings are configurable in `.env.example`. Requests may take longer than the cadence. The dashboard shows observation age. Responses beyond the lag limit cannot create, update, or resolve tasks.

For a bounded API check, run:

```sh
python -m eval.pilot --output eval/results/pilot.json
```

The same command runs on GitHub under **Actions → Gemini smoke test → Run workflow** with the repository secret `GEMINI_API_KEY`. It makes at most two request attempts using the bundled synthetic scene and stores the report as a workflow artifact. The automated build checks use the authored demo and require no key. [See the recorded smoke test and its limits](docs/evaluation.md#verified-results).

## Evaluate footage

```sh
python -m eval.benchmark --fixture --output /tmp/cafe-evaluation.json
python -m unittest discover -v
```

The [bundled report](eval/fixture-report.json) uses 16 samples from one authored scene. It exercises behavior and metric calculations. Gemini quality on actual café footage requires a separate run.

Use the [Café project distribution](https://dk-kim.github.io/CAFE/) to obtain selected clip folders and review its dataset terms. The distribution is a large archive. The example command retrieves one paired clip using about 13 MiB of byte ranges.

```sh
python -m eval.fetch_example eval/local/paired/8/380
python -m eval.import_cafe eval/local/paired/8/380 \
  --fps 30 --cafe source-8 --view unknown --recording-group cafe-source-8 \
  --split development --manifest eval/local/cafe-example.json
```

For a reviewed set of other clips, import each selected folder as follows.

```sh
python -m eval.import_cafe /path/to/local/video_id/clip_id \
  --fps 30 --cafe place-a --view camera-1 --recording-group original-recording-01 \
  --split held_out --manifest eval/local/cafe-manifest.json
```

Use your recording's actual FPS. The importer reads `ann.json` and `images/frames_<number>.jpg`, creates a replay MP4 beside the manifest, and maps the annotated key frame onto the analysis clock. It imports boxes and social groups. Review `queue_count` and each person's `membership` by watching the clip before scoring operational queue metrics. Mark ambiguous customers as `uncertain`. Give overlapping clips and synchronized views the same recording group. Label alert windows on continuous footage for delay measurements. See [evaluation details](docs/evaluation.md).

```sh
python -m eval.benchmark --manifest eval/local/cafe-manifest.json \
  --gemini --split held_out --output .cafe-ops/evaluation.json
```

**Evaluation** reads `evaluation.json` from the runtime directory when present. Keep uploaded footage, annotations, and reports containing nonpublic observations on the local machine. The runtime directory defaults to `.cafe-ops/` and holds videos, sampled frames, and the SQLite journal.

## Project documentation

| Document | Contents |
| --- | --- |
| [Implementation plan](plan.md) | Scope, architecture, milestones, and current status |
| [Agent design](agent.md) | Live agent behavior, model settings, and the proposed Carbon closing review |
| [Contributor guidance](AGENTS.md) | Repository entry points, checks, and documentation conventions |
| [Evaluation](docs/evaluation.md) | Scoring protocol, evidence, and verified results |
| [Decision log](docs/decisions.md) | Design choices and tradeoffs |
| [Issue log](docs/issues.md) | Observed failures and fixes |
| [Demo script](docs/demo.md) | One-minute walkthrough |
