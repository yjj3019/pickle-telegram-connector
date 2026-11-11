# Architecture & Low-Latency Engine Design

## 1. 1-2s Low-Latency Watcher Mechanism

Traditional polling models query the Telegram Bot API at fixed intervals (e.g. every 1 to 5 minutes), leading to significant delay between when a user sends a message and when the bot responds.

**Pickle Telegram Connector** solves this by leveraging **HTTP Long-Polling** (`getUpdates` with server-side timeout):

```
User (Telegram)                 Telegram Cloud               Pickle Watcher Engine
      |                               |                                 |
      |                               |<==== Holds open TCP socket =====| (timeout=30s)
      |                               |      (zero latency listener)    |
      |-- "오늘 일정" (t=0.0s) ------>|                                 |
      |                               |==== Push payload (t=0.2s) =====>|
      |                               |                                 |-- Process & Formulate (t=0.5s)
      |<-- Reply: "일정 0건" (t=1.0s)-|<==== sendMessage (t=0.8s) =====|
```

1. **Persistent TCP Connection**: The watcher opens a long-polling request with `timeout=30` (or `timeout=50`). Telegram holds the connection open until an update occurs or the timeout expires.
2. **Push Delivery**: When a user messages the bot, Telegram immediately flushes the update down the existing HTTP stream. Latency from user touch to agent receipt is under **0.2 ~ 0.5 seconds**.
3. **Sub-second Dispatch**: The watcher unpacks the update, applies security filters (`owner_ids`), atomically appends it to `queue.jsonl`, updates the cursor offset in `state.json`, and triggers the reply.
4. **File-Lock Concurrency**: Single-instance guarantee is enforced via `fcntl.flock(LOCK_EX | LOCK_NB)`. If a watcher is active, overlapping runs cleanly wait or yield (`LOCKED`).

---

## 2. Supervisor-Watcher Pattern

To balance resource consumption in constrained environments (such as serverless agent platforms or battery-aware containers), the system employs a two-tier supervisor pattern:

```
[ Supervisor Cron (Every 5-10m) ]
          │
          ├── Reads watcher-state.json (Heartbeat age, PID, Term age)
          │
          ├── [Case A: Heartbeat Fresh (<180s) & Term < 50m]
          │       └─► Quiet Exit (0 tokens spent, zero CPU overhead)
          │
          └── [Case B: Watcher Dead / Term Expired / Unhandled Messages]
                  └─► Revive watcher / Clean handover
```

---

## 3. Security & Access Control

1. **Secure Token Ingestion (Pickle Agent Card & CLI Setup)**:
   - **Agent Interface**: Never accepts plaintext tokens in chat threads. Instead, uses the Pickle platform's `ask_user` tool with `kind="otp"` and `service="Telegram Bot Token"`. This renders a single-field masked secure input dialog on screen, keeping secrets out of LLM conversation contexts and logs.
   - **CLI Interface**: `pickle-tg setup` prompts with `getpass.getpass()`, verifies connection with Telegram `getMe`, and writes `local.json` with strict `0600` permissions.
2. **Private Chat Whitelist**: `owner_ids` restricts direct messaging to specific user IDs (e.g., `123456789`). Unauthorized private messages are rejected without acknowledgement and logged to `dropped.log`.
3. **Credential Isolation**: Tokens are loaded strictly from environment variables (`TELEGRAM_BOT_TOKEN`) or a non-committed local JSON configuration (`local.json`). No secrets are embedded in source code.
4. **Redirect Denial**: `NoRedirectHandler` prevents SSRF and redirect hijacking attacks on API requests.

---

## 4. Production SLA (≤ 60s) & 30-Second Watcher Cadence

To ensure dependable real-world responsiveness without unbounded agent polling overhead, the system defines a strict, enterprise-grade **Service Level Agreement (SLA ≤ 60s)**:

1. **30-Second Long-Polling Cadence**:
   - Replaces fragile sub-second over-tuning with a rock-solid **30-second polling cadence** (`long_poll_timeout=30`).
   - Telegram server flushes messages down the open HTTP stream immediately upon receipt (0~30s detection window), yielding complete responses in **under 30~45 seconds** with zero socket thrashing or CPU waste.
2. **2-Minute Pre-Spawn Overlap Handover**:
   - In agentic runtimes with bounded execution terms (e.g. 50 minutes), the supervisor monitors term age (`term_age = now - started_at`).
   - At **minute 48** (2 minutes prior to term expiration, `overlap_lead_seconds=120`), the supervisor flags `overlap_due = True`.
   - The platform pre-spawns the next-generation replacement watcher, warming up its context and memory.
   - When the previous term hits minute 50, it yields `watch.lock` and exits cleanly. The pre-warmed successor immediately claims the lock and opens long-polling.
   - **Result**: Handover gap is reduced from minutes to **under 1 second**, preventing polling dead zones.
3. **Fail-Safe Cron Safety Net**:
   - If an unhandled message lingers in `queue.jsonl` for **> 25 seconds**, the supervisor immediately fires (`exit 0`).
   - The supervisor drains and answers pending messages directly, guaranteeing that even during unexpected worker crashes, no message exceeds the **60-second SLA limit**.

---

## 5. Clean-Room Architecture & Licensing

- **100% Standard Library**: Built exclusively using Python 3 built-in modules (`urllib.request`, `json`, `mimetypes`, `fcntl`, `time`, `os`).
- **Zero External Dependencies**: Zero vulnerability footprint, zero supply-chain risk.
- **MIT License**: Fully independent, clean-room design ensuring clear intellectual property rights and unrestricted deployment in enterprise environments.

---

## 6. Resource & Token Economy (Deployment Recommendations)

When deploying this connector with AI agent runtimes, consider the token/credit economy:

1. **In-Agent Subagent Polling (High Token Consumption)**:
   - Running the watcher as an internal agent loop (e.g. `subagent_spawn`) repeatedly invokes the LLM runtime across polling slices.
   - Even with slice durations of 100~240 seconds, continuous 24/7 background execution incurs significant tool-calling token overhead against daily usage quotas.
   - Furthermore, Bot-to-Bot conversation loops in shared group chats can rapidly compound token usage.
2. **Standalone Linux systemd Daemon (Recommended: 0 Tokens Spent)**:
   - For always-on 24/7 duty, deploy the standalone Python daemon on an enterprise Linux server (e.g., RHEL / Rocky Linux) using the provided `scripts/deploy.sh`.
   - The daemon maintains the persistent long-polling socket natively in Python without triggering any LLM context turns.
   - Simple queries are answered locally with **zero LLM tokens**, and complex delegation tasks invoke the agent API only on-demand, maximizing efficiency and eliminating quota exhaustion.

