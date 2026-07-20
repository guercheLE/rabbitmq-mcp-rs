//! One method per MCP prompt. See docs/mcp-prompts-workflow-plan.md for the
//! design rationale (agnostic phrasing, whole-sub-workflow delegation,
//! content-size targets) that every `content/*.md` file must follow.

use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{PromptMessage, Role};
use rmcp::{prompt, prompt_router};

use crate::core::mcp_server::McpifyServer;
use crate::prompts::{
    DeadLetterWorkflowArgs, DefinitionsBackupRestoreWorkflowArgs, MasterWorkflowArgs,
    render_context_header,
};

#[prompt_router(vis = "pub(crate)")]
impl McpifyServer {
    #[prompt(
        name = "rabbitmq_workflow",
        description = "Start here. Presents the available RabbitMQ management workflows, \
                        routes to the right guided sub-workflow based on the user's goal, \
                        and — where the environment supports it — delegates that whole \
                        sub-workflow to an isolated sub-task to spare this conversation's \
                        context window."
    )]
    async fn rabbitmq_workflow_prompt(
        &self,
        Parameters(args): Parameters<MasterWorkflowArgs>,
    ) -> Vec<PromptMessage> {
        let header = render_context_header(&[("goal", args.goal.as_deref())]);
        vec![PromptMessage::new_text(
            Role::User,
            format!("{header}\n\n{}", include_str!("content/master.md")),
        )]
    }

    #[prompt(
        name = "rabbitmq_workflow_dead_letter",
        description = "Guided, multi-step setup of a dead-letter exchange/queue (DLX/DLQ) for \
                        a RabbitMQ queue, including the create-time-vs-policy decision."
    )]
    async fn rabbitmq_workflow_dead_letter_prompt(
        &self,
        Parameters(args): Parameters<DeadLetterWorkflowArgs>,
    ) -> Vec<PromptMessage> {
        let header = render_context_header(&[
            ("vhost", args.vhost.as_deref()),
            ("source_queue", args.source_queue.as_deref()),
            ("dlx_name", args.dlx_name.as_deref()),
            ("dlq_name", args.dlq_name.as_deref()),
        ]);
        vec![PromptMessage::new_text(
            Role::User,
            format!("{header}\n\n{}", include_str!("content/dead_letter.md")),
        )]
    }

    #[prompt(
        name = "rabbitmq_workflow_queues",
        description = "List/inspect/create/delete/purge queues, queue actions, bindings-on-a-\
                        queue, get/publish messages, rebalance."
    )]
    async fn rabbitmq_workflow_queues_prompt(&self) -> Vec<PromptMessage> {
        vec![PromptMessage::new_text(
            Role::User,
            include_str!("content/queues.md"),
        )]
    }

    #[prompt(
        name = "rabbitmq_workflow_exchanges",
        description = "List/inspect/create/delete exchanges, bindings by source/destination, \
                        publish."
    )]
    async fn rabbitmq_workflow_exchanges_prompt(&self) -> Vec<PromptMessage> {
        vec![PromptMessage::new_text(
            Role::User,
            include_str!("content/exchanges.md"),
        )]
    }

    #[prompt(
        name = "rabbitmq_workflow_bindings",
        description = "List bindings (all/by vhost), bind/unbind exchange↔queue and \
                        exchange↔exchange."
    )]
    async fn rabbitmq_workflow_bindings_prompt(&self) -> Vec<PromptMessage> {
        vec![PromptMessage::new_text(
            Role::User,
            include_str!("content/bindings.md"),
        )]
    }

    #[prompt(
        name = "rabbitmq_workflow_vhosts",
        description = "Vhost lifecycle, per-vhost limits, deletion protection, per-vhost \
                        channels/connections."
    )]
    async fn rabbitmq_workflow_vhosts_prompt(&self) -> Vec<PromptMessage> {
        vec![PromptMessage::new_text(
            Role::User,
            include_str!("content/vhosts.md"),
        )]
    }

    #[prompt(
        name = "rabbitmq_workflow_users_permissions",
        description = "User lifecycle, bulk-delete, vhost/topic permissions, per-user \
                        limits/queues."
    )]
    async fn rabbitmq_workflow_users_permissions_prompt(&self) -> Vec<PromptMessage> {
        vec![PromptMessage::new_text(
            Role::User,
            include_str!("content/users_permissions.md"),
        )]
    }

    #[prompt(
        name = "rabbitmq_workflow_policies",
        description = "Policies and operator-policy overrides (cross-references dead-letter/HA/\
                        TTL use cases)."
    )]
    async fn rabbitmq_workflow_policies_prompt(&self) -> Vec<PromptMessage> {
        vec![PromptMessage::new_text(
            Role::User,
            include_str!("content/policies.md"),
        )]
    }

    #[prompt(
        name = "rabbitmq_workflow_federation_shovel",
        description = "Explains the parameters/global-parameters indirection for federation \
                        upstreams and shovels; read-only federation-links status."
    )]
    async fn rabbitmq_workflow_federation_shovel_prompt(&self) -> Vec<PromptMessage> {
        vec![PromptMessage::new_text(
            Role::User,
            include_str!("content/federation_shovel.md"),
        )]
    }

    #[prompt(
        name = "rabbitmq_workflow_definitions_backup_restore",
        description = "Export/import full-cluster or per-vhost definitions."
    )]
    async fn rabbitmq_workflow_definitions_backup_restore_prompt(
        &self,
        Parameters(args): Parameters<DefinitionsBackupRestoreWorkflowArgs>,
    ) -> Vec<PromptMessage> {
        let header = render_context_header(&[("vhost", args.vhost.as_deref())]);
        vec![PromptMessage::new_text(
            Role::User,
            format!(
                "{header}\n\n{}",
                include_str!("content/definitions_backup_restore.md")
            ),
        )]
    }

    #[prompt(
        name = "rabbitmq_workflow_monitoring_diagnostics",
        description = "Thin pointer to the right read-only signal (connections, channels, \
                        consumers, streams, health checks, overview, auth attempts, whoami)."
    )]
    async fn rabbitmq_workflow_monitoring_diagnostics_prompt(&self) -> Vec<PromptMessage> {
        vec![PromptMessage::new_text(
            Role::User,
            include_str!("content/monitoring_diagnostics.md"),
        )]
    }
}
