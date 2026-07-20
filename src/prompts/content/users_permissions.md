# Sub-workflow: Users & permissions

This sub-workflow is self-contained and delegable: if you were routed
here from `rabbitmq_workflow`, or your environment supports running
sub-tasks in an isolated context, this prompt's own text is everything
you need — report back only a short summary when done.

Covers: listing/inspecting users, creating, deleting, bulk-delete,
vhost-scoped permissions (configure/write/read), topic permissions, and
per-user limits (e.g. max channels/connections).

For each task: search for how to do it in natural language (e.g.
"search for how to create a user", "search for how to set a user's
permissions on a virtual host"), call the matching operation, and
confirm the result via a follow-up search-and-call before telling the
user it's done. Never hardcode an operationId or assume a specific
response field name — both can differ across this server's supported
RabbitMQ API versions; always read the current schema via `get`.

**Gotcha:** creating a user does not grant them access to any virtual
host — that's a separate permissions call, scoped to a specific vhost.
If the user's goal is "let this user use this vhost," you need both the
user-create step and a permissions step; don't stop after just one.

Never ask the user to paste a plaintext password into this
conversation for you to relay verbatim if a hashing option is available
— search for how to hash a password first and use the hash, consistent
with how RabbitMQ itself expects user credentials to be provisioned.

Bulk-deleting users is destructive and hard to reverse — confirm the
exact list with the user before calling it, especially if it came from
a broad search rather than an explicit list they gave you.
