# Deployment Guide

This document provides a reproducible deployment sequence for the Google Cloud Agent Gateway MCP Policy Lab.

The objective is to deploy the lab into a new Google Cloud project without relying on identifiers from the environment originally used to validate the implementation.

The final expected behavior is:

```text
read_customer_profile    → ALLOWED → EXECUTED
update_customer_profile  → DENIED  → NOT EXECUTED
```

---

# 1. Deployment model

This guide assumes a single Google Cloud project and region for:

```text
Agent Runtime
Agent Gateway
Agent Registry
MCP server
authorization resources
Unified Access Policy
```

The validated architecture is:

```text
ADK Agent
  ↓
Agent Runtime
  ↓
Agent Identity
  ↓
Agent Gateway
  ↓
Network Security Authorization Policy
  ↓
IAP Authorization Extension
  ↓
IAM Unified Access Policy
  ↓
Registered destination
```

The MCP server runs on Cloud Run.

---

# 2. Prerequisites

Required locally:

```text
gcloud CLI
Python 3.11+
Git
jq
envsubst
```

Authenticate:

```bash
gcloud auth login
gcloud auth application-default login
```

Clone the repository and enter it:

```bash
git clone https://github.com/aman-swarnkar-cloud/google-cloud-agent-gateway-mcp-policy-lab.git
cd google-cloud-agent-gateway-mcp-policy-lab
```

Create a working directory for rendered configuration:

```bash
mkdir -p build
```

Do not commit files under `build/`.

---

# 3. Set deployment variables

Set the project and regional configuration.

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-central1"

export MCP_SERVICE="customer-profile-mcp"
export MCP_REGISTRY_SERVICE="customer-profile-mcp"

export AGENT_GATEWAY_NAME="mcp-policy-gateway"

export AUTHZ_EXTENSION_NAME="mcp-policy-gateway-iap-authzextension"
export AUTHZ_POLICY_NAME="mcp-policy-gateway-iap-authzpolicy"

export ACCESS_POLICY_NAME="customer-profile-tool-governance"
export POLICY_BINDING_NAME="customer-profile-tool-governance-binding"

export VERTEX_ENDPOINT_SERVICE="vertex-ai-mtls"
```

Configure gcloud:

```bash
gcloud config set project "${PROJECT_ID}"
gcloud config set compute/region "${REGION}"
```


Validate:

```bash
printf 'PROJECT_ID=%s\nREGION=%s\n' \
  "${PROJECT_ID}" \
  "${REGION}"
```

---

# 4. Enable required APIs

Enable the APIs used by the lab:

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  agentregistry.googleapis.com \
  networkservices.googleapis.com \
  networksecurity.googleapis.com \
  iap.googleapis.com \
  iam.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  orgpolicy.googleapis.com \
  --project="${PROJECT_ID}"
```

Agent Registry and IAP must both be enabled when Agent Gateway policy enforcement is used.

The Organization Policy API is enabled so that the deployment can verify whether IAM v3 access-policy bindings are permitted in the target project.

Verify the required APIs:

```bash
gcloud services list \
  --enabled \
  --project="${PROJECT_ID}" \
  --filter='name:(aiplatform.googleapis.com OR agentregistry.googleapis.com OR networkservices.googleapis.com OR networksecurity.googleapis.com OR iap.googleapis.com OR run.googleapis.com OR cloudbuild.googleapis.com OR orgpolicy.googleapis.com)'
```

## UAP organization-policy preflight

Before continuing, verify that the project is allowed to bind IAM v3 Unified Access Policies:

```bash
gcloud org-policies describe \
  constraints/iam.managed.disableAccessPolicyBinding \
  --effective \
  --project="${PROJECT_ID}"
```

If the effective policy contains:

```text
enforce: true
```

stop the deployment before creating the UAP Policy Binding.

An enforced:

```text
constraints/iam.managed.disableAccessPolicyBinding
```

prevents IAM v3 access policies from being bound to resources.

An approved Organization Policy exception is required for the project before the UAP Policy Binding step can succeed.

Do not attempt to work around this restriction by granting additional IAM roles.

If the constraint is not enforced, continue with the deployment.

---

# 5. Validate Python dependencies

Create and activate a virtual environment if desired:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the pinned dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

The root and agent dependency files are intentionally aligned.

---

# 6. Run local tests before cloud deployment

Run the authentication unit tests:

```bash
python -m unittest tests/test_agent_auth.py
```

Run a syntax check:

```bash
python -m compileall -q agent mcp-server deploy
```

The GitHub Actions workflows contain additional HTTP and container integration coverage.

Do not continue if local validation fails.

---

# 7. Deploy the MCP server to Cloud Run

Cloud Run source deployment uses Cloud Build to build the container image.

In a fresh Google Cloud project, the default Cloud Build identity may be the Compute Engine default service account. Do not assume that this identity already has the permissions required for a Cloud Run source deployment.

Retrieve the build service account used by the project:

```bash
export BUILD_SERVICE_ACCOUNT="$(
  gcloud builds get-default-service-account \
    --project="${PROJECT_ID}"
)"
```

Verify:

```bash
echo "${BUILD_SERVICE_ACCOUNT}"
```

The value must not be empty.

Check:

```bash
if [[ -z "${BUILD_SERVICE_ACCOUNT}" ]]; then
  echo "ERROR: unable to determine the default Cloud Build service account"
  exit 1
fi
```

Grant the Cloud Run Builder role to the build service account:

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${BUILD_SERVICE_ACCOUNT}" \
  --role="roles/run.builder"
```

Allow a short period for IAM propagation before continuing.

The source-build path requires the build identity to access build artifacts and objects used during the deployment.

A fresh-project deployment may otherwise fail with errors such as:

```text
storage.objects.get permission denied
```

or with a Cloud Run source-build permission failure.

If this occurs, verify:

```text
1. The correct Cloud Build service account was identified.
2. roles/run.builder is granted to that service account.
3. The IAM change has had time to propagate.
```

Do not grant broad Storage roles unless the remaining error proves that an additional Storage permission is required in the target environment.

Deploy the synthetic MCP server:

```bash
gcloud run deploy "${MCP_SERVICE}" \
  --source="mcp-server" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --no-allow-unauthenticated
```

Retrieve the Cloud Run service URL:

```bash
export MCP_BASE_URL="$(
  gcloud run services describe "${MCP_SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format='value(status.url)'
)"
```

Set the MCP endpoint:

```bash
export MCP_URL="${MCP_BASE_URL}/mcp"
```

Verify:

```bash
echo "${MCP_URL}"
```

Expected form:

```text
https://<cloud-run-service-host>/mcp
```

Confirm that the value is not empty:

```bash
if [[ -z "${MCP_BASE_URL}" || -z "${MCP_URL}" ]]; then
  echo "ERROR: MCP Cloud Run URL was not captured."
  exit 1
fi
```
---

# 8. Register the MCP server in Agent Registry

The repository contains the Agent Registry MCP tool specification:

```text
mcp-server/toolspec.json
```

Before registration, validate that the file is valid JSON:

```bash
jq . mcp-server/toolspec.json
```

Every MCP tool registered through a tool specification must include an `inputSchema`.

Validate that every tool contains one:

```bash
jq -e 'all(.tools[]; has("inputSchema"))' \
  mcp-server/toolspec.json
```

Expected result:

```text
true
```

If the command does not return `true`, stop before attempting Agent Registry registration.

The validated tool specification contains:

```text
read_customer_profile
  required input:
    customer_id

update_customer_profile
  required input:
    customer_id

  optional input:
    email
```

A tool definition containing only:

```text
name
description
```

is insufficient for the current Agent Registry tool-spec validation and can fail with an error similar to:

```text
Invalid MCP tool spec content:
tools.0: inputSchema is required
```

Register the Cloud Run MCP endpoint together with its tool metadata:

```bash
export MCP_REGISTRY_RESOURCE="$(
  gcloud agent-registry services create "${MCP_REGISTRY_SERVICE}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --display-name="Customer Profile MCP Server" \
    --mcp-server-spec-type=tool-spec \
    --mcp-server-spec-content="mcp-server/toolspec.json" \
    --interfaces="url=${MCP_URL},protocolBinding=jsonrpc" \
    --format='value(registryResource)'
)"
```

Verify that the registration returned a resource:

```bash
echo "${MCP_REGISTRY_RESOURCE}"
```

Fail early if it is empty:

```bash
if [[ -z "${MCP_REGISTRY_RESOURCE}" ]]; then
  echo "ERROR: MCP Agent Registry resource was not created."
  exit 1
fi
```

Extract the generated MCP server ID:

```bash
export MCP_SERVER_ID="${MCP_REGISTRY_RESOURCE##*/}"
```

Verify:

```bash
echo "MCP_REGISTRY_RESOURCE=${MCP_REGISTRY_RESOURCE}"
echo "MCP_SERVER_ID=${MCP_SERVER_ID}"
```

List the registered MCP servers:

```bash
gcloud agent-registry mcp-servers list \
  --project="${PROJECT_ID}" \
  --location="${REGION}"
```

Confirm that the registered tool metadata represents both:

```text
read_customer_profile
update_customer_profile
```

Registration makes the MCP destination and tool metadata discoverable through Agent Registry.

Registration does not grant the Agent Identity permission to invoke the MCP server or its tools.

Those permissions are configured separately through IAP egress authorization and Unified Access Policy.

---

# 9. Register the Vertex AI destination

The validated Runtime uses Gemini through the Vertex AI mTLS hostname:

```text
aiplatform.mtls.googleapis.com
```

Register that destination as an Agent Registry endpoint:

```bash
export VERTEX_REGISTRY_RESOURCE="$(
  gcloud agent-registry services create "${VERTEX_ENDPOINT_SERVICE}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --display-name="Vertex AI mTLS Endpoint" \
    --endpoint-spec-type=no-spec \
    --interfaces="url=https://aiplatform.mtls.googleapis.com,protocolBinding=jsonrpc" \
    --format='value(registryResource)'
)"
```

Verify that the registration returned a resource:

```bash
echo "${VERTEX_REGISTRY_RESOURCE}"
```

Fail early if it is empty:

```bash
if [[ -z "${VERTEX_REGISTRY_RESOURCE}" ]]; then
  echo "ERROR: Vertex Agent Registry endpoint was not created."
  exit 1
fi
```

Extract the endpoint ID:

```bash
export VERTEX_ENDPOINT_ID="${VERTEX_REGISTRY_RESOURCE##*/}"
```

Verify:

```bash
echo "VERTEX_REGISTRY_RESOURCE=${VERTEX_REGISTRY_RESOURCE}"
echo "VERTEX_ENDPOINT_ID=${VERTEX_ENDPOINT_ID}"
```

List the registered endpoints:

```bash
gcloud agent-registry endpoints list \
  --project="${PROJECT_ID}" \
  --location="${REGION}"
```

Agent Gateway hostname matching is exact.

If the Runtime or SDK resolves a different Vertex AI hostname in another environment, register the exact hostname that appears in Agent Gateway logs before enabling enforcement.

## Why this registration is required

The Agent Gateway and Agent Runtime can be created even when the Vertex AI endpoint is not registered.

However, once Agent-to-Anywhere Gateway enforcement is active, model traffic to an unregistered Vertex destination is denied.

A controlled negative test was performed by deliberately skipping this registration.

The Runtime and Gateway were created successfully, and MCP discovery still worked.

The model request then failed with:

```text
403 Forbidden
Egress request is not authorized.
```

Agent Gateway logs showed:

```text
hostname         = aiplatform.mtls.googleapis.com
registryResource = null
result           = DENIED
```

At the same time, the registered MCP server showed successful discovery traffic:

```text
initialize                 ALLOWED
notifications/initialized  ALLOWED
tools/list                  ALLOWED
```

This confirms that Vertex endpoint registration is not required for Gateway creation, but it is required for governed Gemini model traffic.

The required sequence is therefore:

```text
Register Vertex endpoint
→ grant Agent Identity IAP egress on that endpoint
→ allow UAP registered-endpoint traffic
→ invoke Gemini through Agent Gateway
```

Do not skip this step when the agent uses Gemini through the governed Agent Gateway path.

---

# 10. Create the Agent Gateway

Create the Gateway configuration:

```bash
cat > build/agent-gateway.yaml <<EOF
name: ${AGENT_GATEWAY_NAME}

protocols:
  - MCP

googleManaged:
  governedAccessPath: AGENT_TO_ANYWHERE

registries:
  - //agentregistry.googleapis.com/projects/${PROJECT_ID}/locations/${REGION}
EOF
```

Create the Gateway:

```bash
gcloud network-services agent-gateways import "${AGENT_GATEWAY_NAME}" \
  --source="build/agent-gateway.yaml" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

Verify:

```bash
gcloud network-services agent-gateways describe "${AGENT_GATEWAY_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

Confirm:

```text
governedAccessPath = AGENT_TO_ANYWHERE
protocols contains MCP
regional Agent Registry is attached
```

---

# 11. Bootstrap IAP authorization in DRY_RUN

Do not immediately place a new Runtime behind an enforcing default-deny Gateway before its destination policies exist.

First render the IAP authorization extension template:

```bash
envsubst \
  < policies/iap-authz-extension.yaml \
  > build/iap-authz-extension-enforce.yaml
```

Create a temporary DRY_RUN version:

```bash
sed \
  '/iapPolicyVersion:/a\  iamEnforcementMode: "DRY_RUN"' \
  build/iap-authz-extension-enforce.yaml \
  > build/iap-authz-extension-dry-run.yaml
```

Inspect it:

```bash
cat build/iap-authz-extension-dry-run.yaml
```

It must contain:

```yaml
service: iap.googleapis.com
failOpen: false
timeout: 1s
metadata:
  iapPolicyVersion: "V2"
  iamEnforcementMode: "DRY_RUN"
```

Import the extension:

```bash
gcloud service-extensions authz-extensions import "${AUTHZ_EXTENSION_NAME}" \
  --source="build/iap-authz-extension-dry-run.yaml" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

Verify:

```bash
gcloud service-extensions authz-extensions describe "${AUTHZ_EXTENSION_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

---

# 12. Attach the authorization extension to Agent Gateway

Render the Network Security Authorization Policy:

```bash
envsubst \
  < policies/gateway-authz-policy.yaml \
  > build/gateway-authz-policy.yaml
```

Inspect:

```bash
cat build/gateway-authz-policy.yaml
```

The important fields must be:

```text
target      = Agent Gateway
profile     = REQUEST_AUTHZ
action      = CUSTOM
provider    = IAP Authorization Extension
```

Create the policy:

```bash
gcloud network-security authz-policies import "${AUTHZ_POLICY_NAME}" \
  --source="build/gateway-authz-policy.yaml" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

Verify:

```bash
gcloud network-security authz-policies describe "${AUTHZ_POLICY_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

---

# 13. Validate Agent Runtime configuration before creation

The deployment script requires:

```text
GOOGLE_CLOUD_PROJECT
GOOGLE_CLOUD_REGION
AGENT_GATEWAY_NAME
MCP_URL
```

Export them:

```bash
export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
export GOOGLE_CLOUD_REGION="${REGION}"
export AGENT_GATEWAY_NAME="${AGENT_GATEWAY_NAME}"
export MCP_URL="${MCP_URL}"
```

Run configuration validation without creating cloud resources:

```bash
python deploy/deploy_agent.py
```

Expected:

```text
Agent Runtime configuration validated
DRY VALIDATION ONLY
No cloud resources created.
```

---

# 14. Deploy Agent Runtime

Deploy the agent:

```bash
python deploy/deploy_agent.py --deploy \
  | tee build/runtime-deployment.log
```

The script creates the Runtime with:

```text
identity_type = AGENT_IDENTITY
Agent-to-Anywhere Agent Gateway
MCP_URL
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False
```

Capture the Runtime resource from the deployment output:

```bash
export RUNTIME_RESOURCE="$(
  awk '/^Resource:/ {print $2}' build/runtime-deployment.log \
  | tail -1
)"
```

Extract the Runtime ID:

```bash
export RUNTIME_ID="${RUNTIME_RESOURCE##*/}"
```

Verify both values:

```bash
echo "RUNTIME_RESOURCE=${RUNTIME_RESOURCE}"
echo "RUNTIME_ID=${RUNTIME_ID}"
```

Fail early if either value is empty:

```bash
if [[ -z "${RUNTIME_RESOURCE}" || -z "${RUNTIME_ID}" ]]; then
  echo "ERROR: Runtime resource or Runtime ID was not captured."
  exit 1
fi
```

Expected Runtime resource form:

```text
projects/<PROJECT_ID>/locations/<REGION>/reasoningEngines/<RUNTIME_ID>
```

On a fresh project, the first Runtime deployment can temporarily fail with an Agent Gateway permission error for the Vertex AI Service Agent.

If the Vertex AI Service Agent already has:

```text
roles/aiplatform.serviceAgent
```

do not immediately grant additional Network Services roles.

Allow time for service-agent and IAM propagation, then retry the same deployment command.

The Vertex AI Service Agent and the Runtime Agent Identity are different identities:

```text
Vertex AI Service Agent
→ Google-managed control-plane identity
→ used while Vertex AI provisions and manages Runtime resources

Agent Identity
→ Runtime execution identity
→ used for Agent Gateway, MCP, IAP, and UAP authorization
```

---

# 15. Retrieve the actual Agent Identity

Do not construct the Agent Identity from project number, organization ID, Runtime ID, or trust-domain assumptions.

Retrieve the effective identity issued to the Runtime directly from the Runtime API:

```bash
export AGENT_EFFECTIVE_IDENTITY="$(
  curl -fsS \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${RUNTIME_ID}" \
  | jq -r '.spec.effectiveIdentity // empty'
)"
```

Verify:

```bash
echo "${AGENT_EFFECTIVE_IDENTITY}"
```

Fail early if no identity was returned:

```bash
if [[ -z "${AGENT_EFFECTIVE_IDENTITY}" ]]; then
  echo "ERROR: Runtime effective Agent Identity was not returned."
  exit 1
fi
```

The Runtime API returns the effective identity in a form beginning with:

```text
agents.global.
```

For example:

```text
agents.global.<trust-domain>/resources/aiplatform/projects/<PROJECT_NUMBER>/locations/<REGION>/reasoningEngines/<RUNTIME_ID>
```

This value is the Runtime effective identity.

It is not yet in IAM-member format.

Create the IAM principal representation:

```bash
export AGENT_PRINCIPAL="principal://${AGENT_EFFECTIVE_IDENTITY}"
```

Verify both representations:

```bash
echo "Effective identity:"
echo "${AGENT_EFFECTIVE_IDENTITY}"

echo
echo "IAM principal:"
echo "${AGENT_PRINCIPAL}"
```

Expected forms:

```text
Effective identity:
agents.global.<trust-domain>/resources/aiplatform/...

IAM principal:
principal://agents.global.<trust-domain>/resources/aiplatform/...
```

Validate the relationship:

```bash
if [[ "${AGENT_PRINCIPAL}" != "principal://${AGENT_EFFECTIVE_IDENTITY}" ]]; then
  echo "ERROR: IAM principal was not derived correctly."
  exit 1
fi
```

The trust domain can differ between organization-backed and organization-less projects.

Always retrieve the Runtime effective identity dynamically and derive the IAM principal from that returned value.

Use:

```text
${AGENT_EFFECTIVE_IDENTITY}
```

when comparing against:

```text
spec.effectiveIdentity
```

Use:

```text
${AGENT_PRINCIPAL}
```

when configuring IAM, IAP, or UAP principal bindings.

---

# 16. Grant Cloud Run invocation permission

The agent obtains an ID token for the Cloud Run MCP destination.

Allow the Agent Identity to invoke the MCP service:

```bash
gcloud run services add-iam-policy-binding "${MCP_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --member="${AGENT_PRINCIPAL}" \
  --role="roles/run.invoker"
```

Verify:

```bash
gcloud run services get-iam-policy "${MCP_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}"
```

---

# 17. Grant Agent Registry discovery permission

Allow the agent to discover registered destinations:

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="${AGENT_PRINCIPAL}" \
  --role="roles/agentregistry.viewer"
```

Do not grant Agent Registry Editor or Admin to the Runtime agent.

The agent needs discovery capability, not registry mutation capability.

---

# 18. Grant IAP egress access to the registered MCP resource

Grant the Runtime Agent Identity permission to egress specifically to the registered MCP server.

Use a resource-level IAP binding:

```bash
gcloud iap web add-iam-policy-binding \
  --project="${PROJECT_ID}" \
  --resource-type=agent-registry \
  --mcp-server="${MCP_SERVER_ID}" \
  --region="${REGION}" \
  --member="${AGENT_PRINCIPAL}" \
  --role="roles/iap.egressor"
```

Verify the binding:

```bash
gcloud iap web get-iam-policy \
  --project="${PROJECT_ID}" \
  --resource-type=agent-registry \
  --mcp-server="${MCP_SERVER_ID}" \
  --region="${REGION}"
```

Confirm that the policy contains:

```text
role: roles/iap.egressor
```

for:

```text
${AGENT_PRINCIPAL}
```

This binding is intentionally scoped to the specific MCP server resource.

It does not grant egress permission across the entire project or every Agent Registry resource.

Conceptually:

```text
Agent Principal
  ↓
roles/iap.egressor
  ↓
Registered MCP server
```

This is the destination-level authorization layer.

Fine-grained authorization for individual MCP tool calls is enforced separately by the Unified Access Policy.

Do not use a project-wide egress grant unless broader access to all registered destinations is explicitly intended.

---

# 19. Grant IAP egress access to the Vertex endpoint

Grant the same Runtime Agent Identity egress permission specifically to the registered Vertex AI endpoint:

```bash
gcloud iap web add-iam-policy-binding \
  --project="${PROJECT_ID}" \
  --resource-type=agent-registry \
  --endpoint="${VERTEX_ENDPOINT_ID}" \
  --region="${REGION}" \
  --member="${AGENT_PRINCIPAL}" \
  --role="roles/iap.egressor"
```

Verify:

```bash
gcloud iap web get-iam-policy \
  --project="${PROJECT_ID}" \
  --resource-type=agent-registry \
  --endpoint="${VERTEX_ENDPOINT_ID}" \
  --region="${REGION}"
```

Confirm that the endpoint policy contains:

```text
role: roles/iap.egressor
```

for:

```text
${AGENT_PRINCIPAL}
```

The MCP server and Vertex endpoint are authorized separately so that the lab preserves resource-level least privilege:

```text
Agent Principal
  ├── roles/iap.egressor → registered MCP server
  └── roles/iap.egressor → registered Vertex endpoint
```

A broader Agent Registry-level IAP policy can authorize access to all registered destinations, but this lab deliberately uses per-resource bindings.

This prevents newly registered resources from automatically becoming reachable by the agent.

The previous `set-iam-policy` JSON-file approach is intentionally not used here.

Using:

```text
gcloud iap web add-iam-policy-binding
```

is additive and avoids replacing the full resource policy or requiring an `etag`.

It also avoids JSON-shape compatibility errors such as:

```text
Unknown name "policy" at 'policy'
```
---

# 20. Render the Unified Access Policy

The UAP template uses:

```text
${AGENT_PRINCIPAL}
```

Render it:

```bash
envsubst \
  < policies/customer-profile-tools-uap.json \
  > build/customer-profile-tools-uap.json
```

Inspect:

```bash
cat build/customer-profile-tools-uap.json | jq .
```

Confirm that:

```text
${AGENT_PRINCIPAL}
```

does not remain in the rendered file.

Check:

```bash
if grep -q '\${' build/customer-profile-tools-uap.json; then
  echo "ERROR: unresolved placeholders remain"
  exit 1
else
  echo "PASS: UAP fully rendered"
fi
```

---

# 21. Create the Unified Access Policy

Create the UAP:

```bash
gcloud iam access-policies create "${ACCESS_POLICY_NAME}" \
  --details-rules="build/customer-profile-tools-uap.json" \
  --project="${PROJECT_ID}" \
  --location=global
```

Verify:

```bash
gcloud iam access-policies describe "${ACCESS_POLICY_NAME}" \
  --project="${PROJECT_ID}" \
  --location=global
```

The policy must contain four rules:

```text
ALLOW MCP discovery and handshake
ALLOW registered Vertex endpoints
ALLOW read_customer_profile
DENY update_customer_profile
```

The permission must be:

```text
iap.googleapis.com/resources.egressViaIAP
```

---

# 22. Bind the UAP to the project

Creating the Unified Access Policy does not make it effective by itself.

The UAP must be bound to the target project using an IAM v3 Policy Binding.

Create the binding:

```bash
gcloud iam policy-bindings create "${POLICY_BINDING_NAME}" \
  --policy="projects/${PROJECT_ID}/locations/global/accessPolicies/${ACCESS_POLICY_NAME}" \
  --target-resource="//cloudresourcemanager.googleapis.com/projects/${PROJECT_ID}" \
  --project="${PROJECT_ID}" \
  --location=global
```

Verify:

```bash
gcloud iam policy-bindings describe "${POLICY_BINDING_NAME}" \
  --project="${PROJECT_ID}" \
  --location=global
```

Expected target:

```text
//cloudresourcemanager.googleapis.com/projects/${PROJECT_ID}
```

## Organization Policy failure

If the create command fails with an error containing:

```text
constraints/iam.managed.disableAccessPolicyBinding
```

and:

```text
CUSTOM_ORG_POLICY_VIOLATION
```

do not modify the UAP and do not grant additional IAM roles.

This means the effective Organization Policy prevents IAM v3 access policies from being bound to resources.

Re-check the effective constraint:

```bash
gcloud org-policies describe \
  constraints/iam.managed.disableAccessPolicyBinding \
  --effective \
  --project="${PROJECT_ID}"
```

If the result contains:

```text
enforce: true
```

the project requires an approved Organization Policy exception before this step can succeed.

Do not continue to enforcement testing until the policy binding has been created successfully.

---

# 23. Wait for policy propagation

Do not immediately conclude that a policy is incorrect after creation or modification.

Wait several minutes.

Recommended:

```bash
echo "Waiting 5 minutes for UAP propagation..."
sleep 300
```

During the validated implementation, some misleading failures occurred because policy changes were tested too quickly.

---

# 24. Switch IAP from DRY_RUN to enforcement

The repository extension template intentionally represents the final enforcement configuration and does not contain:

```text
iamEnforcementMode: DRY_RUN
```

Import the enforcement version:

```bash
gcloud service-extensions authz-extensions import "${AUTHZ_EXTENSION_NAME}" \
  --source="build/iap-authz-extension-enforce.yaml" \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

Verify:

```bash
gcloud service-extensions authz-extensions describe "${AUTHZ_EXTENSION_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --format=json \
| jq '{
    name,
    service,
    failOpen,
    timeout,
    metadata
  }'
```

Expected:

```text
service          = iap.googleapis.com
failOpen         = false
timeout          = 1s
iapPolicyVersion = V2
```

`iamEnforcementMode` should no longer be `DRY_RUN`.

---

# 25. Verify Runtime-to-Gateway association

Before querying the Runtime API, confirm that the Runtime ID is available:

```bash
if [[ -z "${RUNTIME_ID}" ]]; then
  echo "ERROR: RUNTIME_ID is empty."
  exit 1
fi
```

Check the Runtime API directly:

```bash
curl -fsS \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${RUNTIME_ID}" \
| jq '.spec.deploymentSpec.agentGatewayConfig'
```

Expected result:

```text
agentToAnywhereConfig.agentGateway
```

must reference:

```text
projects/${PROJECT_ID}/locations/${REGION}/agentGateways/${AGENT_GATEWAY_NAME}
```

If the result is:

```text
null
```

stop before testing MCP authorization.

First confirm that:

```text
RUNTIME_ID is correct
AGENT_GATEWAY_NAME is correct
the Runtime deployment completed successfully
the Runtime was configured with the Agent-to-Anywhere Gateway
```

Do not assume that a `null` result proves a Gateway-binding defect until the Runtime resource being queried has been verified.

A missing or empty Runtime ID can produce misleading REST errors or query the wrong resource path.

---

# 26. Validate Agent Identity again

Retrieve the Runtime's current effective identity again before testing authorization:

```bash
CURRENT_EFFECTIVE_IDENTITY="$(
  curl -fsS \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${RUNTIME_ID}" \
  | jq -r '.spec.effectiveIdentity // empty'
)"
```

Display the values being compared:

```bash
echo "Runtime effective identity:"
echo "${CURRENT_EFFECTIVE_IDENTITY}"

echo
echo "Expected effective identity:"
echo "${AGENT_EFFECTIVE_IDENTITY}"

echo
echo "IAM principal used for IAM/IAP/UAP:"
echo "${AGENT_PRINCIPAL}"
```

Validate both identity representations:

```bash
if [[ -z "${CURRENT_EFFECTIVE_IDENTITY}" ]]; then
  echo "FAIL: Runtime effective identity was not returned."
  exit 1
fi

if [[ "${CURRENT_EFFECTIVE_IDENTITY}" != "${AGENT_EFFECTIVE_IDENTITY}" ]]; then
  echo "FAIL: Runtime effective identity has changed."
  exit 1
fi

if [[ "${AGENT_PRINCIPAL}" != "principal://${CURRENT_EFFECTIVE_IDENTITY}" ]]; then
  echo "FAIL: IAM principal does not match the Runtime effective identity."
  exit 1
fi

echo "PASS: Runtime Agent Identity matches the identity used for IAM, IAP, and UAP."
```

The Runtime API returns:

```text
agents.global....
```

while IAM, IAP, and UAP bindings use:

```text
principal://agents.global....
```

These are two representations of the same Agent Identity and should not be compared as identical strings.

If the Runtime was deleted and recreated, the new Runtime receives a new effective Agent Identity.

In that case, update all authorization references that used the previous identity:

```text
Cloud Run Invoker binding
Agent Registry Viewer binding
MCP resource IAP egress binding
Vertex endpoint IAP egress binding
UAP principal
```

Do not reuse authorization bindings belonging to a deleted Runtime identity.

---

# 27. Validate the allowed read path

Open the deployed Agent Runtime in the Google Cloud console and start an interactive Playground session.

Send:

```text
Read the customer profile for customer_id CUST-1001.
Use the MCP tool.
```

The agent should select:

```text
read_customer_profile
```

with:

```text
customer_id = CUST-1001
```

Expected MCP result:

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

Expected authorization outcome:

```text
ALLOW
```

Expected downstream behavior:

```text
read_customer_profile
→ selected by the model
→ authorized by policy
→ forwarded through Agent Gateway
→ executed by the MCP server
→ result returned to the agent
```

If the Playground instead returns:

```text
403 Forbidden
Egress request is not authorized.
```

do not immediately modify the MCP configuration.

Inspect the Agent Gateway logs first.

If the denied hostname is:

```text
aiplatform.mtls.googleapis.com
```

and:

```text
registryResource = null
```

verify:

```text
Vertex AI endpoint is registered in Agent Registry
Agent Principal has roles/iap.egressor on the registered Vertex endpoint
UAP allows registered ENDPOINT traffic
```

A failure reaching Vertex AI occurs before MCP tool execution and should not be diagnosed as an MCP tool-policy failure.

---

# 28. Validate the denied update path

Use the same interactive Playground session.

Send:

```text
Call update_customer_profile for customer_id CUST-1001
and set email to blocked@example.com.
Use the MCP tool.
```

The model should select:

```text
update_customer_profile
```

Expected authorization outcome:

```text
DENY
```

Expected Runtime behavior:

```text
tool execution fails
```

Expected downstream behavior:

```text
Cloud Run does NOT execute update_customer_profile
```

The important security result is:

```text
model selects update_customer_profile
→ authorization layer denies execution
→ update request does not reach the MCP server as a tool execution
```

The model selecting a tool does not grant permission to execute that tool.

Do not treat the Playground error alone as sufficient proof of successful authorization enforcement.

Continue with the Agent Gateway and Cloud Run log validation steps below to confirm that the denied mutation did not execute downstream.

---

# 29. Inspect Agent Gateway logs

Example query:

```bash
gcloud logging read \
  'resource.type="networkservices.googleapis.com/Gateway"' \
  --project="${PROJECT_ID}" \
  --freshness=30m \
  --limit=100 \
  --order=asc \
  --format=json
```

Useful fields include:

```text
jsonPayload.agentGatewayInfo.agentRegistryResource
jsonPayload.agentGatewayInfo.mcpInfo.method
jsonPayload.agentGatewayInfo.mcpInfo.parameter
jsonPayload.authzPolicyInfo.result
jsonPayload.enforcedGatewaySecurityPolicy.hostname
jsonPayload.enforcedGatewaySecurityPolicy.requestWasTlsIntercepted
```

Expected MCP discovery sequence can include:

```text
initialize
notifications/initialized
tools/list
```

---

# 30. Inspect Cloud Run execution evidence

Query the MCP service:

```bash
gcloud logging read \
  "resource.type=\"cloud_run_revision\"
   resource.labels.service_name=\"${MCP_SERVICE}\"" \
  --project="${PROJECT_ID}" \
  --freshness=30m \
  --limit=100 \
  --order=asc \
  --format=json
```

For the read test:

```text
tool execution should be visible
```

For the denied update test:

```text
update tool execution should be absent
```

Do not rely on only one logging layer when proving whether a tool executed.

---

# 31. Known observability behavior

During validation, separate Agent Gateway or IAP `tools/call` records were not always emitted for every successful or denied tool request.

Therefore correlate:

```text
Agent Runtime events
+
Agent Gateway logs
+
IAP audit logs
+
Cloud Run request logs
```

Downstream Cloud Run evidence is particularly important for proving that a denied mutation never executed.

---

# 32. Bound-token compatibility baseline

The deployment currently sets:

```text
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False
```

This is deliberate.

The validated experiment was:

```text
False
→ read succeeds

True
→ Agent Gateway ALLOWED the Vertex request
→ Vertex AI returned 401 UNAUTHENTICATED

False
→ read succeeds again
```

Do not change this setting as part of unrelated troubleshooting.

Re-test it separately when Google Cloud platform behavior changes.

---

# 33. Troubleshooting order

When a deployment fails, inspect the layers in this order:

```text
1. Cloud Run MCP service
2. Agent Registry MCP registration
3. Agent Registry Vertex endpoint registration
4. Agent Gateway configuration
5. Agent Runtime Gateway association
6. Runtime effective Agent Identity
7. Agent Registry discovery IAM
8. IAP egress bindings
9. Network Security Authorization Policy
10. IAP Authorization Extension
11. Unified Access Policy
12. UAP Policy Binding
13. Policy propagation
14. Gateway logs
15. Cloud Run logs
```

Do not modify multiple layers at the same time.

---

# 34. Common failure: Runtime receives 498

Possible cause:

```text
Runtime was attached to an enforcing Agent Gateway
before required destinations were registered or authorized.
```

Action:

```text
Verify destination registrations.
Verify IAP egress bindings.
Verify UAP.
Use DRY_RUN during initial bootstrap.
```

---

# 35. Common failure: tools/list denied

The MCP protocol performs discovery before tool execution.

The validated discovery rule is:

```text
destination.is_registered == true &&
destination.agent_registry.mcp_server.method != 'tools/call'
```

Without MCP discovery access, the agent cannot establish normal tool operation.

---

# 36. Common failure: Vertex returns 401

If Gateway logs show:

```text
authorization result = ALLOWED
```

but Vertex AI returns:

```text
401 UNAUTHENTICATED
```

check the bound-token compatibility setting before modifying UAP.

Known-good lab value:

```text
GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES=False
```

---

# 37. Common failure: policy appears unchanged

UAP changes can require several minutes to propagate.

Do not repeatedly update CEL expressions while the previous version may still be propagating.

Use:

```text
update
wait
test once
inspect evidence
```

---

# 38. Common failure: recreated Runtime no longer works

Every newly created Agent Runtime receives a new immutable Runtime ID and a new effective Agent Identity.

Do not reuse the identity or authorization bindings from a deleted Runtime.

After recreating the Runtime, capture the new resource and Runtime ID:

```bash
export RUNTIME_RESOURCE="$(
  awk '/^Resource:/ {print $2}' build/runtime-deployment.log \
  | tail -1
)"

export RUNTIME_ID="${RUNTIME_RESOURCE##*/}"
```

Verify:

```bash
echo "RUNTIME_RESOURCE=${RUNTIME_RESOURCE}"
echo "RUNTIME_ID=${RUNTIME_ID}"
```

Retrieve the new effective Agent Identity:

```bash
export AGENT_EFFECTIVE_IDENTITY="$(
  curl -fsS \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${RUNTIME_ID}" \
  | jq -r '.spec.effectiveIdentity // empty'
)"
```

Create the IAM principal representation:

```bash
export AGENT_PRINCIPAL="principal://${AGENT_EFFECTIVE_IDENTITY}"
```

Verify:

```bash
echo "AGENT_EFFECTIVE_IDENTITY=${AGENT_EFFECTIVE_IDENTITY}"
echo "AGENT_PRINCIPAL=${AGENT_PRINCIPAL}"
```

Then update every authorization reference that belonged to the previous Runtime identity:

```text
Cloud Run Invoker binding
Agent Registry Viewer binding
MCP resource IAP egress binding
Vertex endpoint IAP egress binding
UAP principal
```

Re-render the Unified Access Policy after updating:

```text
${AGENT_PRINCIPAL}
```

and update the deployed UAP before testing the recreated Runtime.

Do not reuse permissions or policy principals belonging to the deleted Runtime identity.

---

# 39. Final acceptance checklist

Deployment is complete only when all of the following are true:

```text
[ ] Required Google Cloud APIs are enabled
[ ] Organization Policy allows IAM v3 access-policy binding
[ ] Cloud Build service account is identified
[ ] Cloud Build service account has roles/run.builder

[ ] MCP server is deployed to Cloud Run
[ ] MCP server requires authentication
[ ] MCP_URL is captured successfully

[ ] MCP toolspec is valid JSON
[ ] Every MCP tool contains inputSchema
[ ] MCP server is registered in Agent Registry
[ ] read_customer_profile is registered
[ ] update_customer_profile is registered

[ ] Vertex AI mTLS endpoint is registered in Agent Registry
[ ] Vertex endpoint ID is captured successfully

[ ] Agent Gateway is created in AGENT_TO_ANYWHERE mode
[ ] Regional Agent Registry is attached to the Gateway

[ ] IAP V2 Authorization Extension is created
[ ] Network Security REQUEST_AUTHZ policy is attached
[ ] Runtime is deployed with AGENT_IDENTITY
[ ] Runtime ID is captured successfully
[ ] Runtime is associated with the intended Agent Gateway

[ ] Runtime effective Agent Identity is retrieved dynamically
[ ] AGENT_EFFECTIVE_IDENTITY begins with agents.global.
[ ] AGENT_PRINCIPAL is derived as principal://${AGENT_EFFECTIVE_IDENTITY}

[ ] Cloud Run Invoker is granted to the Runtime Agent Principal
[ ] Agent Registry Viewer is granted to the Runtime Agent Principal

[ ] roles/iap.egressor is granted on the registered MCP server
[ ] roles/iap.egressor is granted on the registered Vertex endpoint

[ ] Unified Access Policy is rendered with the current Agent Principal
[ ] Unified Access Policy is created successfully
[ ] UAP contains the four expected authorization rules
[ ] UAP is bound to the target project
[ ] Policy propagation time has been allowed

[ ] IAP enforcement is enabled
[ ] Playground session can reach Gemini through Agent Gateway
[ ] MCP initialize is allowed
[ ] MCP notifications/initialized is allowed
[ ] MCP tools/list is allowed

[ ] read_customer_profile is selected by the model
[ ] read_customer_profile is authorized
[ ] read_customer_profile executes successfully

[ ] update_customer_profile is selected by the model
[ ] update_customer_profile is denied
[ ] denied update does not execute on Cloud Run

[ ] Agent Gateway logs support the authorization result
[ ] Cloud Run logs confirm downstream execution behavior
```

The final acceptance condition is not simply that the agent responds successfully.

The deployment must demonstrate both:

```text
positive authorization
+
negative authorization
```

Specifically:

```text
read_customer_profile
→ ALLOWED
→ EXECUTED
```

and:

```text
update_customer_profile
→ DENIED
→ NOT EXECUTED
```

---

# 40. Known-good security outcome

The final security model is:

```text
Model capability
≠
execution authorization
```

and:

```text
Registered destination
≠
authorized operation
```

The validated final state is:

```text
Gemini inference                         ALLOWED
MCP discovery                            ALLOWED
read_customer_profile                    ALLOWED
update_customer_profile                  DENIED
Denied mutation reaches downstream       NO
```

For detailed policy behavior and investigation history, see:

```text
docs/validation.md
```

For the architecture, see:

```text
docs/architecture.md
```

---

# 41. Clean up lab resources

After completing the lab, remove the resources if they are no longer required.

Cleanup is especially important for temporary test environments because the lab creates managed runtime, networking, registry, Cloud Run, IAM, and policy resources.

## Option 1 — Delete a dedicated test project

If the Google Cloud project was created exclusively for this lab and contains no other workloads, deleting the project is the simplest complete cleanup.

First confirm the active project:

```bash
echo "${PROJECT_ID}"
gcloud config get-value project
```

If the project is dedicated only to this lab:

```bash
gcloud projects delete "${PROJECT_ID}"
```

Do not delete the project if it contains any unrelated resources or workloads.

If the project is shared, use the targeted cleanup procedure below.

---

## Option 2 — Remove only the lab resources

Use this option when the lab was deployed into an existing or shared Google Cloud project.

### 41.1 Confirm the target project

Before running any destructive command, verify that all required deployment variables are still available in the current shell:

```bash
REQUIRED_VARS=(
  PROJECT_ID
  REGION
  RUNTIME_RESOURCE
  RUNTIME_ID
  AGENT_PRINCIPAL
  MCP_SERVICE
  MCP_REGISTRY_SERVICE
  VERTEX_ENDPOINT_SERVICE
  MCP_SERVER_ID
  VERTEX_ENDPOINT_ID
  AGENT_GATEWAY_NAME
  AUTHZ_POLICY_NAME
  AUTHZ_EXTENSION_NAME
  ACCESS_POLICY_NAME
  POLICY_BINDING_NAME
)

MISSING_VARS=0

for VAR_NAME in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!VAR_NAME:-}" ]]; then
    echo "ERROR: ${VAR_NAME} is not set."
    MISSING_VARS=1
  fi
done

if [[ "${MISSING_VARS}" -ne 0 ]]; then
  echo "Cleanup stopped. Restore the missing deployment variables before continuing."
  exit 1
fi

echo "PASS: Required cleanup variables are available."
```

This prevents cleanup commands from being run with incomplete resource identifiers.

Display the important cleanup variables:

```bash
echo "PROJECT_ID=${PROJECT_ID}"
echo "REGION=${REGION}"
echo "RUNTIME_RESOURCE=${RUNTIME_RESOURCE}"
echo "AGENT_PRINCIPAL=${AGENT_PRINCIPAL}"
echo "MCP_SERVICE=${MCP_SERVICE}"
echo "MCP_REGISTRY_SERVICE=${MCP_REGISTRY_SERVICE}"
echo "VERTEX_ENDPOINT_SERVICE=${VERTEX_ENDPOINT_SERVICE}"
echo "MCP_SERVER_ID=${MCP_SERVER_ID}"
echo "VERTEX_ENDPOINT_ID=${VERTEX_ENDPOINT_ID}"
echo "AGENT_GATEWAY_NAME=${AGENT_GATEWAY_NAME}"
echo "AUTHZ_POLICY_NAME=${AUTHZ_POLICY_NAME}"
echo "AUTHZ_EXTENSION_NAME=${AUTHZ_EXTENSION_NAME}"
echo "ACCESS_POLICY_NAME=${ACCESS_POLICY_NAME}"
echo "POLICY_BINDING_NAME=${POLICY_BINDING_NAME}"
```

Confirm that the active gcloud project matches:

```bash
gcloud config get-value project
```

Require an explicit confirmation before deleting resources:

```bash
read -r -p "Type the project ID to confirm cleanup: " CLEANUP_CONFIRM

if [[ "${CLEANUP_CONFIRM}" != "${PROJECT_ID}" ]]; then
  echo "Cleanup cancelled."
  exit 1
fi
```

Do not continue if the project or resource identifiers are incorrect.

---

## 41.2 Remove Agent Registry IAP egress bindings

Remove the MCP server egress binding:

```bash
gcloud iap web remove-iam-policy-binding \
  --project="${PROJECT_ID}" \
  --resource-type=agent-registry \
  --mcp-server="${MCP_SERVER_ID}" \
  --region="${REGION}" \
  --member="${AGENT_PRINCIPAL}" \
  --role="roles/iap.egressor"
```

Remove the Vertex endpoint egress binding:

```bash
gcloud iap web remove-iam-policy-binding \
  --project="${PROJECT_ID}" \
  --resource-type=agent-registry \
  --endpoint="${VERTEX_ENDPOINT_ID}" \
  --region="${REGION}" \
  --member="${AGENT_PRINCIPAL}" \
  --role="roles/iap.egressor"
```

These commands remove only the resource-level bindings created for this lab.

---

## 41.3 Remove Agent Identity IAM bindings

Remove Cloud Run Invoker from the MCP service:

```bash
gcloud run services remove-iam-policy-binding "${MCP_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --member="${AGENT_PRINCIPAL}" \
  --role="roles/run.invoker"
```

Remove Agent Registry Viewer from the project:

```bash
gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
  --member="${AGENT_PRINCIPAL}" \
  --role="roles/agentregistry.viewer"
```

---

## 41.4 Delete the Agent Runtime

The Runtime may contain child resources such as interactive sessions.

Use the Agent Platform SDK with `force=True`:

```bash
python - <<'PY'
import os
import agentplatform

project = os.environ["PROJECT_ID"]
region = os.environ["REGION"]
runtime_resource = os.environ["RUNTIME_RESOURCE"]

client = agentplatform.Client(
    project=project,
    location=region,
)

client.runtimes.delete(
    name=runtime_resource,
    force=True,
)

print(f"Deleted Agent Runtime: {runtime_resource}")
PY
```

Runtime deletion can involve managed child resources, so verify that the Runtime is gone before deleting the Agent Gateway. The Agent Platform SDK supports `force=True` for deletion when resources such as sessions exist. :contentReference[oaicite:1]{index=1}

Wait for deletion to become visible:

```bash
for ATTEMPT in $(seq 1 30); do
  HTTP_CODE="$(
    curl -s \
      -o /tmp/runtime-delete-check.json \
      -w '%{http_code}' \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${RUNTIME_ID}"
  )"

  if [[ "${HTTP_CODE}" == "404" ]]; then
    echo "PASS: Agent Runtime deletion confirmed."
    break
  fi

  echo "Runtime still exists or deletion is propagating. Attempt ${ATTEMPT}/30..."
  sleep 10
done

if [[ "${HTTP_CODE}" != "404" ]]; then
  echo "ERROR: Agent Runtime deletion was not confirmed."
  cat /tmp/runtime-delete-check.json
  exit 1
fi
```

Do not continue with Gateway deletion until this check passes.

---

## 41.5 Delete the UAP Policy Binding

Delete the IAM v3 Policy Binding before deleting the Unified Access Policy:

```bash
gcloud iam policy-bindings delete "${POLICY_BINDING_NAME}" \
  --project="${PROJECT_ID}" \
  --location=global \
  --quiet
```

---

## 41.6 Delete the Unified Access Policy

Delete the lab UAP:

```bash
gcloud iam access-policies delete "${ACCESS_POLICY_NAME}" \
  --project="${PROJECT_ID}" \
  --location=global \
  --quiet
```

---

## 41.7 Delete the Network Security Authorization Policy

Delete the policy that attaches request authorization to the Agent Gateway:

```bash
gcloud network-security authz-policies delete "${AUTHZ_POLICY_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --quiet
```

---

## 41.8 Delete the IAP Authorization Extension

After the Network Security Authorization Policy has been removed, delete the authorization extension:

```bash
gcloud service-extensions authz-extensions delete "${AUTHZ_EXTENSION_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --quiet
```

---

## 41.9 Delete the Agent Gateway

Delete the Agent-to-Anywhere Gateway:

```bash
gcloud network-services agent-gateways delete "${AGENT_GATEWAY_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --quiet
```

---

## 41.10 Remove the Agent Registry services

Delete the registered MCP service:

```bash
gcloud agent-registry services delete "${MCP_REGISTRY_SERVICE}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --quiet
```

Delete the registered Vertex endpoint service:

```bash
gcloud agent-registry services delete "${VERTEX_ENDPOINT_SERVICE}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --quiet
```

Deleting these Agent Registry service resources removes the lab destinations from the registry.

---

## 41.11 Delete the Cloud Run MCP service

Delete the synthetic MCP server:

```bash
gcloud run services delete "${MCP_SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --quiet
```

Deleting the Cloud Run service removes its deployed revisions.

Container images created during source deployment can remain in Artifact Registry and should be reviewed separately.

---

## 41.12 Optionally remove the Cloud Run Builder IAM binding

Step 7 grants:

```text
roles/run.builder
```

to the project's default Cloud Build service account.

Retrieve that identity again if necessary:

```bash
export BUILD_SERVICE_ACCOUNT="$(
  gcloud builds get-default-service-account \
    --project="${PROJECT_ID}"
)"
```

Verify:

```bash
echo "${BUILD_SERVICE_ACCOUNT}"
```

Only remove the binding if it was added specifically for this lab and is not required by any other Cloud Run or Cloud Build workload in the project.

If it is safe to remove:

```bash
gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${BUILD_SERVICE_ACCOUNT}" \
  --role="roles/run.builder"
```

Do not remove an IAM binding that existed before the lab or is used by another workload.

---

## 41.13 Optionally delete source-build artifacts

A Cloud Run source deployment can use the Artifact Registry repository:

```text
cloud-run-source-deploy
```

Check whether it exists:

```bash
gcloud artifacts repositories describe cloud-run-source-deploy \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

Do not automatically delete this repository.

It can contain images belonging to other Cloud Run source deployments in the same project and region.

If the repository was created exclusively for this lab and contains no artifacts required by other workloads, it can be deleted:

```bash
gcloud artifacts repositories delete cloud-run-source-deploy \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --quiet
```

---

## 41.14 Restore a temporary Organization Policy exception

If a project-level exception for:

```text
constraints/iam.managed.disableAccessPolicyBinding
```

was created specifically to run this lab, restore the organization's normal policy after cleanup.

Do not modify Organization Policy unless you are authorized to do so.

If the project-level override was created only for this lab and the intended post-lab state is to inherit the parent policy, remove the project-level override:

```bash
gcloud org-policies delete \
  constraints/iam.managed.disableAccessPolicyBinding \
  --project="${PROJECT_ID}"
```

Then verify the effective policy:

```bash
gcloud org-policies describe \
  constraints/iam.managed.disableAccessPolicyBinding \
  --effective \
  --project="${PROJECT_ID}"
```

The effective result after deletion depends on the policy inherited from the parent folder or organization.

Do not use this command if the project-level policy existed before the lab.

---

## 41.15 Verify cleanup

Check that the main lab resources are gone.

Agent Runtime:

```bash
curl -fsS \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines" \
| jq '.reasoningEngines // []'
```

Agent Gateway:

```bash
gcloud network-services agent-gateways list \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

Agent Registry:

```bash
gcloud agent-registry services list \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

Cloud Run:

```bash
gcloud run services list \
  --region="${REGION}" \
  --project="${PROJECT_ID}"
```

Authorization policies:

```bash
gcloud network-security authz-policies list \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

Authorization extensions:

```bash
gcloud service-extensions authz-extensions list \
  --location="${REGION}" \
  --project="${PROJECT_ID}"
```

The cleanup is complete when the lab-specific resources no longer appear.

Do not interpret unrelated resources in a shared project as cleanup failures.

---

## Cleanup principle

The cleanup process intentionally removes only resources created for this lab.

Do not delete:

```text
shared Artifact Registry repositories
pre-existing IAM bindings
organization-level policies
unrelated Agent Registry resources
unrelated Cloud Run services
```

unless they were created exclusively for this lab and their deletion has been explicitly verified as safe.
