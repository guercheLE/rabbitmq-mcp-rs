# MCP prompts: guided RabbitMQ management workflows

## Context

`rabbitmq-mcp-rs` currently exposes exactly 3 MCP tools — `search`, `get`, `call` — backed by an embedded, per-API-version catalog of RabbitMQ Management HTTP API operations. This is genuinely 5 separate catalogs, one per supported API version (`mcp_store.db.zst` = 4.3.2 [default, 137 ops], plus `mcp_store_v4.2.8.db.zst` [136], `_v4.1.8` [137], `_v4.0.9` [134], `_v3.13.7` [134] — each with its own `generated_schemas_v*.json.zst` mirroring that version's input/output JSON Schemas, used only for `call` validation). Verified directly against all 5 stores: only 130 `operationId`s are common to every version at all (7 operations in 4.3.2 don't exist in 3.13.7, e.g. `deleteApiVhostsNameDeletionProtection` and several health-check variants) — and critically, **even among those 130 shared ids, 16 have a genuinely different input or output schema across versions**. Confirmed example: `getApiChannels`'s `output_schema` in 3.13.7 is a flat object with pagination fields (`page`, `page_count`, `total_count`, ...); in 4.3.2 it's a `oneOf` of a bare array or that same paginated-object shape, with a differently-shaped error response too. So "agnostic" instructions in this feature must avoid hardcoding not just `operationId` names but also assumed response field names — sub-workflow prose should tell the calling LLM to call `get` on whatever operationId `search` resolves to and read the *current* schema from that response, never assume a field name from the instructions themselves.

This flat 3-tool surface is powerful but leaves all sequencing knowledge — "to set up a dead-letter queue you need an exchange, a queue, a binding, and either queue arguments or a policy, in that order, with a fork depending on whether the queue already exists" — entirely up to whichever LLM is driving the client, re-derived from scratch every session.

The goal is to add an MCP **prompts** capability: a master "menu" prompt plus one prompt per logical RabbitMQ domain (queues, exchanges, bindings, dead-letter setup, vhosts, users/permissions, policies, federation/shovel, definitions backup/restore, monitoring). Each prompt returns instructional prose that guides the calling LLM through a domain's task step by step — asking for missing parameters, gating progression until a step's goal is actually verified (not just attempted), calling out where steps are independent and can run in parallel, and always describing operations by capability ("search for how to create an exchange") rather than by a specific `operationId` or assumed response shape, for the version-drift reasons above.

This repo is generated output from a sibling `../mcpify` generator (every existing `.rs` file is headed "do not hand-edit"; `mcpify.yaml` has `force: true`). The user explicitly chose to hand-edit this repo directly rather than build the feature into the generator — accepted risk: a future `mcpify` re-run against this project would overwrite these changes.

The mechanism is already available for free: this crate's `rmcp = "2"` dependency resolves to rmcp **2.2.0**, which ships a first-class prompts API (`Prompt`, `PromptArgument`, `PromptMessage`, `GetPromptResult`, `#[prompt_router]`, `#[prompt]`, `#[prompt_handler]`) that mirrors the `#[tool_router]`/`#[tool]`/`#[tool_handler]` pattern `src/core/mcp_server.rs` already uses for `search`/`get`/`call` almost exactly. Verified directly against the vendored crate sources (`~/.cargo/registry/src/.../rmcp-2.2.0` and `rmcp-macros-2.2.0`): `#[prompt_router]` appends a `prompt_router() -> PromptRouter<Self>` associated fn to whatever `impl <Self>` block it decorates (it doesn't need to be the same block as `#[tool_router]`), and `#[tool_handler]`/`#[prompt_handler]` can stack on the same `impl ServerHandler` block since each only contributes its own disjoint set of methods (`call_tool`/`list_tools` vs. `get_prompt`/`list_prompts`).

## Approach

### File layout

Prompt code is kept entirely separate from tool code: all prompt logic lives in a new `src/prompts/` module, distinct from `src/tools/` (which holds `search`/`get`/`call`'s business logic — [search_tool.rs](../src/tools/search_tool.rs), [get_tool.rs](../src/tools/get_tool.rs), [call_tool.rs](../src/tools/call_tool.rs)). The `#[prompt_router]`-decorated `impl McpifyServer` block goes in `src/prompts/router.rs`, never in the same file as the existing `#[tool_router]`-decorated block. [src/core/mcp_server.rs](../src/core/mcp_server.rs) itself is touched only for the minimal wiring a single `ServerHandler`/struct necessarily requires — the new struct field, the stacked handler macro, and the `.enable_prompts()` capability flag — no prompt method bodies or prompt-specific logic are added there.

New module `src/prompts/`, declared from `src/lib.rs` next to the existing `pub mod tools;`:

```
src/prompts/
  mod.rs                        // arg structs + render_context_header() helper (+ its own unit tests)
  router.rs                     // second `impl McpifyServer` block, #[prompt_router]-decorated
  content/
    master.md
    queues.md
    exchanges.md
    bindings.md
    dead_letter.md
    vhosts.md
    users_permissions.md
    policies.md
    federation_shovel.md
    definitions_backup_restore.md
    monitoring_diagnostics.md
```

Instructional prose lives in `.md` files pulled in via `include_str!`, not inline Rust string literals — this follows the pattern the crate already uses for large embedded assets ([store.rs:35](../src/data/store.rs)  `include_bytes!`s each version's `.db.zst`; [validator.rs:41](../src/validation/validator.rs) does the same for schema JSON). As `.rs` string literals this content would fight `rustfmt`, produce noisy diffs, and lose markdown tooling. Anything that varies per-invocation (which optional arguments the caller already supplied) is rendered separately in Rust as a short "Context already provided" header and prepended to the static markdown body — no template-substitution engine needed.

New hand-authored files should **not** carry the "generated by mcpify. Do not hand-edit." header every existing file has — that claim would be false for this module.

### `McpifyServer` changes ([src/core/mcp_server.rs](../src/core/mcp_server.rs))

Add a `prompt_router` field next to the existing `tool_router`, initialized the same way in `new()`:

```rust
#[derive(Clone)]
pub struct McpifyServer {
    api_version: String,
    config: Config,
    auth_manager: Arc<Mutex<AuthManager>>,
    tool_router: ToolRouter<McpifyServer>,
    prompt_router: rmcp::handler::server::router::prompt::PromptRouter<McpifyServer>,
}
```

`PromptRouter<S>` is `Clone`, so the struct's `#[derive(Clone)]` is unaffected. No changes needed at either construction site (`main.rs`'s two `McpifyServer::new(...)` calls, `http/server.rs`'s session factory) — the constructor signature doesn't change.

Stack the handler macros and add `.enable_prompts()`:

```rust
#[tool_handler(router = self.tool_router.clone())]
#[prompt_handler(router = self.prompt_router.clone())]
impl ServerHandler for McpifyServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo::new(
            ServerCapabilities::builder()
                .enable_tools()
                .enable_prompts()
                .build(),
        )
        .with_server_info(Implementation::from_build_env())
        .with_protocol_version(ProtocolVersion::V_2024_11_05)
        .with_instructions(
            "Exposes exactly 3 tools -- search, get, call -- backed by an embedded \
             semantic database, so you never need the full API surface in context. \
             Also exposes MCP prompts -- start with the `rabbitmq_workflow` prompt for \
             guided, multi-step help with common RabbitMQ management tasks."
                .to_string(),
        )
    }
}
```

Add `prompt_handler` to the existing `use rmcp::{... tool_handler, tool_router};` import.

### `src/prompts/router.rs` — one method per prompt

Mirrors the existing `SearchArgs`/`GetArgs`/`CallArgs` + `#[tool(...)]` pattern:

```rust
#[prompt_router]
impl McpifyServer {
    #[prompt(
        name = "rabbitmq_workflow",
        description = "Start here. Presents the available RabbitMQ management workflows, \
                        routes to the right guided sub-workflow based on the user's goal, \
                        and — where the environment supports it — delegates that whole \
                        sub-workflow to an isolated sub-task to spare this conversation's \
                        context window."
    )]
    async fn rabbitmq_workflow_prompt(
        &self,
        Parameters(args): Parameters<MasterWorkflowArgs>,
    ) -> Vec<PromptMessage> {
        let header = render_context_header(&[("goal", args.goal.as_deref())]);
        vec![PromptMessage::new_text(
            Role::User,
            format!("{header}\n\n{}", include_str!("content/master.md")),
        )]
    }

    // one method per sub-workflow, same shape — see prompt inventory below
}
```

Argument structs go in `src/prompts/mod.rs`, `#[derive(Deserialize, schemars::JsonSchema)]` like the existing tool arg structs, every field `Option<String>` with a doc comment (doc comments become each `PromptArgument`'s description via rmcp's `cached_arguments_from_schema`). Prompts with no meaningful arguments (most of the domain prompts) simply omit the `Parameters<T>` extractor from the method signature — the macro emits `arguments: None` automatically when no such extractor is present.

**Why every argument is `Option`, never `required: true`:** MCP prompt arguments are conventionally collected up front by whatever UI a client renders when a prompt is explicitly invoked (e.g. a slash-command form) — not well suited to values that only become known partway through a guided flow, and a strict client would refuse `prompts/get` entirely until a required field is filled. Pushing "ask if missing" into the instructional prose (per the brief's own requirement) instead of transport-level required-argument validation is what makes it work uniformly for agentic clients that never populate prompt arguments at all, and interactive ones whose humans do.

### Prompt inventory

| name | description | arguments |
|---|---|---|
| `rabbitmq_workflow` | Master index; menu + goal-based routing | `goal: Option<String>` |
| `rabbitmq_workflow_queues` | List/inspect/create/delete/purge queues, queue actions, bindings-on-a-queue, get/publish messages, rebalance | none |
| `rabbitmq_workflow_exchanges` | List/inspect/create/delete exchanges, bindings by source/destination, publish | none |
| `rabbitmq_workflow_bindings` | List bindings (all/by vhost), bind/unbind exchange↔queue and exchange↔exchange | none |
| `rabbitmq_workflow_dead_letter` | Guided DLX/DLQ setup, including the create-time-vs-policy fork | `vhost`, `source_queue`, `dlx_name`, `dlq_name` |
| `rabbitmq_workflow_vhosts` | Vhost lifecycle, per-vhost limits, deletion protection, per-vhost channels/connections | none |
| `rabbitmq_workflow_users_permissions` | User lifecycle, bulk-delete, vhost/topic permissions, per-user limits/queues | none |
| `rabbitmq_workflow_policies` | Policies and operator-policy overrides (cross-references dead-letter/HA/TTL use cases) | none |
| `rabbitmq_workflow_federation_shovel` | Explains the `parameters`/`global-parameters` indirection for federation upstreams and shovels; read-only `federation-links` status | none |
| `rabbitmq_workflow_definitions_backup_restore` | Export/import full-cluster or per-vhost definitions | `vhost: Option<String>` |
| `rabbitmq_workflow_monitoring_diagnostics` | Thin pointer to the right read-only signal (connections, channels, consumers, streams, health checks, overview, auth attempts, whoami) — deliberately not a multi-step guided flow, kept as its own prompt purely for `prompts/list` discoverability | none |

### Whole-sub-workflow delegation (the master prompt's core routing responsibility)

This is the primary lever for sparing the main conversation's context window and tokens — more so than delegating individual steps within one sub-workflow (below). `master.md`'s routing instructions must tell the calling LLM: once you've matched the user's goal (or the menu selection) to one of the 10 sub-workflow prompt names, **if your environment provides a way to run a sub-task/agent in an isolated context, delegate the entire matched sub-workflow to it** — hand that sub-task the sub-workflow's prompt name (e.g. `rabbitmq_workflow_dead_letter`) and whatever parameters are already known, let it fetch that prompt itself (`prompts/get`) and carry out every one of its steps — including all of *its own* `search`/`get`/`call` traffic — entirely within its own context, and have it report back to this conversation only a short summary: what was accomplished/confirmed, and anything it still needs from the user. Only fall back to running the sub-workflow's steps directly in the current context if no such delegation mechanism is available.

This is what actually keeps a multi-step guided workflow's full tool-call trace (potentially dozens of `search`/`get`/`call` round-trips, each with its own request/response JSON) out of the main conversation — a single sub-workflow like `rabbitmq_workflow_dead_letter` can easily produce far more intermediate tool traffic than the final summary needs to convey. Every sub-workflow's own `content/*.md` should open with a short note reflecting this too (see the worked example below): it's designed to be handed to a fresh sub-task with just its own prompt text plus known parameters, self-contained enough that the sub-task doesn't need any of the master conversation's other history to execute it.

The finer-grained, step-level delegation described further below (e.g. delegating a single verbose `search` or a large listing within one sub-workflow) is a secondary tactic that still applies *within* whichever context ends up actually executing the sub-workflow's steps — the delegated sub-task, if there is one, or the main conversation, if not.

### The agnostic-phrasing rule (applies to every prompt, not just the worked example)

Every operation reference in every `content/*.md` file must be phrased as a *task to search for*, never as a specific tool/operation name — e.g. write `search for "how to create a queue?"`, not `call "createQueue"` or `call putApiQueuesVhostName`. This isn't a style preference: it's required by the version-drift found and confirmed above — 7 operations differ in which ids even exist across the 5 supported API versions, and 16 more share an id but return a genuinely different schema (the `getApiChannels` example). A prompt that names a concrete `operationId` or asserts a specific response field name can silently be wrong depending on which `api_version` the server is configured for. Phrasing every step as a natural-language search query, followed by "read the schema `get` returns before relying on any field name," keeps every prompt correct regardless of which of the 5 catalogs is active. Treat this as a hard rule to check for in review, not just a default.

### Content design pattern (worked example: `rabbitmq_workflow_dead_letter`)

`src/prompts/content/dead_letter.md` must demonstrate every element the brief asked for — use this shape for every sub-workflow, not just this one:

- **Opening note — this sub-workflow is self-contained and delegable.** Before Step 0: "This sub-workflow is designed to be run as an isolated sub-task where possible — if you were delegated here from `rabbitmq_workflow`'s routing, or your environment otherwise supports running this as its own sub-task, everything you need is in this prompt's own text plus the parameters already listed above; report back only a short summary when done rather than the full step-by-step trace." This is what makes whole-sub-workflow delegation (see above) actually work: a sub-task picking up this prompt shouldn't need any of the main conversation's other context to execute it.
- **Step 0 — gather required parameters.** Check the prepended "Context already provided" header first; only ask the user for what's still listed as missing. Don't proceed to Step 1 until all are known.
- **Step 1 — an explicit fork with a disambiguating question.** RabbitMQ queue arguments are immutable after declaration, so DLX/DLQ setup genuinely forks: (A) create-time (queue doesn't exist yet or can be recreated) — set `x-dead-letter-exchange`/`x-dead-letter-routing-key` as queue-declare arguments; (B) policy-based (queue exists and must not be recreated — the common production case) — apply a policy with a `dead-letter-exchange` definition, matched by name pattern. Ask "does the source queue already exist, and must it not be recreated?" rather than guessing.
- **Step 2 — parallelizable, independent sub-steps, delegate if possible.** Creating the DLX exchange and the DLQ queue don't depend on each other (only the binding in Step 3 needs both) — call this out explicitly as safe to do concurrently, *and* as a candidate for delegation: "if your environment provides a way to run a sub-task in its own context (e.g. an agent/task tool), delegate 'create the DLX exchange' and 'create the DLQ queue' as two separate sub-tasks and have each return only a short confirmation — don't pull the full create-call request/response bodies into this conversation. If no such sub-task mechanism is available, just do both calls directly." Every operation reference here is phrased as "search for how to create an exchange in a given virtual host, then call the matching operation" — never a hardcoded `operationId` (see the agnostic-phrasing rule above). Gate: don't proceed until both resources are confirmed to exist (via a follow-up search-and-call, not just "the call didn't error").
- **Step 3 — the binding**, gated on Step 2's resources being confirmed.
- **Step 4 — apply the DLX to the source queue**, branching on the Step 1 fork, gated on confirming the setting actually took effect.
- **Step 5 — summarize and offer live verification** (publish-and-check).
- **Composing with other workflows** — steps 2–3 overlap with `rabbitmq_workflow_exchanges`/`rabbitmq_workflow_queues`/`rabbitmq_workflow_bindings`; tell the calling LLM to fetch those prompts by name for more detail rather than duplicating their content here.

Every other sub-workflow's `.md` should follow this same skeleton: numbered steps, an explicit "don't proceed until X is confirmed" gate per step, agnostic search-language instructions, and a call-out of any genuinely independent sub-steps as parallelizable.

**Step-level delegation and parallelization — secondary to whole-sub-workflow delegation above, but still needed within whatever context runs the steps.** The brief asks explicitly for both "delegation and parallelization to improve performance and spare context windows and tokens." Whole-sub-workflow delegation (above) is the primary mechanism for that; this is the finer-grained complement, for individual steps *within* a sub-workflow (whether it ends up executing inside a delegated sub-task or, absent one, directly in the main conversation):
- *Parallelization*: independent steps (or independent parts of one step) can be issued concurrently instead of sequentially — the DLX-exchange/DLQ-queue pair above.
- *Step-level delegation*: for any single step whose own tool traffic would be verbose relative to what the workflow actually needs back (a `search` over many candidates before picking one, reading a large `output_schema`, paging through a long listing to filter it down, or the two independent creates above), the prose should tell the calling LLM to push *that step* into a further sub-task if the host environment offers one, and bring back only the distilled result (the resolved `operationId`, the one field that matters, a yes/no) rather than letting the full intermediate tool output accumulate. Phrase this conditionally, since not every MCP client has a sub-task mechanism: "if your environment supports running an isolated sub-task, delegate X and bring back only Y; otherwise do it directly here." Every sub-workflow with a step that plausibly produces a large or exploratory tool response (most obviously `rabbitmq_workflow_monitoring_diagnostics`'s listings, `rabbitmq_workflow_definitions_backup_restore`'s full-cluster export, and any `search` with many candidate matches) should include this instruction at that step, not only the two-independent-creates case in `dead_letter.md`.

### Content size and token economy

MCP's two-phase discovery model already bounds most of the cost here, and the design should lean on that rather than fight it:

- `prompts/list` (what a client calls to populate a picker or to let the calling LLM see what's available) returns only `name` + `description` + `arguments` for all 11 prompts — a few lines each, no body content. This is the only "all prompts at once" cost there is, and it's small by construction.
- `prompts/get` is per-prompt and on-demand — a client/LLM only pays for the one workflow's markdown body it actually fetches, never all 11 at once. This is the same shape as `search`→`get` already: cheap discovery, then a single targeted fetch.

Given that, the actual lever is keeping each individual `content/*.md` proportional to its domain's real complexity, not padding every prompt to the same shape as the worked `dead_letter.md` example above:

- **Multi-resource, order-dependent domains** (`dead_letter`, `definitions_backup_restore`, `federation_shovel`'s parameters-indirection explanation) genuinely need the numbered-step/gate/fork treatment and can run longer — but even these should target roughly **60–120 lines**, not 200+. If a domain's steps start sprawling past that, that's a signal it should be split into its own sub-workflow rather than grown in place.
- **Single-resource CRUD domains** (`rabbitmq_workflow_vhosts`, `rabbitmq_workflow_users_permissions`, `rabbitmq_workflow_policies`, `rabbitmq_workflow_queues`, `rabbitmq_workflow_exchanges`, `rabbitmq_workflow_bindings`) don't have the cross-resource dependencies that justify heavy step-gating — these should be short, roughly **20–50 lines**: what the domain covers, the agnostic search-language pattern to use, and 1-2 sentences on any real gotcha (e.g. queue-argument immutability), not a padded numbered-step scaffold for what's really a single search-then-call action.
- **`rabbitmq_workflow_monitoring_diagnostics`** should be the shortest of all — a single paragraph, as already scoped in the prompt inventory.
- **`master.md`** must stay a lean menu: one line per sub-workflow (name, one-sentence when-to-use) plus brief goal-matching guidance, not a summary of each sub-workflow's internal steps — that detail belongs solely in the sub-workflow's own prompt, fetched on demand. Target **under 60 lines**.

These are targets to keep content proportional and reviewable, not hard limits enforced by code — call it out in review if a draft `.md` file overshoots its band without a real reason (e.g. a domain turning out to be more compound than initially scoped).

## Critical files

- `docs/mcp-prompts-workflow-plan.md` (new) — this plan, persisted into the repo as the first implementation step (see Sequencing step 0)
- [src/core/mcp_server.rs](../src/core/mcp_server.rs) — struct field, macro stacking, capabilities, import
- [src/lib.rs](../src/lib.rs) — `pub mod prompts;` declaration
- `src/prompts/mod.rs` (new) — argument structs, `render_context_header` helper + its own unit tests (`#[cfg(test)] mod tests`, separate from any tool test)
- `src/prompts/router.rs` (new) — the `#[prompt_router]`-decorated `impl McpifyServer` block, one method per table row above
- `src/prompts/content/*.md` (new, 11 files) — one per prompt; `master.md` and `dead_letter.md` written last-and-first respectively (see sequencing)
- `tests/prompts_workflow.rs` (new) — protocol-level `prompts/list`/`prompts/get` integration tests, kept out of `src/core/mcp_server.rs`'s existing test module entirely (see Verification)
- Reuse as reference patterns (no changes needed): [src/tools/search_tool.rs](../src/tools/search_tool.rs), [src/tools/get_tool.rs](../src/tools/get_tool.rs) for the existing tool-method shape; [src/data/store.rs](../src/data/store.rs) and [src/validation/validator.rs](../src/validation/validator.rs) for the established `include_bytes!`-for-large-embedded-assets convention this plan extends to `include_str!`; [tests/cli_smoke.rs](../tests/cli_smoke.rs)/[tests/runtime_paths.rs](../tests/runtime_paths.rs) for this repo's existing top-level-`tests/`-integration-test convention, which `tests/prompts_workflow.rs` follows

## Sequencing

0. **Persist this plan into the repo** as `docs/mcp-prompts-workflow-plan.md` (this repo already has a `docs/` folder — [docs/SCHEMA_VERSIONS.md](SCHEMA_VERSIONS.md), [docs/api-sources.md](api-sources.md)), so the design record lives with the code it describes rather than only in an ephemeral planning file outside the repo. Do this first, before any code changes.
1. **Vertical slice**: wire up the struct field, macro stacking, `.enable_prompts()`, and implement only `rabbitmq_workflow` + `rabbitmq_workflow_dead_letter` (with their `content/*.md`). Exercises every integration point at once.
2. **Stand up `tests/prompts_workflow.rs` and verify** the vertical slice through it before writing more content (see Verification below) — this is also where the new file's transport/client scaffolding gets written once, for the remaining prompts' tests to extend rather than re-invent.
3. **Fill in the remaining 9 sub-workflow prompts** one at a time — pure content-design work once step 1 is proven, since they all share the same plumbing.
4. **Finalize `master.md`** last, once every prompt name is stable, so its menu references real names.

## Verification

- `cargo build` / `cargo test` from the repo root after each stage above.
- **Prompt tests stay physically separate from tool tests** — nothing prompt-related is added to `src/core/mcp_server.rs`'s existing `#[cfg(test)] mod tests` (which stays scoped to `search`/`get`/`call`, unchanged except for the one capabilities-flag assertion below). Two new, separate test locations instead:
  - **`tests/prompts_workflow.rs`** (new top-level integration test file, following the same convention as [tests/cli_smoke.rs](../tests/cli_smoke.rs)/[tests/runtime_paths.rs](../tests/runtime_paths.rs)) — protocol-level tests against the crate's public API (`rabbitmq_mcp::core::mcp_server::McpifyServer`, an `rmcp::ClientHandler` stub, `tokio::io::duplex`, the same pattern `mcp_protocol_routes_search_get_and_call_requests` already uses, just promoted to its own file/compilation unit rather than an inline unit test):
    - `prompts/list` shape: assert `client.list_all_prompts()` returns all 11 names under the shared `rabbitmq_workflow*` prefix, and that `rabbitmq_workflow_dead_letter`'s advertised arguments include `vhost`/`source_queue`/`dlx_name`/`dlq_name`, all with `required == Some(false)`.
    - `prompts/get` round-trip for `rabbitmq_workflow` with no arguments — assert success and that the returned text mentions `rabbitmq_workflow_dead_letter` (proves the menu links to it).
    - `prompts/get` round-trip for `rabbitmq_workflow_dead_letter` with partial arguments (e.g. `vhost` + `source_queue` supplied, `dlx_name`/`dlq_name` omitted) — assert the rendered header both echoes the supplied values and lists the still-missing ones.
    - Extend or duplicate `server_info_advertises_the_generated_tool_surface`'s capabilities assertion here too: `info.capabilities.prompts.is_some()` (the existing tools-side assertion in `mcp_server.rs` is left as-is; this is a new, prompts-specific assertion in the new file, not a shared test).
  - **`src/prompts/mod.rs`**'s own `#[cfg(test)] mod tests` — pure unit test for `render_context_header` covering: empty slice, all-supplied, all-missing, mixed. Pure logic, no transport, so it doesn't need the integration-test harness.
- Manual smoke check: `cargo run -- start` (stdio) and, separately, `cargo run -- http` with an MCP-capable client that supports `prompts/list`/`prompts/get`, to confirm the master → dead-letter cross-reference reads naturally to a real calling LLM, not just structurally valid per the automated tests.

## Release (once implementation is complete and `cargo test` passes)

This repo's existing convention, confirmed from git history and `.github/workflows/release.yml`: releases are tag-driven (`push: tags: "v*.*.*"` triggers cargo-dist's build/publish job; no separate version-bump automation script exists in `scripts/`), and every past release follows the same two-commit-then-tag shape (e.g. `chore(release): bump version to 0.4.7`, tag `v0.4.7`). Follow it exactly:

1. `git commit` the implementation changes with a conventional-commit message (e.g. `feat(prompts): add guided RabbitMQ workflow prompts` — confirm the exact `type(scope)` against this repo's actual recent history at commit time, don't assume `feat` is right without checking).
2. `git commit` `docs/mcp-prompts-workflow-plan.md` as its own separate commit (e.g. `docs: add MCP prompts workflow implementation plan`) — kept apart from the implementation commit per the user's explicit instruction, mirroring the file-separation principle applied throughout this plan.
3. Bump `version` in `Cargo.toml` (and let `Cargo.lock` follow via `cargo check`/`cargo build`), commit as `chore(release): bump version to X.Y.Z` — matching every prior release commit's exact message shape. Current version is `0.4.8`; this repo's history bumps the patch component per release regardless of change size (`0.4.7` → `0.4.8`), so default to `0.4.9` unless the implementation commit's conventional-commit type argues for a minor bump instead — use judgment at execution time, don't hardcode this without checking what actually landed.
4. `git tag vX.Y.Z` on that bump commit (matching the `v*.*.*` pattern `release.yml` listens for).
5. `git push` the branch, then `git push --tags` (or `git push origin vX.Y.Z`) — confirm with the user before pushing, per this session's standing rule that pushes and tag creation are confirmed, not assumed.

---

## Addendum (2026-07-20): `rabbitmq_workflow_upgrade_readiness` + README documentation

Shipped as `v0.5.0`, tested, and confirmed working end-to-end (real stdio JSON-RPC `initialize`/`prompts/list`/`prompts/get` round trip). This addendum covers the first follow-up round: a systematic gap-analysis pass over the full operation catalog for missed workflow candidates, plus documenting the feature in `README.md`.

### Gap-analysis method

Cross-checked every operation_id in the default 137-operation (4.3.2) catalog against the coverage described in all 10 existing `content/*.md` files, then re-verified each candidate gap actually exists in all 5 supported API versions (4.3.2, 4.2.8, 4.1.8, 4.0.9, 3.13.7) via direct query — confirmed all of them do.

### New workflow: `rabbitmq_workflow_upgrade_readiness`

`getApiDeprecatedFeatures`, `getApiDeprecatedFeaturesUsed`, `getApiFeatureFlags`, and `postApiVhostsNameStartNode` had no existing home and cluster around one real, compound, gated operational task: *is it safe to restart or upgrade a node/cluster, and what needs re-starting afterward?* Same shape of justification as `rabbitmq_workflow_dead_letter` — multiple independent read-only checks (parallelizable/delegable), a go/no-go gate, and a post-action verification step. Added the same way as every other sub-workflow: `content/upgrade_readiness.md` (69 lines, within the 60–120 compound-tier band), a `#[prompt(...)]` method in `router.rs`, an `UpgradeReadinessWorkflowArgs { node: Option<String> }` struct in `mod.rs`, and a `master.md` menu line. Total prompt count: 12.

### Enrichments folded into existing files (no new prompts)

Per the content-size/token-economy rule (single-call lookups don't earn a guided workflow): `getApiExtensions`, `getApiGlobalParameters`, and `putApiClusterName` were added to `monitoring_diagnostics.md`'s coverage sentence; stream-type queue creation (`x-queue-type: stream` is a queue-create argument, not a separate operation) got one addendum paragraph in `queues.md`; starting a vhost on a node was added to `vhosts.md` (with a cross-reference from the new upgrade-readiness workflow); and `getApiAllConfiguration`/`postApiAllConfiguration` (the deprecated alias of `/api/definitions`) got a one-line note in `definitions_backup_restore.md` so an agent that finds it via `search` doesn't treat it as a separate feature.

### Considered and rejected

A cross-cutting "verify message flow end-to-end" workflow (publish → confirm routing → consume/purge). Every topology-creating domain (`dead_letter`, `queues`, `exchanges`, `bindings`) already ends its own steps with a "confirm end-to-end" instruction scoped to what it just built; a 13th, generic prompt for this would either duplicate that or be too vague to gate meaningfully on its own.

### README.md

Added a `## Workflows` section (after `## Usage`) documenting the `prompts` capability, the `rabbitmq_workflow` master prompt as the entry point, and a table of all 12 prompt names with one-line descriptions — mirroring the existing `## Configuration` table's style. Revised the intro paragraph to mention prompts alongside the 3 tools, matching `get_info()`'s own instructions text.
