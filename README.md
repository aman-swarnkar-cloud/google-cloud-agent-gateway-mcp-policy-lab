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

## Documentation

Start here depending on what you want to do:

- **[Deployment Guide](docs/deployment.md)** — complete reproducible deployment, interactive validation, troubleshooting, fresh-project portability guidance, and safe cleanup procedure.
- **[Reference Architecture](docs/architecture.md)** — architecture, security boundaries, Agent Identity model, governed Vertex AI path, MCP protocol flow, and tool-level authorization.
- **[Validation Guide](docs/validation.md)** — validation evidence, known-good configuration, troubleshooting findings, logging behavior, policy propagation findings, and portability lessons.

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

See the **[Reference Architecture](docs/architecture.md)** for the complete architecture and request flows.

---

## Reference scenario

The synthetic MCP server exposes two tools.

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

The implementation is available in:

[**mcp-server/server.py**](mcp-server/server.py)

---

## Tool discovery is not authorization

MCP discovery operations must be permitted independently of tool execution.

The validated policy permits:

```text
initialize
notifications/initialized
tools/list
```

but applies separate authorization policy to:

```text
tools/call
```

This allows an agent to discover a tool without automatically being authorized to execute it.

Therefore:

```text
Tool discovery
≠
Tool authorization
```

---

## Fine-grained authorization

The validated Unified Access Policy contains four logical rules:

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

The permission used by the UAP is:

```text
iap.googleapis.com/resources.egressViaIAP
```

The complete policy is available in:

[**policies/customer-profile-tools-uap.json**](policies/customer-profile-tools-uap.json)

---

## Governance resources

The implementation uses four separate governance resources.

### IAP Authorization Extension

Connects Agent Gateway authorization to IAP.

Repository artifact:

[**policies/iap-authz-extension.yaml**](policies/iap-authz-extension.yaml)

Validated configuration:

```text
service = iap.googleapis.com
failOpen = false
timeout = 1s
iapPolicyVersion = V2
```

### Network Security Authorization Policy

Attaches the IAP Authorization Extension to Agent Gateway.

Repository artifact:

[**policies/gateway-authz-policy.yaml**](policies/gateway-authz-policy.yaml)

### IAM Unified Access Policy

Contains the agent, destination, protocol, and tool authorization rules.

Repository artifact:

[**policies/customer-profile-tools-uap.json**](policies/customer-profile-tools-uap.json)

### IAM v3 Policy Binding

Binds the Unified Access Policy to the target project.

Repository artifact:

[**policies/customer-profile-uap-binding.json**](policies/customer-profile-uap-binding.json)

These resources have different responsibilities and should not be treated as interchangeable controls.

---

## Agent Identity

The deployed Agent Runtime uses:

```text
AGENT_IDENTITY
```

rather than relying on one broadly shared runtime identity.

The Runtime API exposes the effective identity in raw form:

```text
spec.effectiveIdentity
```

represented in the lab as:

```text
AGENT_EFFECTIVE_IDENTITY
```

For IAM, IAP, and UAP, the corresponding principal representation is:

```text
AGENT_PRINCIPAL
=
principal://${AGENT_EFFECTIVE_IDENTITY}
```

Therefore:

```text
Runtime API representation
→ AGENT_EFFECTIVE_IDENTITY

IAM / IAP / UAP representation
→ AGENT_PRINCIPAL
```

The identity is discovered dynamically from the deployed Runtime rather than reconstructed from project numbers, organization IDs, or Runtime IDs.

This allows authorization to target the specific deployed agent.

See the **[Deployment Guide](docs/deployment.md)** and **[Reference Architecture](docs/architecture.md)** for the complete identity flow.

---

## Agent Registry

The MCP server is registered with Agent Registry together with its tool metadata.

The tool specification is defined in:

[**mcp-server/toolspec.json**](mcp-server/toolspec.json)

It contains:

```text
read_customer_profile
update_customer_profile
```

Each registered MCP tool also contains a valid:

```text
inputSchema
```

For this lab:

```text
read_customer_profile
→ customer_id required

update_customer_profile
→ customer_id required
→ email optional
```

A fresh-project deployment demonstrated that Agent Registry rejects tool metadata when the required `inputSchema` is missing.

Registration still does not grant authorization.

```text
Registered
≠
Authorized
```

A registered tool can still be denied by UAP.

---

## Governed Vertex AI path

Gemini inference also traverses the governed Agent Gateway path.

The validated model endpoint is:

```text
aiplatform.mtls.googleapis.com
```

Under Agent-to-Anywhere enforcement, the intended Vertex AI destination must be:

```text
registered in Agent Registry
+
authorized for IAP egress
+
allowed by UAP as a registered ENDPOINT
```

The validated relationship is:

```text
Agent Runtime
  ↓
Agent Identity
  ↓
Agent Gateway
  ↓
Authorization evaluation
  ↓
Registered Vertex AI endpoint
  ↓
Gemini
```

A deliberate negative test with the Vertex destination left unregistered resulted in:

```text
403 Forbidden
Egress request is not authorized.
```

with Gateway evidence showing:

```text
hostname = aiplatform.mtls.googleapis.com
registryResource = null
authorization result = DENIED
```

This failure occurs on the model-inference path and should not be misdiagnosed as an MCP tool authorization failure.

See **[docs/validation.md](docs/validation.md)** for the complete finding.

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

The successful security condition is:

```text
read_customer_profile
→ ALLOWED
→ EXECUTED
```

while:

```text
update_customer_profile
→ DENIED
→ NOT EXECUTED
```

Detailed validation evidence and troubleshooting findings are documented in the **[Validation Guide](docs/validation.md)**.

---

## Bound-token compatibility finding

The known-good configuration for this lab currently uses:

```text
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False
```

A controlled validation was performed with Agent Gateway and UAP unchanged:

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

This behavior should be re-tested when the underlying platform behavior changes.

See **[docs/validation.md](docs/validation.md)** for the complete experiment and evidence.

---

## Key implementation files

- **[agent/agent.py](agent/agent.py)** — ADK agent, Gemini configuration, MCP connection, and Cloud Run authentication.
- **[deploy/deploy_agent.py](deploy/deploy_agent.py)** — Agent Runtime, Agent Identity, and Agent Gateway deployment configuration.
- **[mcp-server/server.py](mcp-server/server.py)** — synthetic MCP server and reference tools.
- **[mcp-server/toolspec.json](mcp-server/toolspec.json)** — Agent Registry MCP tool metadata and input schemas.
- **[policies/customer-profile-tools-uap.json](policies/customer-profile-tools-uap.json)** — fine-grained MCP discovery, Vertex endpoint, read ALLOW, and update DENY rules.
- **[policies/gateway-authz-policy.yaml](policies/gateway-authz-policy.yaml)** — Network Security authorization policy attached to Agent Gateway.
- **[policies/iap-authz-extension.yaml](policies/iap-authz-extension.yaml)** — IAP V2 authorization extension.
- **[policies/customer-profile-uap-binding.json](policies/customer-profile-uap-binding.json)** — IAM v3 project-level UAP binding.

---

## CI validation

The repository includes automated validation for both agent authentication behavior and the MCP implementation.

- **[agent-auth-unit.yml](.github/workflows/agent-auth-unit.yml)** — authentication and agent configuration unit validation.
- **[mcp-integration.yml](.github/workflows/mcp-integration.yml)** — MCP HTTP integration, Docker validation, Agent Registry tool-spec validation, and runtime-to-registry tool-name consistency.

CI validates that:

```text
toolspec.json contains the expected tools
inputSchema exists for every registered tool
customer_id remains required
email remains optional for update_customer_profile
runtime MCP tools match Agent Registry tool metadata
MCP HTTP transport works
MCP container deployment works
synthetic update does not mutate stored data
```

This prevents the Agent Registry metadata from silently drifting away from the actual MCP server implementation.

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

The repository intentionally does not contain project-specific identifiers from the environments used during validation.

Deployment values are discovered or supplied dynamically.

Examples include:

```text
PROJECT_ID
REGION
RUNTIME_RESOURCE
RUNTIME_ID
AGENT_EFFECTIVE_IDENTITY
AGENT_PRINCIPAL
MCP_URL
MCP_SERVER_ID
VERTEX_ENDPOINT_ID
AGENT_GATEWAY_NAME
AUTHZ_EXTENSION_NAME
AUTHZ_POLICY_NAME
ACCESS_POLICY_NAME
POLICY_BINDING_NAME
```

The deployment code expects environment variables including:

```text
GOOGLE_CLOUD_PROJECT
GOOGLE_CLOUD_REGION
MCP_URL
AGENT_GATEWAY_NAME
```

Policy templates use placeholders such as:

```text
${PROJECT_ID}
${REGION}
${AGENT_PRINCIPAL}
```

These templates must be rendered using the target deployment environment before they are applied.

Do not hardcode:

```text
project IDs
project numbers
Runtime IDs
Agent Registry resource IDs
Cloud Run hostnames
Agent Identity trust domains
```

into reusable repository artifacts.

---

## Fresh-project portability validation

The lab was reproduced in an independent Google Cloud project to identify hidden environment assumptions.

That validation exposed and documented several portability requirements, including:

```text
Cloud Run source-build identity and roles/run.builder
Agent Registry MCP inputSchema requirements
Vertex AI Service Agent IAM propagation behavior
portable Runtime API validation through REST
Agent Identity raw vs principal representation
resource-level IAP IAM bindings
Organization Policy prerequisites for UAP Policy Binding
Runtime ID fail-fast validation
Vertex endpoint registration for governed Gemini traffic
```

These findings are incorporated into:

- **[docs/deployment.md](docs/deployment.md)**
- **[docs/validation.md](docs/validation.md)**
- **[docs/architecture.md](docs/architecture.md)**

---

## Deployment and cleanup

The complete deployment procedure is documented in:

[**docs/deployment.md**](docs/deployment.md)

The guide covers:

```text
API enablement
prerequisite validation
Cloud Run source deployment
Agent Registry registration
Vertex AI destination registration
Agent Gateway creation
IAP authorization bootstrap
Agent Runtime deployment
Agent Identity discovery
IAM and IAP bindings
Unified Access Policy creation
interactive Playground validation
logging and troubleshooting
safe resource cleanup
```

For temporary lab environments, the cleanup procedure supports:

```text
dedicated-project deletion
```

or targeted removal of only the resources created by the lab.

The cleanup guidance intentionally avoids blindly deleting shared IAM bindings, Artifact Registry repositories, or Organization Policy configuration.

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

Do not repeatedly rewrite a policy while propagation from the previous version may still be occurring.

---

## Validation strategy

Do not rely on a single logging source.

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

Absence of an individual Gateway or IAP `tools/call` record should not by itself be treated as proof that authorization was bypassed.

Downstream execution evidence must also be checked.

---

## Security principles demonstrated

This implementation demonstrates that:

- Agent Identity and tool authorization are separate concerns.
- Tool discovery does not imply permission to execute a tool.
- Destination registration does not imply permission to perform every operation.
- Prompt instructions are not authorization controls.
- Model intent does not grant execution authority.
- Read and mutation operations can receive different authorization outcomes.
- Authorization can be applied to individual MCP tools.
- Model inference can itself traverse the governed Agent Gateway path.
- Downstream execution should be independently verified.
- Policy changes should be validated before being treated as production controls.

---

## Scope

This repository is a generic technical reference implementation based on publicly documented Google Cloud capabilities and open standards.

It does not represent a customer architecture, proprietary implementation, production environment, or real customer dataset.

All customer data in the lab is synthetic.

---

## License

This repository is licensed under the terms in [LICENSE](LICENSE).

---

## Core takeaway

> **An agent's ability to discover or request a tool does not imply permission to execute it.**

The model proposes the action.

The authorization layer determines whether that action is allowed to execute.
