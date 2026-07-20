// Protocol-level tests for the MCP `prompts` capability, kept in its own
// file/compilation unit deliberately separate from any tool test — see
// docs/mcp-prompts-workflow-plan.md's file-separation rule.

use rabbitmq_mcp::auth::auth_manager::AuthManager;
use rabbitmq_mcp::core::config_schema::{AuthMethod, Config};
use rabbitmq_mcp::core::mcp_server::McpifyServer;
use rmcp::model::{ContentBlock, GetPromptRequestParams};
use rmcp::{ServerHandler, ServiceExt};
use std::sync::Arc;
use tokio::sync::Mutex;

#[derive(Debug, Clone, Default)]
struct TestClient;

impl rmcp::ClientHandler for TestClient {}

fn server() -> McpifyServer {
    let config: Config = serde_json::from_value(serde_json::json!({
        "url": "https://api.example.test",
        "auth_method": "basic"
    }))
    .unwrap();
    McpifyServer::new(
        "4.3.2".to_string(),
        config,
        Arc::new(Mutex::new(AuthManager::new(AuthMethod::Basic))),
    )
}

async fn connected_client() -> rmcp::service::RunningService<rmcp::RoleClient, TestClient> {
    let (server_transport, client_transport) = tokio::io::duplex(64 * 1024);
    tokio::spawn(async move {
        server().serve(server_transport).await?.waiting().await?;
        anyhow::Ok(())
    });
    TestClient.serve(client_transport).await.unwrap()
}

fn text_of(result: &rmcp::model::GetPromptResult) -> &str {
    match &result.messages[0].content {
        ContentBlock::Text(text) => text.text.as_str(),
        other => panic!("expected a text content block, got {other:?}"),
    }
}

#[tokio::test]
async fn prompts_list_advertises_every_workflow_prompt_under_the_shared_prefix() {
    let client = connected_client().await;

    let prompts = client.list_all_prompts().await.unwrap();
    let mut names: Vec<&str> = prompts.iter().map(|p| p.name.as_ref()).collect();
    names.sort_unstable();
    assert_eq!(
        names,
        [
            "rabbitmq_workflow",
            "rabbitmq_workflow_bindings",
            "rabbitmq_workflow_dead_letter",
            "rabbitmq_workflow_definitions_backup_restore",
            "rabbitmq_workflow_exchanges",
            "rabbitmq_workflow_federation_shovel",
            "rabbitmq_workflow_monitoring_diagnostics",
            "rabbitmq_workflow_policies",
            "rabbitmq_workflow_queues",
            "rabbitmq_workflow_users_permissions",
            "rabbitmq_workflow_vhosts",
        ]
    );
    assert!(
        names.iter().all(|n| n.starts_with("rabbitmq_workflow")),
        "every prompt name must share the rabbitmq_workflow* prefix, got: {names:?}"
    );

    let dead_letter = prompts
        .iter()
        .find(|p| p.name == "rabbitmq_workflow_dead_letter")
        .unwrap();
    let args = dead_letter.arguments.as_ref().unwrap();
    let arg_names: Vec<&str> = args.iter().map(|a| a.name.as_str()).collect();
    for expected in ["vhost", "source_queue", "dlx_name", "dlq_name"] {
        assert!(arg_names.contains(&expected), "missing arg: {expected}");
    }
    assert!(
        args.iter().all(|a| a.required == Some(false)),
        "every dead-letter argument must be optional, got: {args:?}"
    );

    drop(client);
}

#[tokio::test]
async fn master_prompt_with_no_arguments_links_to_the_dead_letter_sub_workflow() {
    let client = connected_client().await;

    let result = client
        .get_prompt(GetPromptRequestParams::new("rabbitmq_workflow"))
        .await
        .unwrap();
    assert_eq!(result.messages.len(), 1);
    let text = text_of(&result);
    assert!(text.contains("rabbitmq_workflow_dead_letter"));

    drop(client);
}

#[tokio::test]
async fn dead_letter_prompt_echoes_supplied_arguments_and_lists_the_missing_ones() {
    let client = connected_client().await;

    let result = client
        .get_prompt(
            GetPromptRequestParams::new("rabbitmq_workflow_dead_letter").with_arguments(
                serde_json::json!({ "vhost": "/", "source_queue": "orders" })
                    .as_object()
                    .unwrap()
                    .clone(),
            ),
        )
        .await
        .unwrap();
    let text = text_of(&result);
    assert!(text.contains("`vhost` = \"/\""));
    assert!(text.contains("`source_queue` = \"orders\""));
    assert!(text.contains("dlx_name"));
    assert!(text.contains("dlq_name"));

    drop(client);
}

#[tokio::test]
async fn dead_letter_prompt_with_no_arguments_lists_every_field_as_missing() {
    let client = connected_client().await;

    let result = client
        .get_prompt(GetPromptRequestParams::new("rabbitmq_workflow_dead_letter"))
        .await
        .unwrap();
    let text = text_of(&result);
    assert!(text.contains("(none — no arguments were supplied"));
    for expected in ["vhost", "source_queue", "dlx_name", "dlq_name"] {
        assert!(text.contains(expected));
    }

    drop(client);
}

#[tokio::test]
async fn server_info_advertises_the_prompts_capability() {
    let info = server().get_info();
    assert!(info.capabilities.prompts.is_some());
}
