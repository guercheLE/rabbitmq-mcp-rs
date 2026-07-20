# Sub-workflow: Virtual hosts

This sub-workflow is self-contained and delegable: if you were routed
here from `rabbitmq_workflow`, or your environment supports running
sub-tasks in an isolated context, this prompt's own text is everything
you need — report back only a short summary when done.

Covers: listing/inspecting virtual hosts, creating, deleting, per-vhost
limits (max connections, max queues), deletion protection, starting a
vhost on a specific node, and listing the channels/connections open in
a given vhost.

For each task: search for how to do it in natural language (e.g.
"search for how to create a virtual host", "search for how to set a
per-vhost connection limit"), call the matching operation, and confirm
the result via a follow-up search-and-call before telling the user it's
done. Never hardcode an operationId or assume a specific response field
name — both can differ across this server's supported RabbitMQ API
versions; always read the current schema via `get`.

**Gotcha:** deleting a vhost deletes every queue, exchange, and binding
inside it. If deletion protection is available and the user is deleting
a vhost they didn't just create in this conversation, ask them to
confirm before proceeding — this is a destructive, hard-to-reverse
operation.

If the user only wants to manage who can access a vhost (not the vhost
itself), that's `rabbitmq_workflow_users_permissions`, not this prompt.

If the goal is checking whether it's safe to restart a node or the
cluster (starting a vhost on a node is often a post-restart step), use
`rabbitmq_workflow_upgrade_readiness` to drive that sequence — it
delegates the actual "start a vhost on a node" call back to the
technique described here.
