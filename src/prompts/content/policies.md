# Sub-workflow: Policies & operator policies

This sub-workflow is self-contained and delegable: if you were routed
here from `rabbitmq`, or your environment supports running
sub-tasks in an isolated context, this prompt's own text is everything
you need — report back only a short summary when done.

Covers: listing/inspecting/creating/deleting policies and operator-policy
overrides. A policy matches queues/exchanges by name pattern within a
vhost and applies a definition (e.g. high availability, TTL, max-length,
message-size limits, or a dead-letter-exchange) without needing to
recreate the matched resources — this is what makes policies the right
tool for changing behavior on resources that already exist and can't be
recreated.

For each task: search for how to do it in natural language (e.g.
"search for how to create a policy"), call the matching operation with
the vhost, a name pattern, and a definition, and confirm it applied
(search for how to inspect the matched queue/exchange, or list policies,
and check) before telling the user it's done. Never hardcode an
operationId or assume a specific response field name — both can differ
across this server's supported RabbitMQ API versions; always read the
current schema via `get`.

Ask the user to confirm the exact name pattern before creating a policy
— an overly broad pattern can silently apply to more resources than
intended. Prefer an exact-name pattern unless the user explicitly wants
to match multiple resources.

Operator policies are a narrower override mechanism layered on top of
regular policies (e.g. capping a value a regular policy sets less
strictly) — if the user just says "policy" without qualifying it, use a
regular policy unless something about their goal specifically calls for
an operator override.

If the goal is specifically dead-lettering, `rabbitmq-dead-letter`
walks through the policy-based path for that one case in more detail —
prefer it over improvising the policy definition here from scratch.
