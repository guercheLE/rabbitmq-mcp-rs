# Sub-workflow: Queues

This sub-workflow is self-contained and delegable: if you were routed
here from `rabbitmq`, or your environment supports running
sub-tasks in an isolated context, this prompt's own text is everything
you need — report back only a short summary when done.

Covers: listing/inspecting queues, creating, deleting, purging, queue
actions (e.g. sync/cancel-sync a mirrored/quorum queue), the bindings on
a queue, fetching messages, publishing, and rebalancing queues across a
cluster.

For each task: search for how to do it in natural language (e.g.
"search for how to create a queue", "search for how to purge a queue"),
call the matching operation, and confirm the result via a follow-up
search-and-call before telling the user it's done — never assume
success just because the call didn't error, and never hardcode an
operationId or a specific response field name (both can differ across
this server's supported RabbitMQ API versions; always read the current
schema via `get`).

Ask for the virtual host and queue name whenever they aren't already
known — almost every queue operation needs both.

**Gotcha:** queue arguments (e.g. TTL, max-length, dead-letter settings)
are set at creation time and are immutable afterward — RabbitMQ has no
"alter queue arguments" operation. If the user wants to change one on an
existing queue, either recreate the queue or use a policy instead (see
`rabbitmq-policies`); don't attempt an in-place argument edit.

If the goal is specifically dead-lettering, use
`rabbitmq-dead-letter` instead of doing it here — it covers the
full exchange+queue+binding sequence and the create-time-vs-policy
decision this queue-only prompt doesn't.

Listing all queues (or "detailed" queue listings) can return a large,
paginated result — if your environment supports delegating that one
step to a sub-task and getting back only a filtered/summarized answer,
do so rather than pulling a long listing into this conversation.

**Stream queues:** a stream is just a queue created with a
`x-queue-type: stream` argument (plus stream-specific arguments like
retention). Create it the same way as any other queue — search for how
to create a queue, and set the type argument — rather than looking for
a separate "create stream" operation, which doesn't exist. Read-only
status for stream connections/consumers/publishers is covered by
`rabbitmq-monitoring-diagnostics`, not here.
