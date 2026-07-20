# Sub-workflow: Federation & shovels

This sub-workflow is self-contained and delegable: if you were routed
here from `rabbitmq`, or your environment supports running
sub-tasks in an isolated context, this prompt's own text is everything
you need — report back only a short summary when done.

Goal: move or mirror messages between RabbitMQ clusters (federation) or
run a standing point-to-point message pump between a source and a
destination (a shovel).

## The indirection you need to know about first

Unlike queues, exchanges, and bindings, federation upstreams and shovels
are **not** configured through dedicated create/delete operations in
this API. They're configured through the generic vhost-scoped
*parameters* mechanism, using a specific `component` value:

- Federation upstream: `component` = `federation-upstream`.
- Shovel: `component` = `shovel`.

So every "create a federation upstream" or "create a shovel" task in
this sub-workflow is really "create a parameter with that component,"
and every "list existing upstreams/shovels" task is "list parameters
filtered to that component." Search using that framing — e.g. "search
for how to set a vhost-scoped parameter" — rather than searching for
"create shovel" or "create federation upstream" literally, since no
operation is named that.

There is one exception: reading federation *link status* (is a
configured upstream currently connected, lagging, etc.) does have its
own dedicated, read-only operation — search for how to check federation
link status when the user wants to know whether an already-configured
upstream is working, not how to configure one.

## Steps

1. **Gather parameters.** You need: the vhost, whether this is a
   federation upstream or a shovel, a name for it, and the definition
   (for an upstream: the source cluster's connection URI and any
   exchange/queue-matching options; for a shovel: source and destination
   URIs plus the queue/exchange to move messages from and to). Ask for
   whatever isn't already known — don't guess connection URIs or
   credentials.
2. **Create the parameter.** Search for how to set a vhost-scoped
   parameter, then call it with `component` set to `federation-upstream`
   or `shovel` as appropriate, the chosen name, vhost, and the
   definition object from step 1. Never hardcode an operationId or
   assume a specific response field name — both can differ across this
   server's supported RabbitMQ API versions; always read the current
   schema via `get`.
3. **Confirm it's active.** For a federation upstream, check link status
   (see above) rather than just confirming the parameter was accepted —
   a misconfigured upstream can be "created" successfully but never
   actually connect. For a shovel, search for how to inspect its
   parameter and, if a status signal is available, check that too.
4. **Report back** what was configured and how the user can check on it
   again later (the same status/list operations from step 3), rather
   than assuming it will keep working unattended without being checked.

Listing all federation links or all parameters for a component can
return more entries than the user's goal needs — if your environment
supports delegating that listing-and-filtering to a sub-task, do so
rather than pulling a long list into this conversation.
