# Google Cloud Agent Gateway MCP Policy Lab

A hands-on reference implementation for governing AI agent access to MCP tools using the Google Cloud agent stack.

The lab uses:

- **Google Agent Development Kit (ADK)** for agent implementation
- **Gemini on Vertex AI** for model inference
- **Google Cloud Agent Runtime** for managed execution
- **Agent Identity** for per-agent identity
- **Agent Registry** for governed destination discovery where appropriate
- **Agent Gateway** as the runtime policy-enforcement boundary
- **IAM Unified Access Policies** for tool-level authorization
- **Model Context Protocol (MCP)** for exposing tools
- **Cloud Logging and audit evidence** to validate policy outcomes

## What this lab demonstrates

An enterprise AI agent may be technically capable of discovering and invoking multiple tools, but that does not mean it should be authorized to use every tool.

This lab explores a simple question:

> **How can we enforce which MCP tools a specific AI agent is allowed to invoke?**

The agent is built using Google ADK and deployed on Google Cloud Agent Runtime.

The deployed agent operates with its own Agent Identity. Governed MCP traffic passes through Agent Gateway, where IAM access policy determines which tool invocations are permitted.

The reference scenario exposes two synthetic MCP tools:

- `read_customer_profile` — allowed
- `update_customer_profile` — denied

No real customer information is used.

## Reference architecture

The intended execution path is:

**User → ADK Agent → Agent Runtime → Agent Identity → Agent Gateway → MCP Server → Tool**

Supporting governance components include:

- **Agent Registry** — destination discovery and governance metadata
- **IAM Unified Access Policies** — runtime authorization rules
- **Cloud Logging / audit evidence** — policy-decision and execution evidence

The key architectural principle is that the agent may decide which tool it wants to invoke, but it does not make the final authorization decision.

## What we will validate

The lab will demonstrate:

1. an agent built using Google ADK
2. model interaction using Gemini on Vertex AI
3. deployment on Google Cloud Agent Runtime
4. the deployed agent operating with its own Agent Identity
5. governed MCP access through Agent Gateway
6. registration or governance of the MCP destination through Agent Registry where appropriate
7. an allow policy for an approved MCP tool
8. a restrictive policy for another MCP tool
9. policy evaluation in dry-run mode before enforcement
10. enforcement of allowed and denied tool calls
11. logging and audit evidence showing the resulting policy decisions

## Reference scenario

The MCP server exposes two tools.

### `read_customer_profile`

A read-only tool that returns a synthetic customer profile.

Expected policy outcome:

**Allowed**

### `update_customer_profile`

A simulated mutation tool representing a higher-risk operation.

Expected policy outcome:

**Denied**

The purpose is not to model a customer-management application.

The two tools simply provide an easy way to demonstrate different authorization outcomes against the same MCP destination.

## Security boundary

This lab is built around one distinction:

> **Tool discovery is not tool authorization.**

The ADK agent may know that both tools exist.

The model may even determine that calling `update_customer_profile` would satisfy a user request.

That does not mean the operation should execute.

The authorization boundary exists outside the model's reasoning loop:

**Agent proposes action → Agent Gateway evaluates policy → approved action executes**

A restricted action should be blocked by policy even if the agent attempts to invoke it.

## Policy lifecycle

The intended policy lifecycle is:

**Define → Dry run → Observe → Validate → Enforce → Verify**

Policy changes should first be evaluated in dry-run mode.

This allows the expected allow and deny decisions to be observed before the policy is moved into enforcement mode.

The lab will then demonstrate both outcomes.

### Allowed path

**ADK Agent → Agent Identity → Agent Gateway → policy allows → MCP → `read_customer_profile`**

Result:

**Tool executes**

### Denied path

**ADK Agent → Agent Identity → Agent Gateway → policy denies → `update_customer_profile`**

Result:

**Request is blocked before the restricted tool executes**

## Why Agent Identity matters

The policy boundary should be able to identify which agent is attempting the operation.

Using a distinct Agent Identity provides a clearer authorization boundary than relying on one broadly shared runtime identity across multiple agents.

This supports:

- per-agent least privilege
- clearer attribution
- agent-specific access policy
- stronger auditability
- safer agent-to-tool communication

## Why MCP is used

MCP provides the protocol through which tools are exposed and invoked.

It does not replace authentication or authorization.

In this lab:

- **MCP** defines the tool interface
- **Agent Identity** identifies the calling agent
- **Agent Gateway** provides the runtime enforcement boundary
- **IAM access policy** determines whether the requested invocation is permitted

These concerns remain intentionally separate.

## Design principles

### Authorization should not live inside the prompt

Prompt instructions such as:

> “Do not call this tool”

are not security controls.

The model can influence which action is proposed, but authorization must be enforced independently of model reasoning.

### Least privilege should apply at the agent level

Different agents may require different tool access even when they use the same MCP server.

Permissions should reflect the responsibility of the individual agent.

### Evaluate policy before execution

A restricted operation should be rejected before the downstream tool performs the action.

### Start with dry-run policy evaluation

Policy behavior should be observed and validated before enforcement.

### Keep audit evidence

For an important tool invocation, the architecture should be able to answer:

- Which agent attempted the action?
- Which destination was called?
- Which tool was requested?
- Which policy was evaluated?
- Was the request allowed or denied?
- Did the tool actually execute?

## Planned repository structure

```text
google-cloud-agent-gateway-mcp-policy-lab/
├── README.md
├── LICENSE
├── agent/
│   └── ...
├── mcp-server/
│   └── ...
├── policies/
│   └── ...
├── docs/
│   ├── architecture.md
│   └── validation.md
└── tests/
    └── ...
```

The structure will evolve as the implementation is added.

## Scope

This repository is a generic technical lab based on publicly documented Google Cloud capabilities and open standards.

It does not represent any customer implementation, internal architecture, production environment, or proprietary dataset.

All example data used by the lab is synthetic.

## Current implementation status

The repository is being built incrementally.

The intended end state is a reproducible demonstration of:

**ADK Agent + Agent Runtime + Agent Identity + Agent Gateway + IAM policy + MCP**

with evidence showing that one tool invocation succeeds while another is blocked by policy.

## Core takeaway

> **An agent's ability to discover or request a tool does not imply permission to execute it.**

The model proposes the action.

The policy boundary decides whether the action is allowed.