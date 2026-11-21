# Build issues

| Issue | Impact | Resolution |
| --- | --- | --- |
| The workspace's HTTP proxy uses SOCKS | The service failed to initialize the HTTP client without the proxy extra. | Declared the HTTPX SOCKS dependency and restarted the service successfully. |
| A timeline event did not narrow to the error variant in TypeScript | The production frontend build stopped. | Narrowed the event by its discriminator and reran the build. |
| Local Chromium could not create its required socket in the workspace | Local headless browser checks could not launch. | Added a browser check to the GitHub-hosted build workflow. |
| The first Gemini smoke request returned HTTP 400 | It stopped before producing a prediction. | Simplified the provider schema and retained strict application validation. Added redacted provider diagnostics to the pilot report. The revised request reached the model. |
| Gemini returned a structurally loose observation after accepting the revised request | Strict row validation discarded the entire observation. | Preserve usable rows and valid frame references, and downgrade observations with rejected fields to uncertain. The follow-up two-call smoke test passed. |
| Observed Gemini latency exceeded the original six-second freshness limit | Valid results would often become stale during continuous replay. | Raised the initial freshness limit to 20 seconds and kept stale-response checks and the visible observation age. |
