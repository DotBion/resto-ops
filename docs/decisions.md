# Decisions

| Decision | Reason and tradeoff | Revisit when |
| --- | --- | --- |
| Begin with a synthetic replay and the Café folder importer | The official Café link points to a single large archive. A deterministic replay verifies the workflow while paired clips are obtained. | A reviewed Café subset is available. |
| Use Gemini's GenerateContent REST endpoint | The documented request format is small, testable with a fake HTTP response, and uses the project's existing HTTP client. The adapter still owns validation and retry handling. | Native tools or media features warrant moving to an SDK. |
| Use timestamped JPEG windows | Sampling the same video timeline for playback and evidence gives an auditable input boundary. Longer motion patterns may need denser samples. | Real footage shows errors from sparse sampling. |
| Let the model select a bounded inspection and let app policy apply the task | The model can request a crop, denser frames, or comparison. The app controls persistence, freshness, and deduplication. | Held-out results favor a different alert policy. |
| Keep identifier scope within an observation | Model-produced identifiers can change between requests. Scene memory retains descriptions and counts. | An independent tracker is validated. |
| Use SQLite and a local server | Saves evidence, tasks, and run history with a small setup. A single server process owns active runs. | Shared deployment or multiple workers are needed. |
| Use the same initial observations for the evaluator's two strategies | This isolates the value of investigation and makes extra calls visible. | Benchmarking independent end-to-end deployments. |
| Start with a private GitHub repository | The owner can review code and results before publishing it. | The owner prepares a public submission. |
