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

The Runtime receives an effective Agent Identity from Google Cloud.

The Runtime API returns that identity in its raw resource form:

```text
spec.effectiveIdentity
```

For example:

```text
agents.global.<trust-domain>/resources/aiplatform/...
```

Store this value as:

```text
AGENT_EFFECTIVE_IDENTITY
```

IAM, IAP, and Unified Access Policy require the corresponding principal representation:

```text
principal://agents.global.<trust-domain>/resources/aiplatform/...
```

Therefore:

```text
AGENT_PRINCIPAL
=
principal://${AGENT_EFFECTIVE_IDENTITY}
```

The two values represent the same Agent Identity but are not identical strings.

The repository UAP template therefore uses:

```text
${AGENT_PRINCIPAL}
```

rather than the raw `spec.effectiveIdentity` value.

The effective identity must be retrieved dynamically from the deployed Runtime.

Do not derive the Agent Identity or trust domain from:

```text
project number
organization ID
Runtime ID
```

because the trust-domain representation can differ between environments.

This allows authorization to target the specific deployed agent instead of relying on a broadly shared runtime identity.

If the Runtime is deleted and recreated, the new Runtime receives a new effective Agent Identity.

The following references must then be updated:

```text
Cloud Run Invoker
Agent Registry Viewer
MCP resource IAP egress
Vertex endpoint IAP egress
Unified Access Policy principal
```

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

The tool specification must include a valid `inputSchema` for every registered tool.

For this lab:

```text
read_customer_profile
→ requires customer_id

update_customer_profile
→ requires customer_id
→ accepts email
```

A fresh-project deployment exposed that Agent Registry rejects an MCP tool specification when `inputSchema` is missing.

The observed validation condition was equivalent to:

```text
tools.0: inputSchema is required
tools.1: inputSchema is required
```

The repository now validates this requirement before registration:

```bash
jq -e 'all(.tools[]; has("inputSchema"))' mcp-server/toolspec.json
```

Expected:

```text
true
```

This is important because the MCP server implementation and the Agent Registry tool specification are separate artifacts.

A tool existing in the running MCP server does not automatically make an incomplete static registry specification valid.

The validated registration relationship is:

```text
MCP server implementation
+
toolspec.json
+
inputSchema
→ Agent Registry registration
```

Registration and authorization remain separate concepts.

Registration means the destination and tool metadata are known to Agent Registry.

It does not grant permission to execute those tools.

Therefore:

```text
registered tool
≠
authorized tool
```

and the validated lab behavior remains:

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
→ denied by authorization policy
→ not executed
```

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

The lab was reproduced in a fresh Google Cloud project to identify assumptions that were not visible in the original validation environment.

The following failures were encountered and resolved.

## Cloud Run source deployment fails during build

Possible symptom:

```text
storage.objects.get permission denied
```

during:

```text
gcloud run deploy --source
```

This can occur when the default Cloud Build service account does not yet have the permissions required for Cloud Run source builds.

Retrieve the build identity:

```bash
gcloud builds get-default-service-account \
  --project="${PROJECT_ID}"
```

The validated minimum project role used by this lab is:

```text
roles/run.builder
```

Do not respond to the storage error by granting broad Storage roles unless independently required.

The storage error can be a downstream symptom of the source-build identity not having the expected Cloud Run build permissions.

---

## Agent Registry rejects MCP tool specification

Possible symptom:

```text
Invalid MCP tool spec content
tools.0: inputSchema is required
tools.1: inputSchema is required
```

Every tool in:

```text
mcp-server/toolspec.json
```

must contain:

```text
inputSchema
```

Validate before registration:

```bash
jq -e 'all(.tools[]; has("inputSchema"))' mcp-server/toolspec.json
```

Expected:

```text
true
```

---

## Runtime deployment initially reports missing Agent Gateway permission

A fresh project can temporarily report that the Vertex AI Service Agent cannot access the Agent Gateway, including permission such as:

```text
networkservices.agentGateways.get
```

Before granting additional roles, inspect the Vertex AI Service Agent.

If it already has:

```text
roles/aiplatform.serviceAgent
```

wait for IAM or service-agent provisioning to propagate and retry the Runtime deployment.

In the reproduced environment, the same deployment succeeded on retry without granting an additional role.

Do not confuse the Google-managed Vertex AI Service Agent with the Runtime's Agent Identity.

They are different identities with different responsibilities.

---

## Reasoning Engines gcloud command is unavailable

Some Cloud SDK environments may not expose:

```text
gcloud ai reasoning-engines describe
```

even when the Runtime API is available.

The more portable validation path used by this lab is the Vertex AI REST API:

```bash
curl -fsS \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${RUNTIME_ID}"
```

This is also the source used to retrieve:

```text
spec.effectiveIdentity
spec.deploymentSpec.agentGatewayConfig
```

---

## Agent Identity representation is interpreted incorrectly

The Runtime API returns:

```text
spec.effectiveIdentity
```

in raw form:

```text
agents.global.<trust-domain>/resources/aiplatform/...
```

IAM, IAP, and UAP require:

```text
principal://agents.global.<trust-domain>/resources/aiplatform/...
```

Therefore:

```text
AGENT_EFFECTIVE_IDENTITY
=
spec.effectiveIdentity
```

and:

```text
AGENT_PRINCIPAL
=
principal://${AGENT_EFFECTIVE_IDENTITY}
```

Do not compare the raw Runtime value directly with the IAM principal string.

---

## IAP policy JSON replacement fails

A policy-replacement approach using:

```text
gcloud iap web set-iam-policy
```

with a JSON wrapper can fail with an error equivalent to:

```text
Invalid JSON payload received.
Unknown name "policy" at "policy"
```

It also introduces policy-replacement and etag concerns.

The validated approach for this lab is additive resource-level IAM:

```text
gcloud iap web add-iam-policy-binding
```

applied separately to:

```text
registered MCP server
registered Vertex endpoint
```

with:

```text
roles/iap.egressor
```

This also preserves the lab's least-privilege model.

A registry-wide grant is not required.

---

## UAP Policy Binding creation is blocked by Organization Policy

Possible symptom:

```text
FAILED_PRECONDITION
CUSTOM_ORG_POLICY_VIOLATION
constraints/iam.managed.disableAccessPolicyBinding
```

Inspect the effective policy:

```bash
gcloud org-policies describe \
  constraints/iam.managed.disableAccessPolicyBinding \
  --effective \
  --project="${PROJECT_ID}"
```

If the constraint is enforced, IAM permission changes do not bypass it.

The project requires an approved Organization Policy exception before the UAP Policy Binding can be created.

This is an environment prerequisite, not a malformed UAP or Policy Binding command.

---

## Runtime API request unexpectedly returns 404

Before diagnosing Runtime-to-Gateway association, confirm:

```bash
echo "${RUNTIME_RESOURCE}"
echo "${RUNTIME_ID}"
```

An empty `RUNTIME_ID` can produce a request against:

```text
.../reasoningEngines/
```

instead of a specific Runtime resource.

That failure does not prove that the Runtime-to-Gateway association is missing.

Always fail fast when the Runtime resource or Runtime ID is empty.

---

## Gemini traffic is denied before MCP execution

A deliberate negative test was performed by leaving the Vertex AI destination unregistered while keeping the MCP destination registered.

The Agent Gateway and Runtime could still be created.

MCP discovery traffic could also be observed as allowed.

However, interactive Runtime execution failed with:

```text
403 Forbidden
Egress request is not authorized.
```

Gateway evidence showed the destination hostname:

```text
aiplatform.mtls.googleapis.com
```

with:

```text
registryResource = null
```

and an authorization result of:

```text
DENIED
```

This demonstrates that Vertex endpoint registration is not required merely to create the Gateway or Runtime.

It is required for governed Gemini model traffic when Agent-to-Anywhere enforcement is active.

The validated sequence is:

```text
register Vertex endpoint
→ grant resource-level IAP egress
→ allow registered ENDPOINT traffic in UAP
→ Gemini inference succeeds through Agent Gateway
```

Do not register unrelated denied hostnames merely because they appear in Gateway logs.

Identify whether the hostname is actually part of the intended governed application path before adding it to Agent Registry.

---

## MCP tools/list denied

Symptom:

```text
initialize works
tools/list fails
```

The validated discovery rule is:

```text
destination.is_registered == true &&
destination.agent_registry.mcp_server.method != 'tools/call'
```

MCP discovery must succeed before normal tool execution can occur.

---

## Tool-specific rule does not match

The validated tool-rule pattern is:

```text
destination.is_registered == true &&
destination.agent_registry.mcp_server.method == 'tools/call' &&
destination.agent_registry.mcp_server.tool.name == '<TOOL_NAME>'
```

Tool discovery and tool execution authorization are independent.

---

## Vertex endpoint-specific rule does not match

The validated rule is:

```text
destination.is_registered == true &&
destination.agent_registry.resource_type == 'ENDPOINT'
```

This allows traffic to registered endpoints.

Further endpoint-level tightening should be tested independently before replacing this rule.

---

## Incorrect UAP permission string

The policy definition must use:

```text
iap.googleapis.com/resources.egressViaIAP
```

Do not replace it with the shortened audit-log representation:

```text
iap.resources.egressViaIAP
```

The shorter form can appear in audit output but is not the permission value used by the UAP definition.

---

## Testing too quickly after policy update

Symptom:

```text
new CEL rule appears ineffective
```

Resolution:

```text
update
→ wait for propagation
→ test once
→ inspect evidence
```

Do not repeatedly change policy expressions while an earlier version may still be propagating.

---

## Bound-token protection enabled

Possible symptom:

```text
Agent Gateway authorization = ALLOWED
Vertex AI response = 401 UNAUTHENTICATED
```

The validated compatibility setting is:

```text
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False
```

The reproduced experiment was:

```text
False
→ read succeeds

True
→ Gateway allows Vertex request
→ Vertex returns 401 UNAUTHENTICATED

False
→ read succeeds again
```

Do not change this setting as part of unrelated authorization troubleshooting.

---

# 19. Known-good deployment variables

The repository intentionally does not commit environment-specific resource identifiers.

The validated deployment uses the following variables.

## Project and region

```text
PROJECT_ID
REGION
GOOGLE_CLOUD_PROJECT
GOOGLE_CLOUD_REGION
```

The Google Cloud SDK project and the deployment variables must refer to the same target project.

---

## MCP server

```text
MCP_SERVICE
MCP_BASE_URL
MCP_URL
MCP_REGISTRY_SERVICE
MCP_REGISTRY_RESOURCE
MCP_SERVER_ID
```

The validated relationship is:

```text
MCP_BASE_URL
→ Cloud Run service URL

MCP_URL
→ ${MCP_BASE_URL}/mcp

MCP_REGISTRY_RESOURCE
→ Agent Registry resource returned during registration

MCP_SERVER_ID
→ final resource segment of MCP_REGISTRY_RESOURCE
```

---

## Vertex AI registered endpoint

```text
VERTEX_ENDPOINT_SERVICE
VERTEX_REGISTRY_RESOURCE
VERTEX_ENDPOINT_ID
```

The registered destination must correspond to the Vertex hostname actually used by the Runtime.

For the validated environment:

```text
aiplatform.mtls.googleapis.com
```

---

## Agent Gateway and authorization resources

```text
AGENT_GATEWAY_NAME
AUTHZ_EXTENSION_NAME
AUTHZ_POLICY_NAME
ACCESS_POLICY_NAME
POLICY_BINDING_NAME
```

These values identify the governed Agent-to-Anywhere path and its authorization resources.

---

## Agent Runtime

```text
RUNTIME_RESOURCE
RUNTIME_ID
```

The expected relationship is:

```text
RUNTIME_RESOURCE
→ full Runtime resource name

RUNTIME_ID
→ final resource segment of RUNTIME_RESOURCE
```

Both must be non-empty before Runtime API validation is attempted.

---

## Agent Identity

The Runtime API returns:

```text
AGENT_EFFECTIVE_IDENTITY
```

from:

```text
spec.effectiveIdentity
```

Its form is:

```text
agents.global.<trust-domain>/resources/aiplatform/...
```

The IAM principal representation is derived separately:

```text
AGENT_PRINCIPAL
=
principal://${AGENT_EFFECTIVE_IDENTITY}
```

Therefore:

```text
AGENT_EFFECTIVE_IDENTITY
≠
AGENT_PRINCIPAL
```

as literal strings.

Use:

```text
AGENT_EFFECTIVE_IDENTITY
```

when comparing against the Runtime API.

Use:

```text
AGENT_PRINCIPAL
```

for:

```text
Cloud Run IAM
Agent Registry IAM
IAP IAM
Unified Access Policy
```

---

## Cloud Run source-build identity

Fresh-project deployment can also require:

```text
BUILD_SERVICE_ACCOUNT
```

retrieved using:

```bash
gcloud builds get-default-service-account \
  --project="${PROJECT_ID}"
```

The validated build role used by the lab is:

```text
roles/run.builder
```

---

## Template rendering

Policy templates contain environment placeholders such as:

```text
${PROJECT_ID}
${REGION}
${AGENT_PRINCIPAL}
```

They must be rendered before deployment.

No unresolved placeholder should remain in a deployed policy artifact.

The deployment guide performs explicit validation before applying the Unified Access Policy.

---

## Portability principle

Do not hardcode:

```text
project IDs
project numbers
Runtime IDs
Agent Registry resource IDs
Cloud Run hostnames
Agent Identity trust domains
```

into repository artifacts.

They must be discovered or generated from the deployment environment.

This is required for the lab to remain reproducible across independent Google Cloud projects.

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

Use the following sequence when reproducing this architecture in another Google Cloud project.

```text
1. Set and verify PROJECT_ID and REGION

2. Enable required APIs, including:
   - Vertex AI
   - Agent Registry
   - Agent Gateway / Network Services
   - Network Security
   - IAP
   - IAM
   - Cloud Run
   - Cloud Build
   - Artifact Registry
   - Organization Policy

3. Check:
   constraints/iam.managed.disableAccessPolicyBinding

   If enforced, obtain the required approved exception
   before attempting to create the UAP Policy Binding.

4. Retrieve the default Cloud Build service account.

5. Ensure the build identity has:
   roles/run.builder

6. Run local unit and syntax validation.

7. Validate:
   mcp-server/toolspec.json

   Confirm every MCP tool contains:
   inputSchema

8. Deploy the authenticated MCP server to Cloud Run.

9. Capture:
   MCP_BASE_URL
   MCP_URL

10. Register the MCP server and tool metadata in Agent Registry.

11. Capture:
    MCP_REGISTRY_RESOURCE
    MCP_SERVER_ID

12. Register the Vertex AI destination actually used by the Runtime.

    For the validated path:
    aiplatform.mtls.googleapis.com

13. Capture:
    VERTEX_REGISTRY_RESOURCE
    VERTEX_ENDPOINT_ID

14. Create the Agent Gateway in:
    AGENT_TO_ANYWHERE

15. Create the IAP Authorization Extension initially in:
    DRY_RUN

16. Create and attach the Network Security REQUEST_AUTHZ policy.

17. Validate the Agent Runtime configuration before deployment.

18. Deploy the Agent Runtime with:
    AGENT_IDENTITY
    Agent-to-Anywhere Gateway association

19. Capture and validate:
    RUNTIME_RESOURCE
    RUNTIME_ID

20. Retrieve:
    spec.effectiveIdentity

    Store it as:
    AGENT_EFFECTIVE_IDENTITY

21. Derive:
    AGENT_PRINCIPAL =
    principal://${AGENT_EFFECTIVE_IDENTITY}

22. Grant the Runtime Agent Principal:
    Cloud Run Invoker
    Agent Registry Viewer

23. Grant resource-level:
    roles/iap.egressor

    separately on:
    - registered MCP server
    - registered Vertex endpoint

24. Render the Unified Access Policy using:
    ${AGENT_PRINCIPAL}

25. Create the UAP with the four validated rules:
    - allow MCP discovery / handshake
    - allow registered ENDPOINT traffic
    - allow read_customer_profile
    - deny update_customer_profile

26. Create the UAP Policy Binding.

27. Allow sufficient IAM and policy propagation time.

28. Switch the IAP Authorization Extension from:
    DRY_RUN
    to enforcement.

29. Verify the Runtime-to-Gateway association through the Runtime API.

30. Verify that the current Runtime effective identity still matches:
    AGENT_EFFECTIVE_IDENTITY

31. Start an interactive Playground session.

32. Validate:
    read_customer_profile
    → ALLOWED
    → EXECUTED

33. Validate:
    update_customer_profile
    → DENIED
    → NOT EXECUTED

34. Correlate:
    Agent Runtime events
    Agent Gateway logs
    IAP audit logs
    Cloud Run logs

35. Confirm that the denied update did not execute downstream.

36. Record the known-good configuration before changing any additional control.
```

The fresh-project reproduction showed that several checks belong **before** Runtime authorization testing:

```text
Organization Policy preflight
Cloud Run build identity
MCP inputSchema validation
Vertex destination registration
```

Skipping these checks can produce failures that look like Agent Gateway or UAP problems even though the authorization design itself is correct.

The recommended troubleshooting principle is:

```text
validate prerequisites
→ validate resource creation
→ validate identity
→ validate destination access
→ validate policy
→ validate behavior
→ validate downstream evidence
```

Do not modify multiple control-plane layers simultaneously.

When a failure occurs, preserve the last known-good layer and investigate the next dependency independently.

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
