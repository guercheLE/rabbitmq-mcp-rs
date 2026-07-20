# RabbitMQ management workflows

This server also exposes `search`/`get`/`call` directly — use this menu
when a task needs more than one call, in a specific order, or has a
non-obvious gotcha worth walking through step by step.

If a `goal` was supplied above, match it against the menu below and go
straight to that sub-workflow. Otherwise, show this menu to the user and
ask which task they want help with.

**Once you've picked a sub-workflow: if your environment provides a way
to run a sub-task in an isolated context (e.g. an agent/task tool),
delegate the entire sub-workflow to it** — hand the sub-task the
sub-workflow's prompt name below plus whatever parameters are already
known, let it fetch that prompt (`prompts/get`) and carry out every step
itself, and have it report back only a short summary. This keeps the
sub-workflow's full `search`/`get`/`call` trace out of this conversation.
If no such mechanism is available, run the sub-workflow's steps directly
here instead.

## Menu

- **`rabbitmq_workflow_queues`** — list, inspect, create, delete, or purge
  queues; queue actions; messages; rebalance.
- **`rabbitmq_workflow_exchanges`** — list, inspect, create, or delete
  exchanges; publish a message.
- **`rabbitmq_workflow_bindings`** — list, create, or remove bindings
  between exchanges and queues, or between exchanges.
- **`rabbitmq_workflow_dead_letter`** — set up a dead-letter
  exchange/queue (DLX/DLQ) for a queue, including the create-time-vs.
  -policy decision. Use this rather than `queues`/`exchanges`/`bindings`
  individually when the goal is specifically dead-lettering.
- **`rabbitmq_workflow_vhosts`** — virtual host lifecycle, limits,
  deletion protection.
- **`rabbitmq_workflow_users_permissions`** — user lifecycle, vhost and
  topic permissions, per-user limits.
- **`rabbitmq_workflow_policies`** — policies and operator-policy
  overrides (HA, TTL, message-size limits, and policy-based dead-letter).
- **`rabbitmq_workflow_federation_shovel`** — federation upstreams and
  shovels (configured indirectly, via generic parameters).
- **`rabbitmq_workflow_definitions_backup_restore`** — export/import the
  full cluster's or one vhost's definitions.
- **`rabbitmq_workflow_monitoring_diagnostics`** — connections, channels,
  consumers, streams, health checks, node/cluster status.
- **`rabbitmq_workflow_upgrade_readiness`** — is it safe to restart a
  node, restart the cluster, or upgrade RabbitMQ; checks deprecated
  features, feature flags, and health, then confirms recovery after.

Every sub-workflow above describes RabbitMQ operations only by what they
do (e.g. "search for how to create a queue"), never by a specific
operationId or an assumed response field — the exact operation id, and
even the response shape for the same id, can differ depending on which
RabbitMQ API version this server is configured for. Always confirm the
current schema via `get` before relying on a field name.
