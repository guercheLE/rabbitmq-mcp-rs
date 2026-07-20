# Sub-workflow: Monitoring & diagnostics

This is a thin pointer, not a multi-step guided flow — most monitoring
and diagnostic questions are a single search-then-call, not a sequence
with gates or forks. Covers: connections, channels, consumers, streams
(connections/consumers/publishers), the various health checks (alarms,
node readiness, quorum-critical queues, certificate expiration,
listener/protocol availability, and more), node and cluster overview
(including renaming the cluster), management-plugin extensions,
cluster-wide (not vhost-scoped) global parameters, authentication
attempts, and "who am I."

Search for the specific signal the user actually wants (e.g. "search for
how to check if a node is ready to serve clients", "search for how to
list open connections for a user") and call it — don't guess an
operationId or assume a response field name, since both can differ
across this server's supported RabbitMQ API versions; read the current
schema via `get`. If the user's request is vague ("is everything OK?"),
ask which specific signal they care about, or, absent that, check the
general health-check and overview operations rather than every possible
one. If a listing could be large (all connections, all channels across
a busy cluster) and your environment supports delegating that call to a
sub-task that returns only a filtered/summarized answer, prefer that
over pulling the full listing into this conversation.
