# Reference Architecture

This document describes the validated architecture of the Google Cloud Agent Gateway MCP Policy Lab.

The implementation demonstrates fine-grained authorization of MCP tool calls made by an AI agent running on Google Cloud Agent Runtime.

The key principle is:

> **The model proposes the action. The authorization layer determines whether that action may execute.**


---

## 1. High-level architecture

```mermaid
flowchart TD
    U[User]

    ADK[Google ADK Agent]
    AR[Agent Runtime]
    AI[Agent Identity]
    AG[Agent Gateway]

    VTX[Gemini on Vertex AI]

    REG[Agent Registry]
    MCP[MCP Server on Cloud Run]

    READ[read_customer_profile]
    UPDATE[update_customer_profile]

    AP[Network Security\nAuthorization Policy]
    EXT[IAP Authorization Extension]
    UAP[IAM Unified Access Policy]
    BIND[IAM v3 Policy Binding]

    LOG[Cloud Logging / Audit Evidence]

    U --> ADK
    ADK --> AR
    AR --> AI
    AI --> AG

    AG --> VTX
    AG --> MCP

    REG -. registered destinations .-> AG
    REG -. MCP tool metadata .-> MCP

    MCP --> READ
    MCP --> UPDATE

    AP -. targets .-> AG
    AP --> EXT
    EXT --> UAP
    BIND -. binds UAP to project .-> UAP

    AG --> LOG
    MCP --> LOG
```

---

## 2. Execution model

The deployed agent runs on Agent Runtime using a dedicated Agent Identity.

The execution path begins as:

```text
User
  ↓
ADK Agent
  ↓
Agent Runtime
  ↓
Agent Identity
  ↓
Agent Gateway
```

From Agent Gateway, traffic can reach governed registered destinations such as:

```text
Vertex AI
MCP Server
```

Authorization is evaluated independently of the model's reasoning.

---

## 3. Governance model

Four distinct governance resources participate in the authorization design.

```text
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

An IAM v3 Policy Binding attaches the UAP to the target project.

These resources serve different purposes and should not be treated as interchangeable.

---

## 4. Network Security Authorization Policy

The Network Security Authorization Policy attaches custom request authorization to the Agent Gateway.

Validated characteristics:

```text
policyProfile = REQUEST_AUTHZ
action        = CUSTOM
```

It targets the Agent Gateway and references the IAP Authorization Extension.

Repository artifact:

```text
policies/gateway-authz-policy.yaml
```

Conceptually:

```text
Agent Gateway
     ↓
REQUEST_AUTHZ
     ↓
CUSTOM provider
     ↓
IAP Authorization Extension
```

---

## 5. IAP Authorization Extension

The IAP Authorization Extension delegates authorization evaluation to IAP.

Validated configuration:

```text
service          = iap.googleapis.com
failOpen         = false
timeout          = 1s
iapPolicyVersion = V2
```

Repository artifact:

```text
policies/iap-authz-extension.yaml
```

The final `1s` timeout was regression-tested with both:

```text
read_customer_profile   → success
update_customer_profile → blocked
```

---

## 6. IAM Unified Access Policy

The Unified Access Policy contains the fine-grained authorization rules.

Repository artifact:

```text
policies/customer-profile-tools-uap.json
```

The UAP evaluates:

```text
Agent Identity
+
registered destination
+
destination resource type
+
MCP method
+
MCP tool name
```

The validated permission is:

```text
iap.googleapis.com/resources.egressViaIAP
```

---

## 7. UAP Policy Binding

The Unified Access Policy is bound to the project through an IAM v3 Policy Binding.

Repository artifact:

```text
policies/customer-profile-uap-binding.json
```

The relationship is:

```text
UAP
  ↓
Policy Binding
  ↓
Target project
```

Creating a UAP alone does not establish the target to which it applies.

---

## 8. Agent Identity

Agent Runtime is configured with:

```text
AGENT_IDENTITY
```

Each deployed Runtime receives its own effective Agent Identity.

The Runtime API exposes the identity as:

```text
spec.effectiveIdentity
```

in raw resource form:

```text
agents.global.<trust-domain>/resources/aiplatform/...
```

The architecture treats this value as:

```text
AGENT_EFFECTIVE_IDENTITY
```

IAM, IAP, and Unified Access Policy use the corresponding principal representation:

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

These two strings represent the same Agent Identity but are not interchangeable representations.

The Unified Access Policy template uses:

```text
${AGENT_PRINCIPAL}
```

This allows authorization to target the specific deployed agent rather than a broadly shared runtime identity.

The identity must be retrieved dynamically from the deployed Runtime.

It should not be reconstructed from:

```text
project number
organization ID
Runtime ID
```

because the trust-domain representation can differ across environments.

If the Runtime is recreated, the new Runtime receives a new effective Agent Identity and the associated IAM, IAP, and UAP references must be updated.

---

## 9. Agent Registry

Agent Registry provides governed destination and tool metadata.

The lab registers the MCP server together with its tool specification.

Repository artifact:

```text
mcp-server/toolspec.json
```

The registered tool metadata includes:

```text
read_customer_profile
update_customer_profile
```

Each registered MCP tool must also provide a valid:

```text
inputSchema
```

For this lab:

```text
read_customer_profile
→ requires customer_id

update_customer_profile
→ requires customer_id
→ accepts email
```

The architectural relationship is:

```text
MCP server implementation
+
Agent Registry service registration
+
tool metadata
+
inputSchema
→ governed MCP destination metadata
```

The static registry specification and the running MCP server are separate artifacts.

A tool implemented by the MCP server does not automatically make an incomplete Agent Registry specification valid.

Registration also does not grant execution permission.

The distinction remains:

```text
Registered
≠
Authorized
```

and:

```text
Tool discoverability
≠
Tool execution authority
```

The validated outcome is:

```text
read_customer_profile
→ registered
→ authorized
→ executed
```

while:

```text
update_customer_profile
→ registered
→ denied by UAP
→ not executed
```

Agent Registry therefore establishes the governed destination and tool metadata that the authorization layer can evaluate, while UAP determines whether a specific operation may execute.

---

## 10. Vertex AI path

Gemini model inference is also governed through the Agent Gateway.

The Runtime does not communicate only with the MCP destination.

The model call itself traverses the governed egress path:

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

For the validated environment, the Runtime used:

```text
aiplatform.mtls.googleapis.com
```

That destination must be represented in Agent Registry when Agent-to-Anywhere enforcement is active.

The validated UAP condition for registered Vertex endpoints is:

```text
destination.is_registered == true &&
destination.agent_registry.resource_type == 'ENDPOINT'
```

Registration alone is not sufficient.

The Runtime Agent Principal also requires resource-level:

```text
roles/iap.egressor
```

on the registered Vertex endpoint.

The complete governed model-inference relationship is:

```text
Vertex hostname used by Runtime
→ registered in Agent Registry
→ Agent Principal has IAP egress on that endpoint
→ UAP allows registered ENDPOINT traffic
→ Gemini inference proceeds through Agent Gateway
```

A deliberate negative test was performed with the MCP server registered but the Vertex destination left unregistered.

The Agent Gateway and Agent Runtime could still be created.

MCP discovery traffic could also be observed.

However, model execution failed with:

```text
403 Forbidden
Egress request is not authorized.
```

Gateway evidence showed:

```text
hostname = aiplatform.mtls.googleapis.com
registryResource = null
authorization result = DENIED
```

This demonstrates an important architectural distinction:

```text
Vertex registration is not required merely to create the Gateway or Runtime.
```

but:

```text
Vertex registration is required for governed Gemini traffic under Agent-to-Anywhere enforcement.
```

Do not treat this failure as an MCP authorization problem.

The denial occurs on the model-inference path before the intended MCP tool execution can complete.

Also do not register every denied hostname observed in Gateway logs.

Only destinations that are intentionally part of the governed application path should be added to Agent Registry.

---

## 11. MCP protocol path

The MCP client performs protocol operations before executing a tool.

The observed sequence includes:

```text
initialize
notifications/initialized
tools/list
tools/call
```

Discovery and execution require different policy treatment.

The validated discovery condition is:

```text
destination.is_registered == true &&
destination.agent_registry.mcp_server.method != 'tools/call'
```

This permits protocol setup and discovery without granting arbitrary tool execution.

---

## 12. Tool-level authorization

The validated tool-level CEL structure is:

```text
destination.is_registered == true &&
destination.agent_registry.mcp_server.method == 'tools/call' &&
destination.agent_registry.mcp_server.tool.name == '<TOOL_NAME>'
```

The lab applies different effects to the two tools.

```text
read_customer_profile
→ ALLOW

update_customer_profile
→ DENY
```

---

## 13. Allowed read flow

```mermaid
sequenceDiagram
    participant U as User
    participant A as ADK Agent
    participant G as Agent Gateway
    participant P as Authorization Layer
    participant M as MCP Server

    U->>A: Read customer CUST-1001

    A->>G: Gemini inference
    G->>P: Evaluate registered Vertex endpoint
    P-->>G: ALLOW
    G-->>A: Gemini response selects read_customer_profile

    A->>G: MCP initialize / tools/list
    G->>P: Evaluate MCP discovery
    P-->>G: ALLOW

    A->>G: tools/call read_customer_profile
    G->>P: Evaluate Agent Identity + tool
    P-->>G: ALLOW

    G->>M: Forward read_customer_profile
    M-->>G: Synthetic customer profile
    G-->>A: Tool result
```

Validated outcome:

```text
read_customer_profile
→ selected by Gemini
→ authorized
→ reached Cloud Run
→ executed successfully
→ result returned to agent
```

---

## 14. Denied update flow

```mermaid
sequenceDiagram
    participant U as User
    participant A as ADK Agent
    participant G as Agent Gateway
    participant P as Authorization Layer
    participant M as MCP Server

    U->>A: Update customer email

    A->>G: Gemini inference
    G->>P: Evaluate registered Vertex endpoint
    P-->>G: ALLOW
    G-->>A: Gemini selects update_customer_profile

    A->>G: MCP initialize / tools/list
    G->>P: Evaluate MCP discovery
    P-->>G: ALLOW

    A->>G: tools/call update_customer_profile
    G->>P: Evaluate Agent Identity + tool
    P-->>G: DENY

    Note over G,M: Update request is not forwarded downstream
    G-->>A: Tool execution failure
```

Validated outcome:

```text
update_customer_profile
→ selected by Gemini
→ blocked by governance
→ did not reach Cloud Run as a tool execution
```

---

## 15. Downstream execution evidence

Authorization logs alone are not treated as sufficient proof of execution.

The validation correlates:

```text
Agent Runtime events
+
Agent Gateway logs
+
IAP audit logs
+
Cloud Run request logs
```

For the denied update test, Cloud Run received only:

```text
initialize
notifications/initialized
tools/list
```

There was no downstream request corresponding to the update tool execution.

This provided independent evidence that the mutation did not execute.

---

## 16. Logging architecture

```mermaid
flowchart LR
    AR[Agent Runtime] --> L[Cloud Logging]
    AG[Agent Gateway] --> L
    IAP[IAP Authorization] --> L
    CR[Cloud Run MCP Server] --> L
```

Useful evidence comes from different layers.

### Agent Runtime

Shows:

```text
model response
function_call
function_response
final response
```

### Agent Gateway

Shows information such as:

```text
registered destination
MCP method
MCP parameter
authorization result
TLS interception
HTTP status
```

### IAP

Provides authorization evaluation evidence where emitted.

### Cloud Run

Provides the strongest downstream evidence that a request actually reached the MCP service.

---

## 17. Observability limitation

During validation, individual `tools/call` decisions were not always emitted as separate Gateway or IAP log records.

Therefore:

```text
absence of one log event
≠
proof that the architecture was bypassed
```

Validation should correlate the complete request timeline across multiple logging sources.

See:

```text
docs/validation.md
```

for the detailed evidence and queries.

---

## 18. Bound-token compatibility finding

The validated Runtime currently uses:

```text
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False
```

A controlled test changed only this value to:

```text
True
```

while leaving Gateway and UAP configuration unchanged.

Observed flow:

```text
Agent Runtime
  ↓
Agent Gateway
  ↓
Gateway authorization = ALLOWED
  ↓
aiplatform.mtls.googleapis.com
  ↓
Vertex AI = 401 UNAUTHENTICATED
```

After reverting to:

```text
False
```

the same read path succeeded again.

Therefore the observed failure is separate from the UAP authorization decision.

The detailed experiment is documented in:

```text
docs/validation.md
```

---

## 19. Security boundaries

The architecture intentionally separates several concerns.

### Reasoning

Handled by:

```text
Gemini + ADK
```

### Agent identity

Handled by:

```text
Agent Identity
```

### Destination registration

Handled by:

```text
Agent Registry
```

### Traffic interception and governance

Handled by:

```text
Agent Gateway
```

### Authorization attachment

Handled by:

```text
Network Security Authorization Policy
```

### IAP delegation

Handled by:

```text
IAP Authorization Extension
```

### Fine-grained authorization

Handled by:

```text
IAM Unified Access Policy
```

### Tool interface

Handled by:

```text
MCP
```

### Downstream execution

Handled by:

```text
Cloud Run MCP server
```

No single component performs all of these responsibilities.

---

## 20. Security principles

The validated design demonstrates:

### Tool discovery is not authorization

An agent can discover a tool without being allowed to execute it.

### Model intent is not permission

Gemini may decide that a tool would satisfy the request, but the model does not grant authorization.

### Authorization lives outside the prompt

Prompt instructions are behavioral guidance, not security controls.

### Least privilege applies per agent

Agent Identity allows policy to target the specific deployed agent.

### Tool-level policy is possible

Two tools exposed by the same MCP server can receive different authorization outcomes.

### Verify execution independently

Policy logs and downstream execution evidence should be correlated.

---

## 21. Policy lifecycle

The validated policy lifecycle is:

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

Policy propagation may take several minutes.

A policy should not be repeatedly changed while propagation from the previous update may still be occurring.

---

## 22. Repository artifacts

```text
agent/
  agent.py
  runtime_app.py

deploy/
  deploy_agent.py

mcp-server/
  server.py
  toolspec.json

policies/
  iap-authz-extension.yaml
  gateway-authz-policy.yaml
  customer-profile-tools-uap.json
  customer-profile-uap-binding.json

docs/
  architecture.md
  validation.md
```

All cloud-environment-specific resource identifiers are represented using placeholders or environment variables rather than the identifiers from the environment used for validation.

---

## 23. Final validated baseline

```text
Agent Runtime                         PASS
Agent Identity                        ACTIVE
Agent Gateway                         ENFORCE
Agent Registry MCP destination        REGISTERED

IAP Policy Version                    V2
IAP Authorization timeout             1s
IAP fail-open                         false

Registered Vertex endpoint            ALLOWED

MCP initialize                        ALLOWED
MCP notifications/initialized         ALLOWED
MCP tools/list                        ALLOWED

read_customer_profile                 ALLOWED + EXECUTED
update_customer_profile               DENIED + NOT EXECUTED

Bound-token protection                False
Final read regression                 PASS
Final update-deny regression          PASS
```

This represents the known-good reference architecture validated by this lab.
