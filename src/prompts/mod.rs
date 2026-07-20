//! MCP prompts exposing guided, multi-step RabbitMQ management workflows on
//! top of the `search`/`get`/`call` tools (see `router.rs`). Kept as its own
//! module, separate from `tools/`, per docs/mcp-prompts-workflow-plan.md.

pub mod router;

use rmcp::schemars;
use serde::Deserialize;

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct MasterWorkflowArgs {
    /// What the user is trying to accomplish, in their own words (optional — omit to show the full menu)
    pub goal: Option<String>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct DeadLetterWorkflowArgs {
    /// Virtual host the source queue lives in
    pub vhost: Option<String>,
    /// Name of the queue whose messages should be dead-lettered
    pub source_queue: Option<String>,
    /// Desired name for the dead-letter exchange, if the user already has one in mind
    pub dlx_name: Option<String>,
    /// Desired name for the dead-letter queue, if the user already has one in mind
    pub dlq_name: Option<String>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct DefinitionsBackupRestoreWorkflowArgs {
    /// Virtual host to scope the export/import to (omit for the full cluster)
    pub vhost: Option<String>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct UpgradeReadinessWorkflowArgs {
    /// Node to scope the readiness check to (omit for a cluster-wide check)
    pub node: Option<String>,
}

/// Renders a short "Context already provided" header listing which of a
/// prompt's optional arguments the caller already supplied vs. still need to
/// be asked for. Prepended to each `content/*.md` body so the static
/// markdown never needs its own placeholder-substitution logic.
pub(crate) fn render_context_header(fields: &[(&str, Option<&str>)]) -> String {
    if fields.is_empty() {
        return String::new();
    }
    let mut out = String::from("## Context already provided\n");
    let mut any_known = false;
    for (name, value) in fields {
        if let Some(v) = value {
            out.push_str(&format!("- `{name}` = \"{v}\"\n"));
            any_known = true;
        }
    }
    if !any_known {
        out.push_str("- (none — no arguments were supplied with this prompt request)\n");
    }
    let missing: Vec<_> = fields
        .iter()
        .filter(|(_, v)| v.is_none())
        .map(|(n, _)| *n)
        .collect();
    if !missing.is_empty() {
        out.push_str(&format!(
            "\nStill unknown, ask the user before the step that needs it: {}\n",
            missing.join(", ")
        ));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_field_list_renders_nothing() {
        assert_eq!(render_context_header(&[]), "");
    }

    #[test]
    fn all_fields_supplied_lists_each_and_no_missing_section() {
        let header = render_context_header(&[("vhost", Some("/")), ("name", Some("orders"))]);
        assert!(header.contains("`vhost` = \"/\""));
        assert!(header.contains("`name` = \"orders\""));
        assert!(!header.contains("Still unknown"));
    }

    #[test]
    fn all_fields_missing_notes_none_supplied_and_lists_all_as_missing() {
        let header = render_context_header(&[("vhost", None), ("name", None)]);
        assert!(header.contains("(none — no arguments were supplied"));
        assert!(
            header
                .contains("Still unknown, ask the user before the step that needs it: vhost, name")
        );
    }

    #[test]
    fn mixed_fields_report_supplied_and_missing_separately() {
        let header = render_context_header(&[("vhost", Some("/")), ("name", None)]);
        assert!(header.contains("`vhost` = \"/\""));
        assert!(!header.contains("`name` ="));
        assert!(header.contains("Still unknown, ask the user before the step that needs it: name"));
    }
}
