# Architecture Diagrams

This directory contains PlantUML diagrams for the PR Check Agent architecture.

## Files

- `architecture.puml` - System architecture showing components and data flow
- `architecture.png` - Generated PNG of system architecture
- `workflow.puml` - Workflow state machine and transitions
- `workflow.png` - Generated PNG of workflow states

## Regenerating Diagrams

To regenerate the PNG files after editing the PlantUML source:

```bash
# Install PlantUML (if not already installed)
# On Ubuntu/Debian: sudo apt-get install plantuml
# On macOS: brew install plantuml
# Or download from: https://plantuml.com/download

# Generate diagrams
cd docs/diagrams
plantuml architecture.puml
plantuml workflow.puml
```

## Architecture Diagram

Shows the overall system design including:
- **LangGraph Workflows**: Main monitoring workflow with nodes
- **External Services**: GitHub API, Claude Code CLI, Telegram, Redis
- **LangGraph Tools**: GitHub Tool, Claude Tool, Telegram Tool
- **State Management**: Persistence layer and state schemas
- **Observability**: Metrics, health checks, dashboard

## Workflow Diagram

Shows the state machine with:
- **State Transitions**: How workflow moves between states
- **Decision Points**: Conditional routing based on check results
- **Error Handling**: Retry logic and escalation paths
- **Timing**: Polling intervals and timeouts

## Editing Guidelines

When editing the PlantUML files:
1. Keep the diagrams focused and readable
2. Use consistent naming for components
3. Update both `.puml` files if architecture changes
4. Regenerate PNG files after changes
5. Update this README if new diagrams are added