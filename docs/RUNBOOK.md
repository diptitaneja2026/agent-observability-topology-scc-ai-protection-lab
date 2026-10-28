# Step-by-Step Operational Runbook — Agent Observability, Topology & SCC AI Protection

> **Lab URL:** [https://explore.qwiklabs.com/classrooms/21504/labs/115876](https://explore.qwiklabs.com/classrooms/21504/labs/115876)  
> **Region:** `us-central1`

---

## Task 1. Prepare Your Environment

### Step 1.1: Set Project, Location, and Organization Variables
Open Cloud Shell and configure the environment variables used throughout the lab:

```bash
export PROJECT_ID=qwiklabs-gcp-01-f67f64703dca
export LOCATION=us-central1
gcloud config set project ${PROJECT_ID}
export PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')
export ORGANIZATION_ID=$(gcloud projects get-ancestors ${PROJECT_ID} --format=json | jq -r '.[] | select(.type=="organization") | .id')
echo "Project: ${PROJECT_ID} (${PROJECT_NUMBER}), Org: ${ORGANIZATION_ID}, Location: ${LOCATION}"
```

**Verified Output:**
```text
Updated property [core/project].
Project: qwiklabs-gcp-01-f67f64703dca (361307671572), Org: 616463121992, Location: us-central1
```

### Step 1.2: Copy Pre-Staged Lab Scripts and Run Prerequisites
Copy the prerequisite scripts from the project Cloud Storage bucket and execute `lab2_prereqs.sh` (providing the Project ID, GitHub PAT, Salesforce My Domain, Salesforce Consumer Key, and Salesforce Consumer Secret when prompted):

```bash
gcloud storage cp -r gs://${PROJECT_ID}-bucket/apex_labs .
bash apex_labs/lab2_prereqs.sh
```

**What `lab2_prereqs.sh` provisions:**
1. Enables core build/runtime APIs (`aiplatform.googleapis.com`, `run.googleapis.com`, `cloudbuild.googleapis.com`, `artifactregistry.googleapis.com`, `iam.googleapis.com`, `iamcredentials.googleapis.com`, `logging.googleapis.com`, `cloudtrace.googleapis.com`).
2. Creates the Reasoning Engine service agent (`service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com`) and grants `roles/aiplatform.user`, `roles/logging.logWriter`, and `roles/cloudtrace.agent`.
3. Installs `google-agents-cli==1.0.0` via `uv tool install`.
4. Deploys `github-agent` to Vertex AI Agent Runtime (`us-central1`).
5. Deploys `salesforce-agent` to Cloud Run (`us-central1`, `--max-instances=4`, private).
6. Ensures baseline model and logging roles (`roles/aiplatform.user`, `roles/logging.logWriter`, `roles/cloudtrace.agent`) on the Cloud Run service account.

### Step 1.3: Stage Agent Code, Disable Gemini Code Assist, and Verify `agents-cli`

```bash
gcloud storage cp -r gs://${PROJECT_ID}-bucket/agents .
mkdir -p ~/.vscode
gcloud storage cp -r gs://${PROJECT_ID}-bucket/settings.json ~/.vscode/

export PATH="${HOME}/.local/bin:${PATH}"
uvx google-agents-cli setup
uv tool upgrade google-agents-cli
agents-cli info
```

**Verified Output:**
```text
CLI version:        1.0.0
CLI install path:   /home/student_03_d6d9266204c9/.local/share/uv/tools/google-agents-cli/lib/python3.12/site-packages/google/agents/cli
OS info:            Linux-6.18.55+-x86_64-with-glibc2.39
Installed skills:   none
```

### Step 1.4: Confirm the Fleet is Present
Check that `salesforce-agent` is running on Cloud Run:

```bash
gcloud run services list --project=${PROJECT_ID} --region=${LOCATION} --format="table(metadata.name)"
```

**Verified Output:**
```text
NAME
salesforce-agent
```

Check that `github-agent` is running on Vertex AI Agent Runtime:

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://${LOCATION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION}/reasoningEngines" \
  | jq -r '(.reasoningEngines // [])[] | "\(.displayName)\t\(.name)"'
```

**Verified Output:**
```text
github-agent	projects/361307671572/locations/us-central1/reasoningEngines/2580054886989168640
```

### Step 1.5: Enable Observability and Discovery APIs
Enable the APIs required by Cloud Trace, OpenTelemetry OTLP ingestion, App Hub, Agent Topology, Agent Registry, and Policy Analyzer:

```bash
gcloud services enable \
  observability.googleapis.com \
  cloudtrace.googleapis.com \
  telemetry.googleapis.com \
  apphub.googleapis.com \
  apptopology.googleapis.com \
  agentregistry.googleapis.com \
  cloudasset.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com \
  --project=${PROJECT_ID}
```

> **Checkpoint 1:** Click **Check my progress** for *"Enable the observability and discovery APIs"*.

---

## Task 2. Export Traces to Cloud Trace

### Step 2.1: Inspect the OpenTelemetry Instrumentation in the Agent Code
Verify that `google-adk[gcp,otel-gcp]` and `opentelemetry-instrumentation-google-genai` are declared in `~/agents/salesforce-agent/pyproject.toml`:

```bash
grep -E "google-adk|opentelemetry" ~/agents/salesforce-agent/pyproject.toml
```

**Verified Output:**
```toml
    "google-adk[gcp,otel-gcp]>=2.0.0,<3.0.0",
    "opentelemetry-instrumentation-google-genai>=0.1.0,<1.0.0",
```

Verify `setup_telemetry()` and `get_gcp_exporters(enable_cloud_tracing=True)` in `~/agents/salesforce-agent/app/app_utils/telemetry.py`:

```bash
sed -n '58,74p' ~/agents/salesforce-agent/app/app_utils/telemetry.py
```

**Verified Output:**
```python
    # Set up OpenTelemetry exporters for Cloud Trace and Cloud Logging
    credentials, project_id = google.auth.default()
    otel_hooks = get_gcp_exporters(
        enable_cloud_tracing=True,
        enable_cloud_metrics=False,
        enable_cloud_logging=True,
        google_auth=(credentials, project_id),
    )
    otel_resource = get_gcp_resource(project_id)
    maybe_set_otel_providers(
        otel_hooks_to_setup=[otel_hooks],
        otel_resource=otel_resource,
    )

    # Set up GenAI SDK instrumentation
    _setup_instrumentation_lib_if_installed()
```

### Step 2.2: Grant the Cloud Telemetry Traces Writer Role (`roles/telemetry.tracesWriter`)
While Agent Runtime agents (`github-agent`) export traces via managed built-in telemetry, Cloud Run agents (`salesforce-agent`) export traces as their runtime service account (`${PROJECT_NUMBER}-compute@developer.gserviceaccount.com`) to `telemetry.googleapis.com` and require `roles/telemetry.tracesWriter`:

```bash
export SF_SA=$(gcloud run services describe salesforce-agent --region=${LOCATION} \
  --format='value(spec.template.spec.serviceAccountName)')
if [ -z "${SF_SA}" ]; then
  export SF_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SF_SA}" \
  --role="roles/telemetry.tracesWriter" \
  --condition=None
```

### Step 2.3: Generate Traffic So the System Emits Traces
Retrieve the `github_agent` Reasoning Engine URL (without `:query`) and run a query using `agents-cli run` with `--mode adk` and `--app-name app`:

```bash
export GH_ENGINE_NAME=$(curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://${LOCATION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION}/reasoningEngines" \
  | jq -r '(.reasoningEngines // [])[] | select(.displayName=="github-agent") | .name' | head -n 1)

export GH_QUERY_URL="https://${LOCATION}-aiplatform.googleapis.com/v1/${GH_ENGINE_NAME}"
echo "Querying: ${GH_QUERY_URL}"

agents-cli run \
  --url "${GH_QUERY_URL}" \
  --mode adk \
  --app-name app \
  "Find the google/adk-python repository and list 3 open issues"
```

**Verified Output:**
```text
Querying remote agent: https://us-central1-aiplatform.googleapis.com/v1/projects/361307671572/locations/us-central1/reasoningEngines/2580054886989168640 (mode: adk)
[user]: Find the google/adk-python repository and list 3 open issues
[github_agent]: I found the **`google/adk-python`** repository and listed 3 open issues:
...
Session: 4722571113253568512
```

### Step 2.4: Confirm the Traces Landed in Trace Explorer
1. Open the Google Cloud console and navigate to **Monitoring > Trace explorer**.
2. Set the time range to **Last 1 hour** and filter by span name `call_llm` or `agent_run`.
3. Click a trace to inspect the waterfall hierarchy:
   - Top-level `invocation` / `agent_run` span: root agent handling the request.
   - `call_llm` spans: Gemini model invocations.
   - `execute_tool` spans: `github_agent` invoking the GitHub MCP server.

> **Checkpoint 2:** Click **Check my progress** for *"Grant the trace-writer role to an agent's service account"*.

---

## Task 3. Confirm the Agent Runtime Agents Are Already Discovered

### Step 3.1: List Agents in Agent Registry
Confirm `github-agent` is automatically listed in Agent Registry:

```bash
gcloud alpha agent-registry agents list \
  --location=${LOCATION} \
  --project=${PROJECT_ID} \
  --format="table(displayName)"
```

**Verified Output:**
```text
DISPLAY_NAME
Workspace Agent
github-agent
```

### Step 3.2: Confirm App Hub Functional Type Classification (`AGENT`)
Query the App Hub `discoveredWorkloads` endpoint to confirm the Reasoning Engine is classified with `functionalType.type = AGENT`:

```bash
export TOKEN=$(gcloud auth print-access-token)
curl -s -H "Authorization: Bearer ${TOKEN}" \
  -H "x-goog-user-project: ${PROJECT_ID}" \
  "https://apphub.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION}/discoveredWorkloads" \
  | jq -r '.discoveredWorkloads[] | "\(.workloadProperties.functionalType.type // "-")\t\(.workloadReference.uri)"'
```

**Verified Output:**
```text
AGENT	//aiplatform.googleapis.com/projects/361307671572/locations/us-central1/reasoningEngines/2580054886989168640
```

---

## Task 4. Register the Cloud Run Agent (`salesforce-agent`)

### Step 4.1: Provision Discovery Engine Service Agent & Grant Cloud Run Invoker Access
Create the Discovery Engine service identity and grant `roles/run.invoker` on the `salesforce-agent` Cloud Run service so Agent Registry can read its A2A card:

```bash
gcloud beta services identity create \
  --service=discoveryengine.googleapis.com \
  --project=${PROJECT_ID}

gcloud run services add-iam-policy-binding salesforce-agent \
  --region=${LOCATION} \
  --project=${PROJECT_ID} \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-discoveryengine.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

**Verified Output:**
```text
Service identity created: service-361307671572@gcp-sa-discoveryengine.iam.gserviceaccount.com
Updated IAM policy for service [salesforce-agent].
bindings:
- members:
  - serviceAccount:service-361307671572@gcp-sa-discoveryengine.iam.gserviceaccount.com
  role: roles/run.invoker
```

> **Checkpoint 3:** Click **Check my progress** for *"Grant the Discovery Engine service agent invoker access"*.

### Step 4.2: Fetch the `salesforce-agent` A2A Agent Card and Register in Agent Registry
Download the A2A agent card from `${SF_URL}/a2a/app/.well-known/agent-card.json` and register `salesforce-agent` in Agent Registry:

```bash
export SF_URL=$(gcloud run services describe salesforce-agent --region=${LOCATION} --format='value(status.url)')
export TOKEN=$(gcloud auth print-identity-token)
curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${SF_URL}/a2a/app/.well-known/agent-card.json" -o salesforce_card.json

gcloud alpha agent-registry services create salesforce-agent \
  --location=${LOCATION} \
  --project=${PROJECT_ID} \
  --agent-spec-type=a2a-agent-card \
  --agent-spec-content="$(cat salesforce_card.json)"
```

**Verified Output:**
```text
Create request issued for: [salesforce-agent]
Waiting for operation [projects/qwiklabs-gcp-01-f67f64703dca/locations/us-central1/operations/operation-...] to complete...done.
Created service [salesforce-agent].
```

Verify both `github-agent` and `salesforce_agent` now appear in Agent Registry:

```bash
gcloud alpha agent-registry agents list \
  --location=${LOCATION} \
  --project=${PROJECT_ID} \
  --format="table(displayName)"
```

**Verified Output:**
```text
DISPLAY_NAME
Workspace Agent
salesforce_agent
github-agent
```

> **Checkpoint 4:** Click **Check my progress** for *"Register the Cloud Run agent in Agent Registry"*.

---

## Task 5. Register the GitHub MCP Server

### Step 5.1: Register `github-mcp` in Agent Registry
Register the external GitHub Copilot MCP server (`https://api.githubcopilot.com/mcp/`) with `--mcp-server-spec-type=no-spec` and `protocolBinding=JSONRPC`:

```bash
gcloud alpha agent-registry services create github-mcp \
  --location=${LOCATION} \
  --project=${PROJECT_ID} \
  --mcp-server-spec-type=no-spec \
  --interfaces=url=https://api.githubcopilot.com/mcp/,protocolBinding=JSONRPC
```

### Step 5.2: Confirm the MCP Server Registration

```bash
gcloud alpha agent-registry mcp-servers list \
  --location=${LOCATION} \
  --project=${PROJECT_ID}
```

**Verified Output:**
```yaml
---
attributes:
  agentregistry.googleapis.com/system/RuntimeReference:
    uri: //agentregistry.googleapis.com/projects/361307671572/locations/us-central1/services/github-mcp
createTime: '2026-10-28T11:22:52.919716Z'
interfaces:
- protocolBinding: JSONRPC
  url: https://api.githubcopilot.com/mcp/
mcpServerId: urn:mcp:projects-361307671572:projects:361307671572:locations:us-central1:agentregistry:services:github-mcp
name: projects/qwiklabs-gcp-01-f67f64703dca/locations/us-central1/mcpServers/agentregistry-00000000-0000-0000-26b0-04a0598bfd6c
updateTime: '2026-10-28T11:22:52.919716Z'
```

> **Checkpoint 5:** Click **Check my progress** for *"Register the GitHub MCP server in Agent Registry"*.

---

## Task 6. View the Agent Topology Graph

1. In the Google Cloud console, navigate to **Agent Platform > Agent Registry**.
2. Select your lab project (`qwiklabs-gcp-01-f67f64703dca`).
3. Under the **Agents** tab, click `github-agent` (or `salesforce_agent`).
4. Select the **Topology** tab to view the unified multi-runtime graph showing `github-agent` (Agent Runtime), `salesforce_agent` (Cloud Run), and the edge from `github-agent` to the `github-mcp` server.

---

## Task 7. See the Fleet in SCC AI Protection & Simulate Over-Privilege

1. Navigate to **Agent Platform > Agents > Security** (`https://console.cloud.google.com/agent-platform/security`) to view the AI asset inventory and risk widgets.
2. Simulate over-granting the `salesforce-agent` service account with `roles/editor`:

```bash
export SF_SA=$(gcloud run services describe salesforce-agent --region=${LOCATION} \
  --format='value(spec.template.spec.serviceAccountName)')
if [ -z "${SF_SA}" ]; then
  export SF_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SF_SA}" \
  --role="roles/editor" --condition=None
```

---

## Task 8. Identify the Security Finding and Its Scope Using Policy Analyzer

1. In the **Agent Platform > Security** tab, review the **Agents with excessive permissions** and **AI risks by severity** widgets to locate `salesforce_agent`.
2. Open **IAM & Admin > Policy Analyzer** in the Google Cloud console:
   - Click **Create custom query**.
   - Set **Scope** to project `qwiklabs-gcp-01-f67f64703dca`.
   - Set **Parameter 1** to **Principal** and enter `serviceAccount:361307671572-compute@developer.gserviceaccount.com` (output of `echo ${SF_SA}`).
   - Under **Advanced options**, check **List resources within resource(s) matching your query**, then click **Analyze > Run query**.
   - Confirm that `roles/editor` grants broad read/write access across nearly every resource in the project.

---

## Task 9. Fix It and Verify Least Privilege

### Step 9.1: Inspect Current Roles on the `salesforce-agent` Service Account

```bash
gcloud projects get-iam-policy ${PROJECT_ID} --flatten="bindings[].members" \
  --filter="bindings.members:${SF_SA}" \
  --format="value(bindings.role)"
```

**Verified Output (Before Remediation):**
```text
roles/aiplatform.user
roles/cloudtrace.agent
roles/editor
roles/logging.logWriter
roles/telemetry.tracesWriter
```

### Step 9.2: Remove `roles/editor` and Verify Least Privilege
Remove the over-broad `roles/editor` role while keeping the four required operational roles:

```bash
gcloud projects remove-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SF_SA}" \
  --role="roles/editor"
```

Confirm `roles/editor` is removed from the live project IAM policy:

```bash
gcloud projects get-iam-policy ${PROJECT_ID} \
  --flatten="bindings[].members" \
  --filter="bindings.members:${SF_SA} AND bindings.role:roles/editor" \
  --format="value(bindings.role)"
```

*(Returns empty output, confirming `roles/editor` is gone.)*

Confirm the remaining narrow roles:

```bash
gcloud projects get-iam-policy ${PROJECT_ID} --flatten="bindings[].members" \
  --filter="bindings.members:${SF_SA}" \
  --format="value(bindings.role)"
```

**Verified Output (After Remediation):**
```text
roles/aiplatform.user
roles/cloudtrace.agent
roles/logging.logWriter
roles/telemetry.tracesWriter
```

---

## Task 10. (Optional Exercise) Trigger and View an Agent's Runtime Attacks

### Step 10.1: Enable Container Threat Detection & Agent Platform Threat Detection

```bash
gcloud services enable \
  containerthreatdetection.googleapis.com \
  securitycentermanagement.googleapis.com \
  securitycenter.googleapis.com \
  --project=${PROJECT_ID}

gcloud scc manage services update agent-engine-threat-detection \
  --project=${PROJECT_ID} \
  --enablement-state=ENABLED \
  --quiet
```

### Step 10.2: Create and Run the Throwaway EICAR Threat Detection Test Agent
The test suite in [`threat_test/`](../threat_test/) deploys a temporary Reasoning Engine (`scc_threat_test_agent`), executes the `Execution: Added Malicious Binary Executed` test using the harmless EICAR signature (`/tmp/test_mal_file`), and deletes the agent automatically:

```bash
cd ~/threat_test
uv venv env
source env/bin/activate
uv pip install -r requirements.txt
python3 main.py
```

**Verified Execution Output:**
```text
Deployed agent:  projects/361307671572/locations/us-central1/reasoningEngines/6469757590153723904
...
{'content': {'parts': [{'function_response': {'id': 'adk-ff5412f1-ceda-4940-ada6-fc065d0f0d9c', 'name': 'threat_detection_test', 'response': {'result': 'Called sleep 60\nCalled touch /tmp/test_mal_file\nCalled chmod 700 /tmp/test_mal_file\nCalled sh -c /tmp/test_mal_file\nError: /tmp/test_mal_file: 1: Syntax error: word unexpected (expecting ")")\nCalled sleep 10\n'}}}], 'role': 'user'}...}
```

### Step 10.3: Verify the Resulting `CRITICAL` Finding in Security Command Center

```bash
gcloud scc findings list projects/${PROJECT_NUMBER} \
  --filter='category="Execution: Added Malicious Binary Executed"' \
  --format="table(finding.category,finding.resourceName,finding.eventTime,finding.severity)" \
  --limit=5
```

**Verified Output:**
```text
CATEGORY                                     RESOURCE_NAME                                                                                      EVENT_TIME                SEVERITY
Execution: Added Malicious Binary Executed   //aiplatform.googleapis.com/projects/361307671572/locations/us-central1/reasoningEngines/6469757590153723904  2026-10-28T11:46:09.378Z  CRITICAL
```

---

## Troubleshooting Guide

| Symptom | Root Cause | Resolution |
| :--- | :--- | :--- |
| **"Grant the Discovery Engine service agent invoker access"** check fails | Either `salesforce-agent` Cloud Run service is still building or `roles/run.invoker` was granted at project level instead of on the Cloud Run service resource. | Wait for `salesforce-agent` validation/deployment and run `gcloud run services add-iam-policy-binding salesforce-agent --region=${LOCATION} --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-discoveryengine.iam.gserviceaccount.com" --role="roles/run.invoker"`. |
| `gcloud alpha agent-registry services create` fails with `unrecognized arguments: --agent-spec-content-from-file` | The `gcloud alpha agent-registry services create` command accepts inline JSON via `--agent-spec-content`. | Pass `--agent-spec-content="$(cat salesforce_card.json)"` along with `--agent-spec-type=a2a-agent-card`. |
| No traces appear in Cloud Trace Explorer | Missing `roles/telemetry.tracesWriter` on the agent's runtime service account or `telemetry.googleapis.com` is not enabled. | Enable `telemetry.googleapis.com` and grant `roles/telemetry.tracesWriter` to `${PROJECT_NUMBER}-compute@developer.gserviceaccount.com`. |
| Policy Analyzer still shows `roles/editor` right after removal | Cloud Asset Inventory lags live IAM policy updates by up to 60 seconds. | Verify immediately with `gcloud projects get-iam-policy ${PROJECT_ID}`, then wait 60 seconds and re-run the Policy Analyzer query. |
