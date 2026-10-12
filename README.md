# Google Cloud Agent Gateway MCP Policy Lab

A validated reference implementation for enforcing fine-grained MCP tool authorization for AI agents on Google Cloud.

This lab demonstrates how a Google ADK agent running on Agent Runtime can use its own Agent Identity, access governed destinations through Agent Gateway, and have individual MCP tool calls allowed or denied by IAM Unified Access Policy.

The final validated outcome is:

```text
read_customer_profile    → ALLOWED → EXECUTED
update_customer_profile  → DENIED  → NOT EXECUTED
```

All customer data used by the lab is synthetic.

---

## What this repository demonstrates

The implementation combines:

- **Google Agent Development Kit (ADK)** — agent implementation
- **Gemini on Vertex AI** — model inference
- **Google Cloud Agent Runtime** — managed agent execution
- **Agent Identity** — per-agent security identity
- **Agent Registry** — governed destination and MCP tool metadata
- **Agent Gateway** — runtime egress and enforcement boundary
- **IAP Authorization Extension** — delegates Gateway authorization to IAP
- **Network Security Authorization Policy** — attaches the authorization extension to the Gateway
- **IAM Unified Access Policy (UAP)** — fine-grained authorization logic
- **Model Context Protocol (MCP)** — tool discovery and execution
- **Cloud Run** — synthetic MCP server
- **Cloud Logging** — runtime, Gateway, IAP, and downstream execution evidence

The core security principle is:

> **The model proposes an action. The authorization layer decides whether it may execute.**

---

## Validated architecture

```text
User
  ↓
Google ADK Agent
  ↓
Agent Runtime
  ↓
Agent Identity
  ↓
Agent Gateway
  ├─────────────────────────────┐
  │                             │
  ↓                             ↓
Vertex AI                   MCP Server
Gemini                      registered in
                            Agent Registry
                                ↓
                            MCP tools

Authorization chain:

Agent Gateway
  ↓
Network Security Authorization Policy
  ↓
IAP Authorization Extension
  ↓
IAM Unified Access Policy
  ↓
ALLOW / DENY
```

See:

```text
docs/architecture.md
```

for the detailed architecture.

---

## Reference scenario

The MCP server exposes two synthetic tools.

### `read_customer_profile`

Returns a synthetic customer profile.

Policy outcome:

```text
ALLOW
```

Validated result:

```text
Tool executed successfully.
```

### `update_customer_profile`

Simulates a higher-risk mutation operation.

Policy outcome:

```text
DENY
```

Validated result:

```text
The model selected the tool,
but the request was blocked before the update reached Cloud Run.
```

---

## Tool discovery is not authorization

MCP discovery operations must be permitted independently of tool execution.

The validated policy permits:

```text
initialize
notifications/initialized
tools/list
```

but applies separate policy to:

```text
tools/call
```

This allows an agent to discover a tool without automatically being authorized to execute it.

---

## Fine-grained authorization

The validated UAP contains four logical rules:

```text
1. ALLOW registered MCP discovery and handshake traffic
2. ALLOW registered Vertex AI endpoints
3. ALLOW tools/call → read_customer_profile
4. DENY  tools/call → update_customer_profile
```

The validated tool-level CEL pattern is:

```text
destination.is_registered == true &&
destination.agent_registry.mcp_server.method == 'tools/call' &&
destination.agent_registry.mcp_server.tool.name == '<TOOL_NAME>'
```

The UAP permission is:

```text
iap.googleapis.com/resources.egressViaIAP
```

---

## Governance resources

The implementation uses four separate governance resources.

### IAP Authorization Extension

Connects Agent Gateway authorization to IAP.

Repository artifact:

```text
policies/iap-authz-extension.yaml
```

Validated configuration:

```text
service = iap.googleapis.com
failOpen = false
timeout = 1s
iapPolicyVersion = V2
```

### Network Security Authorization Policy

Attaches the IAP Authorization Extension to the Agent Gateway.

Repository artifact:

```text
policies/gateway-authz-policy.yaml
```

### IAM Unified Access Policy

Contains the agent, destination, protocol, and tool authorization rules.

Repository artifact:

```text
policies/customer-profile-tools-uap.json
```

### IAM v3 Policy Binding

Binds the Unified Access Policy to the target project.

Repository artifact:

```text
policies/customer-profile-uap-binding.json
```

---

## Agent Identity

The deployed Agent Runtime uses:

```text
AGENT_IDENTITY
```

rather than relying on one broadly shared runtime identity.

The UAP evaluates the specific Agent Identity principal.

The repository uses placeholders rather than committing environment-specific project and Runtime identifiers.

---

## Agent Registry

The MCP server is registered with Agent Registry.

The tool metadata represented in:

```text
mcp-server/toolspec.json
```

contains:

```text
read_customer_profile
update_customer_profile
```

Registration does not grant authorization.

A registered tool may still be denied by UAP.

---

## Validated results

```text
Agent Runtime                            PASS
Agent Identity                           PASS
Agent Gateway ENFORCE                    PASS
Registered Vertex AI endpoint            ALLOWED
MCP initialize                           ALLOWED
MCP notifications/initialized            ALLOWED
MCP tools/list                           ALLOWED
read_customer_profile                    ALLOWED + EXECUTED
update_customer_profile                  DENIED
Denied update reached Cloud Run          NO
```

Detailed validation evidence and troubleshooting notes are documented in:

```text
docs/validation.md
```

---

## Bound-token compatibility finding

The known-good configuration for this lab currently uses:

```text
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False
```

A controlled validation was performed with the Gateway and UAP unchanged:

```text
False
→ read_customer_profile succeeds

True
→ Agent Gateway authorizes the Vertex request
→ Vertex AI returns 401 UNAUTHENTICATED

False
→ read_customer_profile succeeds again
```

The failure therefore occurs after Gateway authorization and is associated with the authentication presented to Vertex AI rather than a UAP denial.

This behavior has been reported separately to Google.

The compatibility setting should be re-tested when the underlying platform behavior changes.

See `docs/validation.md` for the complete evidence.

---

## Repository structure

```text
google-cloud-agent-gateway-mcp-policy-lab/
├── .github/
│   └── workflows/
│       ├── agent-auth-unit.yml
│       └── mcp-integration.yml
│
├── agent/
│   ├── __init__.py
│   ├── agent.py
│   ├── requirements.txt
│   └── runtime_app.py
│
├── deploy/
│   └── deploy_agent.py
│
├── docs/
│   ├── architecture.md
│   ├── deployment.md
│   └── validation.md
│
├── mcp-server/
│   ├── Dockerfile
│   ├── server.py
│   └── toolspec.json
│
├── policies/
│   ├── customer-profile-tools-uap.json
│   ├── customer-profile-uap-binding.json
│   ├── gateway-authz-policy.yaml
│   └── iap-authz-extension.yaml
│
├── tests/
│   └── test_agent_auth.py
│
├── LICENSE
├── README.md
└── requirements.txt
```

---

## Environment-specific configuration

The repository intentionally does not contain the project-specific identifiers from the environment used during validation.

Templates use values such as:

```text
${PROJECT_ID}
${PROJECT_NUMBER}
${REGION}
${RUNTIME_ID}
${AGENT_GATEWAY_NAME}
${AUTHZ_EXTENSION_NAME}
${AUTHZ_POLICY_NAME}
${ACCESS_POLICY_NAME}
${POLICY_BINDING_NAME}
```

The deployment code expects environment variables including:

```text
GOOGLE_CLOUD_PROJECT
GOOGLE_CLOUD_REGION
MCP_URL
AGENT_GATEWAY_NAME
```

Render policy templates with the appropriate environment-specific values before deployment.

---

## Policy lifecycle

The validated workflow is:

```text
Define
  ↓
Dry run / evaluate
  ↓
Observe
  ↓
Validate
  ↓
Enforce
  ↓
Verify downstream execution
```

Policy updates can require several minutes to propagate.

Do not repeatedly rewrite a policy while propagation may still be occurring.

---

## Validation strategy

Do not rely on a single log source.

Correlate:

```text
Agent Runtime events
+
Agent Gateway logs
+
IAP audit logs
+
Cloud Run request logs
```

This is particularly important when validating whether a denied tool actually reached the downstream service.

---

## Security principles demonstrated

This implementation demonstrates that:

- Agent Identity and tool authorization are separate concerns.
- Tool discovery does not imply permission to execute a tool.
- Prompt instructions are not authorization controls.
- Model intent does not grant execution authority.
- Read and mutation operations can receive different authorization outcomes.
- Authorization can be applied to individual MCP tools.
- Downstream execution should be independently verified.
- Policy changes should be validated before being treated as production controls.

---

## Documentation

Reproducible deployment guide:

```text
docs/deployment.md
```

Detailed architecture:

```text
docs/architecture.md
```

Complete validation, troubleshooting, known-good configuration, log queries, propagation findings, and bound-token experiment:

```text
docs/validation.md
```

---

## Scope

This repository is a generic technical reference implementation based on publicly documented Google Cloud capabilities and open standards.

It does not represent a customer architecture, proprietary implementation, production environment, or real customer dataset.

All customer data in the lab is synthetic.

---

## Core takeaway

> **An agent's ability to discover or request a tool does not imply permission to execute it.**

The model proposes the action.

The policy boundary determines whether that action is allowed.
