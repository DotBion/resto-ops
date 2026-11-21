# Café Ops agent design

Café Ops watches for people waiting to order, checks ambiguous changes, and creates staff tasks with links to the supporting frames. It accepts uploaded footage and webcam frames. The included synthetic replay uses authored observations for a repeatable demo.

## How the live agent works

| Stage | Behavior |
| --- | --- |
| Observe | Sample up to six images from the latest window, then estimate the queue and identify visible people, groups, and evidence frames. |
| Investigate | When a queue may need attention or an active queue may have cleared, check denser samples, a crop, or earlier observations. Use the frames available at that point in the run. |
| Decide | Validate frame references and response fields. Use fresh, sufficiently supported observations to create or resolve a task after the condition persists. Update an active task while the condition persists and allow staff to acknowledge it. |
| Record | Store observations, review outcomes, task changes, and evidence references in SQLite. The dashboard streams events from the backend and opens the corresponding frame when evidence is selected. |

The Gemini observer and verifier both default to `gemini-4-hydrogen` with `LOW` thinking. Set the models independently with `CAFE_OBSERVER_MODEL` and `CAFE_VERIFIER_MODEL`. The default window is five seconds, the minimum analysis cadence is two seconds, and observations older than 20 seconds cannot change tasks. The backend counts request attempts against a budget of 30 per run and 100 per process, including retries. See [.env.example](.env.example) for the settings.

The [model adapter](backend/app/models.py) owns the prompt, structured response validation, and Gemini calls. The [analysis policy](backend/app/analysis.py) owns review triggers and task transitions. The [run manager](backend/app/runs.py) coordinates processing and keeps the newest pending window while a request is in flight. See the [evaluation notes](docs/evaluation.md#verified-results) for the tested scenarios and limits.

## Proposed Carbon closing shift review

The closing review would help a manager reconstruct service issues and choose one change to test next shift. This feature is a proposal.

Send Carbon the shift's structured timeline, backend-calculated metrics, and short timestamped footage around significant events. Include a few quiet or uncertain windows so the review can catch missed queues. The timeline should include queue estimates and ranges, reviews, task creation, acknowledgment and resolution, camera coverage, and recorded staff interventions when available.

Ask Carbon the following questions.

1. When did the queue build and clear? Which backed-up periods recur on comparable shifts? Cite the frames and report gaps where coverage was too sparse to estimate duration.
2. What preceded each buildup? Which evidence supports or weakens explanations such as a burst of arrivals, a stationary line, or pickup traffic mixing with the ordering line?
3. Which alerts were supported or questionable? When did staff acknowledge them, and when did the queue visibly shrink?
4. Did any quiet or uncertain windows show a queue the live system missed?
5. What is one change worth testing on the next comparable shift, and how will the manager measure its effect?

The report should identify the most consequential recurring issue, link its evidence, and suggest one measurable experiment. For example, if pickup customers repeatedly crowd the ordering line around 6 p.m., test a designated pickup area and compare time above the queue threshold during the same hour. Report observed coverage alongside that comparison. Order and handoff timestamps can help distinguish preparation delays from pickup delays. A recorded intervention is needed to connect a staff action to later recovery.
