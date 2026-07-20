# Sub-workflow: Bindings

This sub-workflow is self-contained and delegable: if you were routed
here from `rabbitmq`, or your environment supports running
sub-tasks in an isolated context, this prompt's own text is everything
you need — report back only a short summary when done.

Covers: listing all bindings (or by virtual host), and binding/unbinding
both exchange↔queue and exchange↔exchange pairs.

Before binding anything, confirm both endpoints already exist — search
for how to inspect an exchange or a queue and check, rather than
assuming a binding call will fail loudly if one is missing (don't rely
on that; confirm first). Do not proceed to the bind/unbind call until
both endpoints are confirmed.

For the bind/unbind itself: search for how to bind an exchange to a
queue, or how to bind two exchanges, depending on which the user needs,
then call the matching operation with the source, destination, virtual
host, and routing key (empty/wildcard if the user wants to catch
everything). Never hardcode an operationId or assume a specific response
field name — both can differ across this server's supported RabbitMQ
API versions; always read the current schema via `get`.

Confirm the binding took effect afterward (search for how to list
bindings and check it appears) before telling the user it's done.

If the goal is specifically dead-lettering, use
`rabbitmq-dead-letter` instead — it covers the full
exchange+queue+binding sequence together, including the fork this
prompt alone doesn't handle.
