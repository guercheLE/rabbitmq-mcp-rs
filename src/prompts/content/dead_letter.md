# Sub-workflow: Dead-letter setup (DLX/DLQ)

Goal: make messages that are rejected, expired (TTL), or dropped for
exceeding a queue length limit land in a dedicated dead-letter queue,
instead of being discarded.

This sub-workflow is self-contained and delegable: if you were routed
here from `rabbitmq`, or your environment supports running
sub-tasks in an isolated context, this prompt's own text plus the
parameters above is everything you need — report back only a short
summary when done, not the full step-by-step trace.

Do not skip ahead. Advance to the next numbered step only once the
previous step's stated goal is confirmed met (i.e., you have actually
observed — via `search`/`get`/`call` — that the resource exists or the
setting is in effect, not merely that you issued the call).

## Step 0 — Gather required parameters

You need four pieces of information before you can proceed. Check the
"Context already provided" section above first; only ask the user for
whatever is still missing there:

1. **vhost** — which virtual host the source queue lives in.
2. **source_queue** — the name of the queue whose messages should be
   dead-lettered.
3. **dlx_name** — a name for the dead-letter exchange (suggest
   `<source_queue>.dlx` if the user has no preference).
4. **dlq_name** — a name for the dead-letter queue (suggest
   `<source_queue>.dlq` if the user has no preference).

Do not proceed to Step 1 until all four are known.

## Step 1 — Decide: create-time vs. policy-based

RabbitMQ queue arguments (including `x-dead-letter-exchange` and
`x-dead-letter-routing-key`) are immutable once a queue is declared.
This means there are two genuinely different paths, and you must ask
the user which applies before continuing:

- **(A) Create-time.** `source_queue` does not exist yet, or the user
  is fine with deleting and recreating it. The dead-letter exchange is
  set as a queue-declare argument directly on `source_queue` itself.
- **(B) Policy-based.** `source_queue` already exists and must not be
  recreated (the common case in production). A *policy* whose
  definition includes `dead-letter-exchange` is applied retroactively,
  matching `source_queue` by name pattern — no queue recreation
  required.

If the user hasn't said which applies, ask: "Does the source queue
already exist, and do you want to avoid recreating it?" A "yes" means
path (B); anything else means path (A). Do not guess.

## Step 2 — Create the DLX exchange and the DLQ queue (parallelizable, delegate if possible)

These two resources have no dependency on each other — only the
*binding* in Step 3 depends on both existing. If your environment
supports running sub-tasks in an isolated context, delegate "create the
DLX exchange" and "create the DLQ queue" as two separate sub-tasks and
have each return only a short confirmation, not the full request/
response bodies. Otherwise just do both calls directly, concurrently
rather than sequentially:

- Exchange: search for how to create an exchange in a given virtual
  host, then call it with `dlx_name` and `vhost`. `fanout` or `direct`
  is fine unless the user wants a specific routing pattern.
- Queue: search for how to create a queue in a given virtual host, then
  call it with `dlq_name` and `vhost`.

Never hardcode an operationId or assume a specific response field name
— both can differ across the RabbitMQ API versions this server
supports. Always call `get` on whatever operationId `search` resolves
to and read its current schema.

Do not proceed to Step 3 until you've confirmed (search for how to
inspect an exchange / a queue and call it) that both `dlx_name` and
`dlq_name` now exist in `vhost`.

## Step 3 — Bind the DLX to the DLQ

Search for how to bind an exchange to a queue, then call it with
source = `dlx_name`, destination = `dlq_name`, vhost = `vhost`. Use an
empty or wildcard routing key unless the user wants selective
dead-lettering by routing key.

Do not proceed to Step 4 until you have confirmed the binding exists
(search for how to list bindings for a queue and check `dlx_name`
appears as a source).

## Step 4 — Apply the dead-letter exchange to the source queue

- **If path (A) (create-time):** the source queue does not exist yet
  — search for how to create a queue, and include the dead-letter
  exchange (and, if the user wants a specific routing key, the
  dead-letter routing key) as queue arguments alongside `source_queue`
  and `vhost`.
- **If path (B) (policy-based):** search for how to create a policy,
  and call it with a pattern that matches `source_queue` (exact name
  or a narrow regex — confirm with the user which), scoped to `vhost`,
  with a definition that sets the dead-letter exchange to `dlx_name`.

Do not tell the user setup is complete until you've confirmed (search
for how to inspect the queue, or how to list policies, depending on
which path was taken) that the dead-letter exchange is actually
attached to `source_queue`.

## Step 5 — Confirm end-to-end

Summarize what was created (`dlx_name`, `dlq_name`, the binding, and how
`source_queue` now points at `dlx_name`), and offer to verify live by
publishing a message that will be rejected or expire and checking
`dlq_name` for its arrival, rather than taking your word for it.

## Composing with other workflows

Steps 2–3 overlap with `rabbitmq-exchanges`,
`rabbitmq-queues`, and `rabbitmq-bindings` — fetch
those prompts for more detail on an individual operation rather than
guessing.
