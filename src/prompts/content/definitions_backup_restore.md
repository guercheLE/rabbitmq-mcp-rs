# Sub-workflow: Definitions backup/restore

This sub-workflow is self-contained and delegable: if you were routed
here from `rabbitmq`, or your environment supports running
sub-tasks in an isolated context, this prompt's own text is everything
you need — report back only a short summary when done.

Goal: export or import the set of exchanges, queues, bindings, users,
vhosts, permissions, policies, and parameters as one definitions
document — for backup, migration, or replicating configuration between
clusters.

If `search` surfaces an older `all-configuration` operation instead of
`definitions`, treat it as the same feature under its previous,
deprecated name — don't use both or treat them as different exports.

## Step 0 — Scope: full cluster or one vhost?

Check the "Context already provided" header above for a `vhost` value.
If present, this is a per-vhost export/import (only that vhost's
exchanges/queues/bindings/policies — not users or other vhosts). If
absent, ask the user whether they want the full cluster or just one
vhost, rather than assuming — a full-cluster export includes every
user's credentials (hashed) and every vhost's resources, which is a
meaningfully different, more sensitive operation than a single vhost's.

## Step 1 — Export

Search for how to export the server definitions (full-cluster, if no
`vhost`) or how to export a given virtual host's definitions (if
`vhost` was supplied), then call the matching operation. Never hardcode
an operationId or assume a specific response field name — both can
differ across this server's supported RabbitMQ API versions; always
read the current schema via `get`.

The exported document can be large (every queue, exchange, binding, and
— for a full-cluster export — every user and vhost in the system). If
your environment supports delegating this call to a sub-task and
returning only a summary (counts per resource type, or a saved-location
confirmation) rather than the full document, do so — don't pull a large
definitions export into this conversation's context just to say it
succeeded.

## Step 2 — Import (only if the user asked to restore, not just export)

Confirm with the user which cluster/vhost they intend to import into —
importing overwrites/merges with whatever is already there, and doing
it against the wrong target is hard to reverse. Once confirmed, search
for how to import server definitions (or a given vhost's definitions),
call it with the document from Step 1 (or one the user supplies), and
verify afterward by listing a sample of the resources it should have
created (e.g. search for how to list queues in the target vhost and spot-check).

## Step 3 — Report back

Summarize what was exported or imported (resource counts by type, and
scope — full cluster vs. which vhost), and where the export was saved
if applicable, rather than dumping the raw document into the
conversation.
