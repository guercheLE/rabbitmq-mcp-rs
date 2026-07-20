# Sub-workflow: Exchanges

This sub-workflow is self-contained and delegable: if you were routed
here from `rabbitmq`, or your environment supports running
sub-tasks in an isolated context, this prompt's own text is everything
you need — report back only a short summary when done.

Covers: listing/inspecting exchanges, creating, deleting, listing the
bindings where an exchange is the source or the destination, and
publishing a message directly to an exchange.

For each task: search for how to do it in natural language (e.g.
"search for how to create an exchange", "search for how to publish a
message to an exchange"), call the matching operation, and confirm the
result via a follow-up search-and-call before telling the user it's
done. Never hardcode an operationId or assume a specific response field
name — both can differ across this server's supported RabbitMQ API
versions; always read the current schema via `get`.

Ask for the virtual host and exchange name whenever they aren't already
known. If creating an exchange, also confirm the exchange type (direct,
fanout, topic, or headers) — ask the user's intended routing pattern if
they haven't said, rather than defaulting silently.

If the goal is specifically setting up a dead-letter exchange, use
`rabbitmq-dead-letter` instead of doing it here — it covers the
full exchange+queue+binding sequence and the create-time-vs-policy
decision this exchange-only prompt doesn't.

If the goal involves federating an exchange to another cluster, that's
`rabbitmq-federation-shovel`, not this prompt — exchange
creation here only covers a single local cluster.
