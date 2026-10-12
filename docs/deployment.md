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
  --project="${PROJECT_ID}"
```

Agent Registry and IAP must both be enabled when Agent Gateway policy enforcement is used.

Verify:

```bash
gcloud services list \
  --enabled \
  --project="${PROJECT_ID}" \
  --filter='name:(aiplatform.googleapis.com OR agentregistry.googleapis.com OR networkservices.googleapis.com OR networksecurity.googleapis.com OR iap.googleapis.com OR run.googleapis.com)'
```

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

---

# 8. Register the MCP server in Agent Registry

The repository contains:

```text
mcp-server/toolspec.json
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

Extract the generated MCP server ID:

```bash
export MCP_SERVER_ID="${MCP_REGISTRY_RESOURCE##*/}"
```

Verify:

```bash
echo "${MCP_REGISTRY_RESOURCE}"

gcloud agent-registry mcp-servers list \
  --project="${PROJECT_ID}" \
  --location="${REGION}"
```

Confirm that both tools are represented:

```text
read_customer_profile
update_customer_profile
```

Registration makes the destination discoverable.

Registration does not grant permission to invoke its tools.

---

# 9. Register the Vertex AI destination

The validated Runtime used Gemini through the secure Vertex AI hostname:

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

Extract the endpoint ID:

```bash
export VERTEX_ENDPOINT_ID="${VERTEX_REGISTRY_RESOURCE##*/}"
```

Verify:

```bash
echo "${VERTEX_REGISTRY_RESOURCE}"

gcloud agent-registry endpoints list \
  --project="${PROJECT_ID}" \
  --location="${REGION}"
```

Important:

Agent Gateway hostname matching is exact.

If the Runtime or SDK in a different environment resolves another Vertex hostname, register that exact standard, regional, or mTLS hostname before enforcement.

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

Extract its ID:

```bash
export RUNTIME_ID="${RUNTIME_RESOURCE##*/}"
```

Verify:

```bash
echo "${RUNTIME_RESOURCE}"
echo "${RUNTIME_ID}"
```

---

# 15. Retrieve the actual Agent Identity

Do not construct the Agent Identity from project or organization assumptions.

Retrieve the identity issued by Google:

```bash
export AGENT_PRINCIPAL="$(
  gcloud ai reasoning-engines describe "${RUNTIME_ID}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --format='value(spec.effectiveIdentity)'
)"
```

Verify:

```bash
echo "${AGENT_PRINCIPAL}"
```

It should begin with:

```text
principal://
```

The trust domain can differ between organization-backed and organization-less projects.

Always use the returned identity.

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

Create an IAP IAM policy file:

```bash
cat > build/mcp-iap-policy.json <<EOF
{
  "policy": {
    "bindings": [
      {
        "role": "roles/iap.egressor",
        "members": [
          "${AGENT_PRINCIPAL}"
        ]
      }
    ]
  }
}
EOF
```

Apply it specifically to the registered MCP server:

```bash
gcloud iap web set-iam-policy build/mcp-iap-policy.json \
  --project="${PROJECT_ID}" \
  --resource-type=agent-registry \
  --mcp-server="${MCP_SERVER_ID}" \
  --region="${REGION}"
```

This grants destination-level egress capability.

Fine-grained tool authorization is still controlled separately by UAP.

---

# 19. Grant IAP egress access to the Vertex endpoint

Create:

```bash
cat > build/vertex-iap-policy.json <<EOF
{
  "policy": {
    "bindings": [
      {
        "role": "roles/iap.egressor",
        "members": [
          "${AGENT_PRINCIPAL}"
        ]
      }
    ]
  }
}
EOF
```

Apply it:

```bash
gcloud iap web set-iam-policy build/vertex-iap-policy.json \
  --project="${PROJECT_ID}" \
  --resource-type=agent-registry \
  --endpoint="${VERTEX_ENDPOINT_ID}" \
  --region="${REGION}"
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

The repository includes the binding body for reference, but the gcloud command accepts the policy and target as command arguments.

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

Check the Runtime API directly:

```bash
curl -s \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${RUNTIME_ID}" \
| jq '.spec.deploymentSpec.agentGatewayConfig'
```

Expected:

```text
agentToAnywhereConfig.agentGateway
```

must reference:

```text
projects/${PROJECT_ID}/locations/${REGION}/agentGateways/${AGENT_GATEWAY_NAME}
```

If the result is `null`, stop and fix the Gateway binding before testing MCP policy.

---

# 26. Validate Agent Identity again

Confirm the active Runtime identity:

```bash
gcloud ai reasoning-engines describe "${RUNTIME_ID}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --format='value(spec.effectiveIdentity)'
```

It must exactly match:

```text
${AGENT_PRINCIPAL}
```

used when the UAP was rendered.

If the Runtime was deleted and recreated, its identity changes.

A UAP referencing the previous Runtime principal will no longer authorize the new Runtime.

---

# 27. Validate the read path

Use the deployed Agent Runtime with a request equivalent to:

```text
Read the customer profile for customer_id CUST-1001.
Use the MCP tool.
```

Expected model selection:

```text
read_customer_profile
```

Expected tool result:

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

Expected authorization result:

```text
ALLOW
```

Expected downstream behavior:

```text
Cloud Run receives and executes read_customer_profile
```

---

# 28. Validate the denied update path

Send a request equivalent to:

```text
Call update_customer_profile for customer_id CUST-1001
and set email to blocked@example.com.
Use the MCP tool.
```

Expected model selection:

```text
update_customer_profile
```

Expected runtime result:

```text
tool execution fails
```

Expected downstream behavior:

```text
Cloud Run does NOT receive the update tool execution
```

The model choosing a tool does not mean that the tool has authorization to execute.

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

Every newly created Agent Runtime receives a new immutable Runtime ID and therefore a new Agent Identity.

After recreating the Runtime:

```bash
export AGENT_PRINCIPAL="$(
  gcloud ai reasoning-engines describe "${RUNTIME_ID}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --format='value(spec.effectiveIdentity)'
)"
```

Then update:

```text
Cloud Run Invoker binding
Agent Registry viewer binding
IAP resource bindings
UAP principal
```

Do not reuse permissions belonging to the deleted Runtime identity.

---

# 39. Final acceptance checklist

Deployment is complete only when all of the following are true:

```text
[ ] MCP server deployed
[ ] MCP server requires authentication
[ ] MCP server registered in Agent Registry
[ ] read_customer_profile registered
[ ] update_customer_profile registered
[ ] Vertex endpoint registered
[ ] Agent Gateway created in AGENT_TO_ANYWHERE mode
[ ] IAP V2 Authorization Extension attached
[ ] Network Security REQUEST_AUTHZ policy attached
[ ] Runtime deployed with AGENT_IDENTITY
[ ] Runtime associated with Agent Gateway
[ ] Runtime effective identity captured dynamically
[ ] Cloud Run Invoker granted to Runtime identity
[ ] Agent Registry discovery granted
[ ] IAP egress granted to required registered destinations
[ ] UAP created
[ ] UAP bound to project
[ ] IAP enforcement enabled
[ ] read_customer_profile executes
[ ] update_customer_profile is blocked
[ ] denied update does not reach Cloud Run
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
