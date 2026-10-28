# Low-Level Design (LLD) — Agent Observability, Topology & SCC AI Protection

> **Lab URL:** [https://explore.qwiklabs.com/classrooms/21504/labs/115876](https://explore.qwiklabs.com/classrooms/21504/labs/115876)

---

## 1. Environment & Project Specifications

| Parameter | Variable | Value in Lab Execution | Purpose |
| :--- | :--- | :--- | :--- |
| **Project ID** | `PROJECT_ID` | `qwiklabs-gcp-01-f67f64703dca` | Target Google Cloud project hosting the agent fleet |
| **Project Number** | `PROJECT_NUMBER` | `361307671572` | Used in service agent emails and resource URIs |
| **Organization ID** | `ORGANIZATION_ID` | `616463121992` | Parent Google Cloud Organization |
| **Region / Location** | `LOCATION` / `REGION` | `us-central1` | Deployment region for Agent Runtime, Cloud Run, App Hub, and Agent Registry |
| **Model Location** | `GOOGLE_CLOUD_LOCATION` | `global` | Vertex AI Gemini model endpoint location |
| **Agent Model** | `MODEL` | `gemini-3.5-flash` (fleet) / `gemini-2.5-flash` (threat test) | Underlying LLM powering ADK agents |
| **Agents CLI Version** | `ACLI_VERSION` | `1.0.0` | Pinned `google-agents-cli` version |

---

## 2. Required Google Cloud APIs

| API Service Name | Plane | Technical Purpose |
| :--- | :--- | :--- |
| `observability.googleapis.com` | Observability | Google Cloud Observability control plane |
| `cloudtrace.googleapis.com` | Observability | Cloud Trace storage, querying, and Trace Explorer waterfall visualization |
| `telemetry.googleapis.com` | Observability | OpenTelemetry Protocol (OTLP) ingestion endpoint used by `get_gcp_exporters()` |
| `monitoring.googleapis.com` | Observability | Cloud Monitoring metrics ingestion |
| `logging.googleapis.com` | Observability | Structured Cloud Logging and GenAI completion logs |
| `apphub.googleapis.com` | Discovery & Inventory | Catalogs discovered workloads (`AGENT` functional type) and backs MCP inventory for Topology & SCC |
| `apptopology.googleapis.com` | Discovery & Topology | Aggregates App Hub / Agent Registry nodes and Cloud Trace spans into the Agent Topology graph |
| `agentregistry.googleapis.com` | Discovery & Inventory | Stores registered A2A agents (`salesforce-agent`) and MCP servers (`github-mcp`) |
| `cloudasset.googleapis.com` | Security & Governance | Backs IAM Policy Analyzer queries and SCC asset inventory |
| `containerthreatdetection.googleapis.com` | Security & Threat Detection | Required runtime sensor pipeline for Agent Platform Threat Detection |
| `securitycentermanagement.googleapis.com` | Security & Threat Detection | Manages enablement state of `agent-engine-threat-detection` modules |
| `securitycenter.googleapis.com` | Security & Threat Detection | Queries and displays active Security Command Center findings |

---

## 3. Code-Level OpenTelemetry Instrumentation Specification

### 3.1 Dependency Declaration (`pyproject.toml`)
Both `github-agent` and `salesforce-agent` declare `google-adk[gcp,otel-gcp]` and `opentelemetry-instrumentation-google-genai` in [`pyproject.toml`](../agents/salesforce-agent/pyproject.toml):

```toml
[project]
name = "salesforce-agent"
version = "0.1.0"
description = "Salesforce sub-agent: ADK agent over the Salesforce REST/SOSL API (app-only 2LO), served via A2A."

dependencies = [
    "google-adk[gcp,otel-gcp]>=2.0.0,<3.0.0",
    "a2a-sdk[http-server]~=0.3.22",
    "aiohttp>=3.13.4",
    "opentelemetry-instrumentation-google-genai>=0.1.0,<1.0.0",
    ...
]
```

### 3.2 Exporter Initialization (`app/app_utils/telemetry.py`)
At FastAPI / ADK startup, [`setup_telemetry()`](../agents/salesforce-agent/app/app_utils/telemetry.py) configures the Google Cloud OTLP exporters and registers the OpenTelemetry providers:

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

### 3.3 Emitted Trace Span Hierarchy
When a user queries an ADK agent, OpenTelemetry emits a nested span tree to `telemetry.googleapis.com`:

| Span Name | Hierarchy Level | Attributes & Meaning | Usage by Agent Topology |
| :--- | :--- | :--- | :--- |
| `invocation` / `agent_run` (root) | Top-level span | Root agent handling the user request (`github_agent`) | Identifies the source agent node |
| `agent_run` (nested) | Child of root `agent_run` | Specialist sub-agent invoked over A2A (`salesforce_agent`) | Creates directed agent-to-agent edge |
| `call_llm` | Child of `agent_run` | Gemini model invocation (`gemini-3.5-flash`), token counts, latency | Confirms active LLM execution per agent |
| `execute_tool` | Child of `agent_run` | Tool or MCP server execution (e.g., `github-mcp` or `search_salesforce`) | Creates directed agent-to-MCP/tool edge |

---

## 4. Multi-Runtime Discovery & Registration Schemas

### 4.1 Auto-Discovered Agent Runtime Workload (`github-agent`)
- **Reasoning Engine Resource URI:**
  ```text
  //aiplatform.googleapis.com/projects/361307671572/locations/us-central1/reasoningEngines/2580054886989168640
  ```
- **App Hub Discovered Workload Classification:**
  ```json
  {
    "workloadReference": {
      "uri": "//aiplatform.googleapis.com/projects/361307671572/locations/us-central1/reasoningEngines/2580054886989168640"
    },
    "workloadProperties": {
      "functionalType": {
        "type": "AGENT"
      }
    }
  }
  ```

### 4.2 Registered Cloud Run A2A Agent (`salesforce-agent`)
- **Cloud Run Service URL:** `https://salesforce-agent-361307671572.us-central1.run.app`
- **A2A Agent Card Endpoint:** `https://salesforce-agent-361307671572.us-central1.run.app/a2a/app/.well-known/agent-card.json`
- **Downloaded Agent Card ([`configs/salesforce_card.json`](../configs/salesforce_card.json)):**
  ```json
  {
    "name": "salesforce_agent",
    "version": "0.1.0",
    "protocolVersion": "0.3.0",
    "preferredTransport": "JSONRPC",
    "url": "https://salesforce-agent-361307671572.us-central1.run.app/a2a/app",
    "description": "Specialized assistant for Salesforce: searches the organization's document library (Salesforce Files) via the Salesforce REST/SOSL API.",
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "supportsAuthenticatedExtendedCard": false,
    "capabilities": {
      "streaming": true,
      "extensions": [
        {
          "description": "Ability to use the new agent executor implementation",
          "uri": "https://google.github.io/adk-docs/a2a/a2a-extension/"
        }
      ]
    },
    "skills": [
      {
        "id": "salesforce_agent",
        "name": "model",
        "tags": ["llm"],
        "description": "Specialized assistant for Salesforce..."
      },
      {
        "id": "salesforce_agent-search_salesforce",
        "name": "search_salesforce",
        "tags": ["llm", "tools"],
        "description": "Searches the company's Salesforce document library (Files)..."
      },
      {
        "id": "salesforce_agent-preload_memory",
        "name": "preload_memory",
        "tags": ["llm", "tools"],
        "description": "preload_memory"
      }
    ]
  }
  ```
- **Agent Registry Registration Parameters:**
  - Service ID: `salesforce-agent`
  - Location: `us-central1`
  - Spec Type: `--agent-spec-type=a2a-agent-card`
  - Spec Content: `--agent-spec-content="$(cat salesforce_card.json)"`

### 4.3 Registered External MCP Server (`github-mcp`)
- **Agent Registry Registration Parameters:**
  - Service ID: `github-mcp`
  - Location: `us-central1`
  - Spec Type: `--mcp-server-spec-type=no-spec`
  - Interfaces: `--interfaces=url=https://api.githubcopilot.com/mcp/,protocolBinding=JSONRPC`
- **Resulting Agent Registry MCP Server Resource:**
  ```yaml
  attributes:
    agentregistry.googleapis.com/system/RuntimeReference:
      uri: //agentregistry.googleapis.com/projects/361307671572/locations/us-central1/services/github-mcp
  interfaces:
  - protocolBinding: JSONRPC
    url: https://api.githubcopilot.com/mcp/
  mcpServerId: urn:mcp:projects-361307671572:projects:361307671572:locations:us-central1:agentregistry:services:github-mcp
  name: projects/qwiklabs-gcp-01-f67f64703dca/locations/us-central1/mcpServers/agentregistry-00000000-0000-0000-26b0-04a0598bfd6c
  ```

---

## 5. IAM Principal & Least-Privilege Role Matrix

| Principal | Resource Scope | Role | Status in Final State | Technical Justification |
| :--- | :--- | :--- | :--- | :--- |
| `service-361307671572@gcp-sa-aiplatform-re.iam.gserviceaccount.com` | Project | `roles/aiplatform.user`<br/>`roles/logging.logWriter`<br/>`roles/cloudtrace.agent` | **GRANTED** | Allows Vertex AI Agent Runtime (`github-agent`) to invoke Gemini models and write logs/traces. |
| `service-361307671572@gcp-sa-discoveryengine.iam.gserviceaccount.com` | Cloud Run service `salesforce-agent` | `roles/run.invoker` | **GRANTED** | Allows Discovery Engine / Agent Registry to invoke `salesforce-agent` and read its A2A agent card. |
| `361307671572-compute@developer.gserviceaccount.com` (`SF_SA`) | Project | `roles/aiplatform.user` | **GRANTED** | Allows `salesforce-agent` to invoke Vertex AI Gemini models. |
| `361307671572-compute@developer.gserviceaccount.com` (`SF_SA`) | Project | `roles/telemetry.tracesWriter` | **GRANTED (Task 2)** | Required for OpenTelemetry OTLP exporter to write spans to `telemetry.googleapis.com`. |
| `361307671572-compute@developer.gserviceaccount.com` (`SF_SA`) | Project | `roles/logging.logWriter` | **GRANTED** | Allows `salesforce-agent` to write structured container and GenAI logs. |
| `361307671572-compute@developer.gserviceaccount.com` (`SF_SA`) | Project | `roles/cloudtrace.agent` | **GRANTED** | Supports legacy Cloud Trace span writing. |
| `361307671572-compute@developer.gserviceaccount.com` (`SF_SA`) | Project | `roles/editor` | **REMOVED (Task 9)** | Over-broad primitive role simulated in Task 7, analyzed in Task 8 via Policy Analyzer, and revoked in Task 9. |

---

## 6. Agent Platform Threat Detection Specification (Task 10)

### 6.1 Service & Detector Configuration
- **Security Center Service:** `projects/361307671572/locations/global/securityCenterServices/agent-engine-threat-detection`
- **Enablement State:** `ENABLED`
- **Target Detector Module:** `AGENT_ENGINE_ADDED_MALICIOUS_BINARY_EXECUTED` (`effectiveEnablementState: ENABLED`)

### 6.2 Throwaway Test Agent Architecture ([`threat_test/main.py`](../threat_test/main.py))
- **Display Name:** `scc_threat_test_agent`
- **Identity Type:** `vertexai.types.IdentityType.AGENT_IDENTITY`
- **Deployed ReasoningEngine Resource:** `projects/361307671572/locations/us-central1/reasoningEngines/6469757590153723904`
- **Simulated Attack Sequence (`threat_detection_test()`):**
  1. `sleep 60` — Ensures the runtime threat sensor attaches to the newly spawned Reasoning Engine container.
  2. Writes the standard 68-byte **EICAR** anti-malware test string (`X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*`) to `/tmp/test_mal_file` (a path not part of the immutable container image manifest).
  3. Executes `chmod 700 /tmp/test_mal_file` and `sh -c /tmp/test_mal_file`.
  4. `sleep 10` — Allows the kernel/runtime event stream to flush before teardown.
  5. `finally:` calls `client.agent_engines.delete(name=remote_agent.api_resource.name, force=True)` to automatically clean up the throwaway agent.
- **Generated SCC Finding:**
  - **Category:** `Execution: Added Malicious Binary Executed`
  - **Severity:** `CRITICAL`
  - **Resource Name:** `//aiplatform.googleapis.com/projects/361307671572/locations/us-central1/reasoningEngines/6469757590153723904`
