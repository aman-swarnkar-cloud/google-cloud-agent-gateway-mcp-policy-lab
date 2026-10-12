# Validation, Troubleshooting, and Known-Good Baseline

This document records the end-to-end validation of the Google Cloud Agent Gateway MCP Policy Lab.

It is intended to serve as:

- a validation record
- a troubleshooting reference
- a known-good baseline
- a handoff document for recreating the same security pattern in another Google Cloud project

Environment-specific identifiers are intentionally excluded from the repository.

---

# 1. What this lab proves

The lab demonstrates that a Google ADK agent running on Google Cloud Agent Runtime can:

1. operate using its own Agent Identity
2. access Gemini on Vertex AI through Agent Gateway
3. discover an MCP server registered with Agent Registry
4. discover MCP tools through the Gateway
5. execute an explicitly allowed MCP tool
6. be prevented from executing a denied MCP tool
7. enforce authorization outside the model reasoning loop
8. preserve downstream execution evidence through Cloud Logging

The validated policy outcome is:

```text
read_customer_profile    → ALLOWED → EXECUTED
update_customer_profile  → DENIED  → NOT EXECUTED
```

---

# 2. Validated architecture

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
  ├───────────────────────────────┐
  │                               │
  ↓                               ↓
Vertex AI                     Registered MCP Server
Gemini                        through Agent Registry
  │                               │
  │                               ↓
  │                         MCP discovery
  │                               ↓
  │                         MCP tools/call
  │                               ↓
  └──────── Governance ────────────┘

Governance chain:

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

The model proposes the action.

The authorization layer decides whether the action can execute.

---

# 3. Governance resources

Four distinct governance resources are involved.

They should not be treated as interchangeable.

## 3.1 IAP Authorization Extension

Purpose:

Connect Agent Gateway request authorization to IAP.

Validated configuration:

```yaml
name: ${AUTHZ_EXTENSION_NAME}

service: iap.googleapis.com

failOpen: false

timeout: 1s

metadata:
  iapPolicyVersion: "V2"
```

Validated repository artifact:

```text
policies/iap-authz-extension.yaml
```

The final `1s` timeout was regression-tested with both the allowed and denied MCP paths.

---

## 3.2 Network Security Authorization Policy

Purpose:

Attach the authorization extension to the Agent Gateway.

Validated structure:

```yaml
name: ${AUTHZ_POLICY_NAME}

target:
  resources:
    - projects/${PROJECT_ID}/locations/${REGION}/agentGateways/${AGENT_GATEWAY_NAME}

policyProfile: REQUEST_AUTHZ

action: CUSTOM

customProvider:
  authzExtension:
    resources:
      - projects/${PROJECT_ID}/locations/${REGION}/authzExtensions/${AUTHZ_EXTENSION_NAME}
```

Repository artifact:

```text
policies/gateway-authz-policy.yaml
```

This resource is the attachment layer between Agent Gateway and IAP authorization.

---

## 3.3 IAM Unified Access Policy

Purpose:

Define fine-grained authorization rules for the Agent Identity.

Repository artifact:

```text
policies/customer-profile-tools-uap.json
```

The policy uses:

```text
iap.googleapis.com/resources.egressViaIAP
```

The final policy contains four logical rules.

### Rule 1 — Allow MCP discovery and handshake

```text
destination.is_registered == true &&
destination.agent_registry.mcp_server.method != 'tools/call'
```

Effect:

```text
ALLOW
```

This permits protocol operations such as:

```text
initialize
notifications/initialized
tools/list
```

without granting arbitrary tool execution.

---

### Rule 2 — Allow registered Vertex AI endpoints

```text
destination.is_registered == true &&
destination.agent_registry.resource_type == 'ENDPOINT'
```

Effect:

```text
ALLOW
```

This allows Gemini model traffic to registered Vertex AI endpoints.

---

### Rule 3 — Allow read_customer_profile

```text
destination.is_registered == true &&
destination.agent_registry.mcp_server.method == 'tools/call' &&
destination.agent_registry.mcp_server.tool.name == 'read_customer_profile'
```

Effect:

```text
ALLOW
```

---

### Rule 4 — Deny update_customer_profile

```text
destination.is_registered == true &&
destination.agent_registry.mcp_server.method == 'tools/call' &&
destination.agent_registry.mcp_server.tool.name == 'update_customer_profile'
```

Effect:

```text
DENY
```

---

# 4. UAP Policy Binding

The Unified Access Policy is bound to the project using an IAM v3 Policy Binding.

Repository artifact:

```text
policies/customer-profile-uap-binding.json
```

Template:

```json
{
  "policy": "projects/${PROJECT_ID}/locations/global/accessPolicies/${ACCESS_POLICY_NAME}",
  "target": {
    "resource": "//cloudresourcemanager.googleapis.com/projects/${PROJECT_ID}"
  }
}
```

The binding is separate from the UAP itself.

Creating a UAP does not by itself make the policy effective until the policy is bound to a target.

---

# 5. Agent Identity

The Agent Runtime uses:

```text
identity_type = AGENT_IDENTITY
```

The UAP evaluates the Runtime's effective Agent Identity.

```text
${AGENT_PRINCIPAL}
```

This allows authorization to be evaluated for a specific deployed agent instead of relying on a broadly shared runtime identity.

---

# 6. Agent Registry

The MCP server is registered with Agent Registry.

Its registered tool metadata includes:

```text
read_customer_profile
update_customer_profile
```

Repository representation:

```text
mcp-server/toolspec.json
```

Registration and authorization are separate concepts.

A registered tool can still be denied by UAP.

---

# 7. Validated MCP protocol behavior

Before a tool can execute, the MCP client performs protocol operations.

The working policy allows:

```text
initialize
notifications/initialized
tools/list
```

These operations must not be blocked if tool discovery is expected to work.

A key finding during implementation was that allowing only `tools/call` is insufficient.

MCP discovery traffic must also be authorized.

---

# 8. Allowed-path validation

Test request:

```text
Read the customer profile for customer_id CUST-1001.
Use the MCP tool.
```

Observed model action:

```text
function_call:
  name: read_customer_profile
  customer_id: CUST-1001
```

Observed MCP result:

```json
{
  "status": "success",
  "profile": {
    "customer_id": "CUST-1001",
    "name": "Sample Customer",
    "email": "sample@example.com",
    "tier": "gold"
  }
}
```

Final result:

```text
read_customer_profile
→ selected by Gemini
→ permitted by policy
→ executed by MCP server
→ Cloud Run returned success
→ result returned to the agent
```

Status:

```text
PASS
```

---

# 9. Denied-path validation

Test request:

```text
Call update_customer_profile for customer_id CUST-1001
and set email to blocked@example.com.
Use the MCP tool.
```

Observed model action:

```text
function_call:
  name: update_customer_profile
```

Observed tool response:

```text
MCP tool execution failed:
Server returned an error response
```

The important downstream validation was performed against Cloud Run.

For the denied request, Cloud Run received only:

```text
initialize
notifications/initialized
tools/list
```

There was no fourth downstream MCP request corresponding to:

```text
update_customer_profile
```

Therefore:

```text
Gemini selected update_customer_profile
→ tool invocation was blocked
→ Cloud Run never executed the update
```

Status:

```text
PASS
```

---

# 10. Final acceptance matrix

```text
Component / Operation                    Expected       Validated

Agent Runtime                            Running        PASS
Agent Identity                           Active         PASS
Agent Gateway                            ENFORCE        PASS
Registered Vertex AI endpoint            Allowed        PASS
MCP initialize                           Allowed        PASS
MCP notifications/initialized            Allowed        PASS
MCP tools/list                           Allowed        PASS
read_customer_profile                    Executed       PASS
update_customer_profile                  Blocked        PASS
Denied update reaches Cloud Run          No             PASS
```

---

# 11. UAP propagation behavior

A significant implementation finding was policy propagation delay.

Some early tests were performed too soon after UAP updates and produced misleading results.

Observed behavior showed that policy updates can take several minutes before the new authorization behavior is consistently visible.

Recommended procedure after any UAP update:

```text
1. Update policy
2. Confirm update operation completed
3. Wait several minutes
4. Run one controlled validation request
5. Inspect logs
6. Only then modify policy again if necessary
```

Do not repeatedly rewrite the policy during the propagation window.

---

# 12. Gateway logging behavior

Useful Agent Gateway log fields include:

```text
jsonPayload.agentGatewayInfo.agentRegistryResource

jsonPayload.agentGatewayInfo.mcpInfo.method

jsonPayload.agentGatewayInfo.mcpInfo.parameter

jsonPayload.authzPolicyInfo.result

jsonPayload.enforcedGatewaySecurityPolicy.hostname

jsonPayload.enforcedGatewaySecurityPolicy.requestWasTlsIntercepted
```

Typical successful discovery evidence:

```text
initialize                 ALLOWED
notifications/initialized  ALLOWED
tools/list                 ALLOWED
```

---

# 13. Gateway log query

Example:

```bash
gcloud logging read \
  'resource.type="networkservices.googleapis.com/Gateway"' \
  --project="${PROJECT_ID}" \
  --freshness=30m \
  --limit=100 \
  --order=asc \
  --format=json
```

For MCP-specific inspection:

```bash
gcloud logging read \
  'resource.type="networkservices.googleapis.com/Gateway"
   jsonPayload.agentGatewayInfo.mcpInfo.method="tools/call"' \
  --project="${PROJECT_ID}" \
  --freshness=30m \
  --limit=50 \
  --order=desc \
  --format=json
```

---

# 14. Cloud Run execution validation

Gateway logs alone should not be the only evidence used to determine whether a tool executed.

Cloud Run logs can confirm whether the downstream MCP server actually received the request.

Example:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision"
   resource.labels.service_name="${MCP_SERVICE}"' \
  --project="${PROJECT_ID}" \
  --freshness=30m \
  --limit=100 \
  --order=asc \
  --format=json
```

For denied operations, the expected result is:

```text
discovery traffic visible
tool execution request absent
```

---

# 15. Observability finding

During validation, successful or denied `tools/call` requests were not always emitted as separate Agent Gateway or IAP log entries.

For example:

- Agent Runtime showed the generated tool call.
- Cloud Run proved whether the downstream request executed.
- Gateway showed initialization and discovery.
- A standalone per-tool Gateway or IAP record was not always present.

Therefore, validation should correlate multiple evidence sources:

```text
Agent Runtime events
+
Agent Gateway logs
+
IAP audit logs
+
Cloud Run request logs
```

Absence of one individual log record should not automatically be interpreted as proof that the authorization layer was bypassed.

---

# 16. Bound-token protection experiment

The validated working configuration is:

```text
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False
```

A controlled experiment was performed after all Gateway and UAP behavior had already been validated.

No Gateway or UAP policy was changed.

Only this setting was changed:

```text
False → True
```

Result:

```text
Gateway authorization result = ALLOWED
Destination = aiplatform.mtls.googleapis.com
HTTP response from Vertex AI = 401 UNAUTHENTICATED
```

The request reached the registered Vertex destination through Agent Gateway and was authorized by Gateway policy.

Vertex AI then rejected the authentication credentials.

The experiment was reverted:

```text
True → False
```

The same `read_customer_profile` request immediately returned to the known-good behavior.

Validated sequence:

```text
False
→ read succeeds

True
→ Gateway ALLOWED
→ Vertex AI returns 401 UNAUTHENTICATED

False
→ read succeeds again
```

This isolates the failure from the UAP and Gateway authorization rules.

The behavior has been reported separately to Google.

Until the platform behavior changes, this lab keeps:

```text
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False
```

---

# 17. Known-good IAP extension configuration

The extension was initially running with a longer timeout.

The final configuration was changed to:

```text
timeout = 1s
failOpen = false
iapPolicyVersion = V2
```

After this change:

```text
read_customer_profile   → PASS
update_customer_profile → BLOCKED
```

Therefore the 1-second configuration is the final validated baseline.

---

# 18. Common implementation failures discovered

## MCP tools/list denied

Symptom:

```text
initialize works
tools/list fails
```

Working condition:

```text
destination.is_registered == true &&
destination.agent_registry.mcp_server.method != 'tools/call'
```

---

## Tool-specific rule does not match

Working tool-rule pattern:

```text
destination.is_registered == true &&
destination.agent_registry.mcp_server.method == 'tools/call' &&
destination.agent_registry.mcp_server.tool.name == '<TOOL_NAME>'
```

---

## Vertex endpoint-specific rule does not match

The validated working rule was:

```text
destination.is_registered == true &&
destination.agent_registry.resource_type == 'ENDPOINT'
```

This allows registered Vertex endpoint traffic.

Further endpoint-level tightening should be tested independently before replacing this rule.

---

## Incorrect UAP permission string

The policy file must use:

```text
iap.googleapis.com/resources.egressViaIAP
```

Do not replace it with the shortened runtime audit representation:

```text
iap.resources.egressViaIAP
```

The shortened form can appear in audit output but is not the correct permission value for the UAP definition.

---

## Testing too quickly after policy update

Symptom:

```text
new CEL rule appears ineffective
```

Resolution:

Wait several minutes before concluding that a rule is incorrect.

---

## Bound-token protection enabled

Symptom:

```text
Gateway ALLOWED
Vertex AI 401 UNAUTHENTICATED
```

Known-good compatibility setting:

```text
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False
```

---

# 19. Known-good deployment variables

The repository does not commit environment-specific resource identifiers.

Expected variables include:

```text
GOOGLE_CLOUD_PROJECT
GOOGLE_CLOUD_REGION
PROJECT_ID
REGION
RUNTIME_ID
MCP_URL
MCP_SERVICE
AGENT_GATEWAY_NAME
AUTHZ_EXTENSION_NAME
AUTHZ_POLICY_NAME
ACCESS_POLICY_NAME
POLICY_BINDING_NAME
```

Policy templates must be rendered before deployment.

---

# 20. Repository artifact mapping

```text
agent/
  agent.py
      ADK agent, Gemini configuration, MCP authentication

  runtime_app.py
      Agent Runtime application and authentication diagnostics

deploy/
  deploy_agent.py
      Agent Runtime deployment configuration

mcp-server/
  server.py
      Synthetic MCP server

  toolspec.json
      Agent Registry tool metadata

policies/
  iap-authz-extension.yaml
      IAP V2 authorization extension

  gateway-authz-policy.yaml
      Network Security authorization policy

  customer-profile-tools-uap.json
      Fine-grained UAP rules

  customer-profile-uap-binding.json
      Project-level IAM v3 UAP binding

docs/
  architecture.md
      Reference architecture

  validation.md
      Validation, troubleshooting, and known-good baseline
```

---

# 21. Recommended first-attempt validation order

Use the following sequence when reproducing this architecture in another project:

```text
1. Deploy MCP server
2. Register MCP server and tool metadata
3. Deploy Agent Runtime with Agent Identity
4. Create Agent Gateway
5. Associate Agent Runtime with Agent Gateway
6. Ensure required Agent Registry and IAP IAM roles
7. Create IAP Authorization Extension
8. Create Network Security Authorization Policy
9. Create UAP
10. Create UAP Policy Binding
11. Begin with policy evaluation / validation
12. Allow MCP discovery
13. Allow registered Vertex endpoint traffic
14. Add tool-specific ALLOW
15. Add tool-specific DENY
16. Allow sufficient propagation time
17. Validate read
18. Validate update denial
19. Confirm denied operation never reached Cloud Run
20. Capture logs and freeze the known-good configuration
```

Do not start by debugging all layers simultaneously.

Validate each control plane layer independently.

---

# 22. Security principles demonstrated

This lab intentionally enforces several principles:

```text
Agent identity is separate from tool authorization.

Tool discovery does not imply tool permission.

Model intent does not imply execution authority.

Authorization occurs outside the prompt and model reasoning loop.

Mutation operations can be denied while read operations remain available.

Downstream execution should be verified independently from policy logs.

Policies should be tested before being treated as production controls.
```

---

# 23. Current known-good baseline

At the completion of validation:

```text
Agent Identity                          ACTIVE
Agent Gateway                           ENFORCE
IAP Policy Version                      V2
IAP Extension timeout                   1s
IAP Extension fail-open                 false
Vertex registered endpoint              ALLOWED
MCP discovery                           ALLOWED
read_customer_profile                   ALLOWED
update_customer_profile                 DENIED
Bound-token protection                  False
Read regression after rollback          PASS
Update deny regression                  PASS
```

This is the baseline that should be preserved until a deliberate change is tested and validated.
