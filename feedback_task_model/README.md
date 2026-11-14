# Community task/model feedback

Hermes Unlimited can learn from consenting participants instead of running expensive central model benchmarks. The source of observations is local; public contributions are coarse, self-reported aggregates.

**Not sending or recording by default.** The Hermes plugin registers lifecycle observers, but they collect nothing until a participant explicitly enables local publication consent. The observers capture only numeric usage, coarse tool-family category, and whether a turn completed. They do not inspect or store tool arguments, messages, or results. They never classify correctness as verified. Manual `record` calls can supply task-verifier results only with active consent. Only explicit, unexpired consent permits external publication. Consent does not imply model or task execution authority.

## Data protocol (v1)

`record` accepts exactly nine fields: `task_family` (a fixed category), `model` (public model identifier), `verified` (caller claims an outcome was checked), `success`, `completed`, `latency_ms`, `cost_usd` (estimated or null when unknown), `input_tokens`, `output_tokens`. It intentionally rejects prompts, outputs, email addresses, customer IDs, paths, arbitrary task labels, stack traces and tokens/credentials. Events stay locally in `~/.hermes/feedback_task_model/events.jsonl` (mode 0600). The receiver sees only per-model/per-task aggregates of at least 3 observations in a completed 12-hour UTC window. Published groups contain the sample count, claimed verified outcomes, mean latency/cost and token totals; each batch explicitly says `SELF_REPORTED_UNVERIFIED`.

## Usage

Run from the checkout root:

```sh
python3 -m feedback_task_model.feedback status
# After reviewing the contribution terms, explicitly opt in before any recording:
python3 -m feedback_task_model.feedback consent --agree --days 30
printf '%s\n' '{"task_family":"file_lookup","model":"nous/solar-mini4:free","verified":true,"success":true,"completed":true,"latency_ms":1800,"cost_usd":0,"input_tokens":100,"output_tokens":12}' | python3 -m feedback_task_model.feedback record
python3 -m feedback_task_model.feedback preview
python3 -m feedback_task_model.feedback revoke
```

The proposed scheduler invokes `python3 -m feedback_task_model.feedback publish` at **00:05 and 12:05 UTC**, twice per day, without an LLM. It does nothing if consent is absent, expired, revoked, or insufficient observations exist. An atomic local per-window reservation prevents concurrent submissions. A timeout or ambiguous GitHub result leaves a `PENDING_RECONCILIATION` receipt and blocks automatic retries until a human checks whether the Issue was created; never delete these receipts without reconciling the remote result. This guarantee applies per shared local feedback directory, not across multiple machines or profiles. Set `HERMES_FEEDBACK_HOME` for a per-profile data directory.

## Receiver / prerequisite

Target: `rrglab/hermes-unlimited` on GitHub. Publisher uses GitHub Issues, never write access to the repository or PRs containing event logs. **As of 14 Nov 2026, Issues were reported disabled in the target repository.** The publisher returns `NOT_SENT_TARGET_ISSUES_DISABLED` until the repository owner enables Issues. Users also need GitHub CLI `gh` authentication with permission to create issues. No public data is transmitted merely by installing this package. No bypass of receiver configuration is attempted.

The protocol must not be used for covert analytics. Public feedback can be untruthful or gamed; it is not equivalent to independent benchmark certification. Published issues are visible with the GitHub identity of the posting account, even though aggregate payloads omit identities. Users should explicitly understand this before consent.
