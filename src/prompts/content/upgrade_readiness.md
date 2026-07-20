# Sub-workflow: Upgrade / restart readiness

This sub-workflow is self-contained and delegable: if you were routed
here from `rabbitmq_workflow`, or your environment supports running
sub-tasks in an isolated context, this prompt's own text is everything
you need — report back only a short summary when done.

Goal: assess whether it's safe to restart a node, restart the whole
cluster, or upgrade RabbitMQ itself, and confirm recovery afterward.

Do not skip ahead — advance only once the previous step's goal is
confirmed, not merely attempted.

## Step 1 — Scope

Check the "Context already provided" header above for a `node`. If
present, this is a check for restarting that specific node; if absent,
ask whether the user wants a cluster-wide check or a specific node,
then proceed with whichever they choose.

## Step 2 — Run the independent readiness checks (parallelizable, delegate if possible)

None of these depend on each other — if your environment supports
running sub-tasks in an isolated context, delegate them concurrently
and have each return only a short answer, not the full response body.
Otherwise run them directly, in any order:

- Search for how to list deprecated features currently in use. Any
  result here is a potential blocker — a feature slated for removal
  that this deployment still relies on.
- Search for how to check feature-flag status. Flags not yet enabled
  may need enabling before an upgrade; ask the user if they want that
  done as a separate, explicit step rather than doing it silently here.
- Reuse `rabbitmq_workflow_monitoring_diagnostics`'s health-check
  operations rather than re-deriving them: alarms, quorum-critical
  queues, and (if `node` was given) that node's readiness.

Never hardcode an operationId or assume a specific response field name
— both can differ across the RabbitMQ API versions this server
supports; always read the current schema via `get`.

## Step 3 — Gate: go / no-go

Do not tell the user it's safe to proceed until every Step 2 check has
actually come back clean. If any check is red (deprecated features in
active use, an unresolved alarm, a queue that would lose quorum), say
so explicitly and let the user decide whether to proceed anyway rather
than making that call yourself.

## Step 4 — After the restart (only if the user is proceeding with one)

Once the node or cluster is back: confirm via the readiness health
check that it's actually serving clients again — don't assume a
successful process start means the same thing. If a specific `node`
was in scope, also check whether any vhost needs to be explicitly
started on it (search for how to start a vhost on a node) rather than
assuming vhosts recover automatically.

## Step 5 — Report back

Summarize what was checked, what (if anything) blocked proceeding, and
what was confirmed healthy afterward — not the raw output of every
check.

## Composing with other workflows

The health-check details this prompt reuses in Step 2 and Step 4 are
covered more fully by `rabbitmq_workflow_monitoring_diagnostics` — fetch
it for more detail on an individual check rather than guessing.
