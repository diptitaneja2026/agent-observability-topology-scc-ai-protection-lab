# Step-by-Step Workflows — Agent Observability, Topology & SCC AI Protection

> **Lab URL:** [https://explore.qwiklabs.com/classrooms/21504/labs/115876](https://explore.qwiklabs.com/classrooms/21504/labs/115876)

---

## Master Lab Execution Flow (Tasks 1–10)

```mermaid
flowchart LR
    T1["Task 1<br/>Prepare Environment &<br/>Enable Observability/Discovery APIs"]
    T2["Task 2<br/>Grant tracesWriter Role &<br/>Emit OpenTelemetry Spans"]
    T3["Task 3<br/>Confirm Auto-Discovery of<br/>Agent Runtime (github-agent)"]
    T4["Task 4<br/>Grant run.invoker & Register<br/>Cloud Run Agent (salesforce-agent)"]
    T5["Task 5<br/>Register External MCP Server<br/>(github-mcp) in Agent Registry"]
    T6["Task 6<br/>Inspect Unified<br/>Agent Topology Graph"]
    T7["Task 7<br/>Review SCC AI Protection &<br/>Simulate Over-Privilege (roles/editor)"]
    T8["Task 8<br/>Prove Blast Radius with<br/>IAM Policy Analyzer"]
    T9["Task 9<br/>Remediate Service Account &<br/>Verify Least Privilege"]
    T10["Task 10 (Optional)<br/>Trigger & View Agent Platform<br/>Threat Detection (EICAR)"]

    T1 --> T2 --> T3 --> T4 --> T5 --> T6 --> T7 --> T8 --> T9 --> T10
```

---

## Task 1 Workflow: Environment Preparation, Baseline Fleet Deployment & API Enablement

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator (Cloud Shell)
    participant GCS as Project GCS Bucket<br/>(gs://PROJECT_ID-bucket)
    participant Prereq as lab2_prereqs.sh
    participant AR_Runtime as Vertex AI Agent Runtime<br/>(us-central1)
    participant CloudRun as Cloud Run<br/>(us-central1)
    participant ServiceUsage as Service Usage API

    Operator->>Operator: Export PROJECT_ID, LOCATION, PROJECT_NUMBER, ORGANIZATION_ID
    Operator->>GCS: gcloud storage cp -r gs://PROJECT_ID-bucket/apex_labs .
    Operator->>Prereq: bash apex_labs/lab2_prereqs.sh (Provide GitHub PAT & Salesforce creds)
    Prereq->>ServiceUsage: Enable aiplatform, run, cloudbuild, artifactregistry, iam, logging, cloudtrace
    Prereq->>AR_Runtime: agents-cli deploy github-agent (--region us-central1)
    AR_Runtime-->>Prereq: Deployed ReasoningEngine (2580054886989168640)
    Prereq->>CloudRun: agents-cli deploy salesforce-agent (--max-instances 4, private)
    CloudRun-->>Prereq: Deployed Cloud Run service (salesforce-agent)
    Operator->>GCS: Copy agents/ source code & ~/.vscode/settings.json
    Operator->>Operator: Install & verify google-agents-cli (v1.0.0)
    Operator->>CloudRun: Verify salesforce-agent via gcloud run services list
    Operator->>AR_Runtime: Verify github_agent via reasoningEngines REST API
    Operator->>ServiceUsage: Enable observability, cloudtrace, telemetry, apphub, apptopology, agentregistry, cloudasset, monitoring, logging
```

---

## Task 2 Workflow: OpenTelemetry Trace Export & Traffic Generation

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator (Cloud Shell)
    participant IAM as Cloud IAM
    participant CLI as agents-cli
    participant GH_Agent as github-agent<br/>(Vertex AI Agent Runtime)
    participant Gemini as Vertex AI Gemini<br/>(gemini-3.5-flash)
    participant GH_MCP as GitHub Copilot MCP<br/>(api.githubcopilot.com/mcp)
    participant OTLP as Cloud Telemetry OTLP API<br/>(telemetry.googleapis.com)
    participant Trace as Cloud Trace Explorer

    Operator->>Operator: Inspect pyproject.toml (google-adk[otel-gcp]) & telemetry.py (get_gcp_exporters)
    Operator->>IAM: Grant roles/telemetry.tracesWriter to Compute Engine Default SA (salesforce-agent SA)
    IAM-->>Operator: Binding updated
    Operator->>CLI: agents-cli run --url <REASONING_ENGINE_URL> --mode adk --app-name app "<query>"
    CLI->>GH_Agent: Start root span (invocation / agent_run)
    GH_Agent->>Gemini: call_llm (Select MCP tool)
    GH_Agent->>GH_MCP: execute_tool (JSON-RPC MCP call)
    GH_MCP-->>GH_Agent: Repository & open issues payload
    GH_Agent->>Gemini: call_llm (Synthesize final answer)
    GH_Agent-->>CLI: Stream response to user
    GH_Agent->>OTLP: Export OpenTelemetry span waterfall (invocation -> agent_run -> call_llm / execute_tool)
    OTLP->>Trace: Ingest spans into Cloud Trace
    Operator->>Trace: Filter by span name call_llm / agent_run and inspect waterfall
```

---

## Task 3 Workflow: Confirming Auto-Discovery of Agent Runtime Workloads

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator (Cloud Shell)
    participant AR_Runtime as Vertex AI Agent Runtime
    participant AppHub as App Hub API<br/>(discoveredWorkloads)
    participant Registry as Agent Registry API<br/>(gcloud alpha agent-registry)

    AR_Runtime-.->AppHub: Automatically catalogs ReasoningEngine with functionalType=AGENT
    AR_Runtime-.->Registry: Automatically surfaces ReasoningEngine as github-agent
    Operator->>Registry: gcloud alpha agent-registry agents list --location=us-central1
    Registry-->>Operator: Returns github-agent (and Workspace Agent)
    Operator->>AppHub: GET /v1/projects/{PROJECT_ID}/locations/us-central1/discoveredWorkloads
    AppHub-->>Operator: Returns AGENT //aiplatform.googleapis.com/.../reasoningEngines/2580054886989168640
```

---

## Task 4 Workflow: Registering the Cloud Run A2A Agent (`salesforce-agent`)

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator (Cloud Shell)
    participant ServiceUsage as Service Identity API
    participant CloudRun as Cloud Run Service<br/>(salesforce-agent)
    participant Registry as Agent Registry API<br/>(us-central1)
    participant DE_SA as Discovery Engine SA<br/>(service-PROJECT_NUMBER@gcp-sa-discoveryengine...)

    Operator->>ServiceUsage: gcloud beta services identity create --service=discoveryengine.googleapis.com
    ServiceUsage-->>Operator: Created service-PROJECT_NUMBER@gcp-sa-discoveryengine.iam.gserviceaccount.com
    Operator->>CloudRun: Grant roles/run.invoker to Discovery Engine SA on salesforce-agent
    CloudRun-->>Operator: Updated Cloud Run service IAM policy
    Operator->>CloudRun: GET ${SF_URL}/a2a/app/.well-known/agent-card.json (Bearer ID token)
    CloudRun-->>Operator: Save salesforce_card.json (name: salesforce_agent, protocol: 0.3.0, skills: [...])
    Operator->>Registry: gcloud alpha agent-registry services create salesforce-agent<br/>--agent-spec-type=a2a-agent-card --agent-spec-content="$(cat salesforce_card.json)"
    Registry->>DE_SA: Validate / invoke A2A card endpoint
    Registry-->>Operator: Created service [salesforce-agent] (Surfaced as salesforce_agent in Agent Registry)
```

---

## Task 5 Workflow: Registering the External GitHub MCP Server (`github-mcp`)

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator (Cloud Shell)
    participant Registry as Agent Registry API<br/>(services & mcp-servers)
    participant AppHub as App Hub Inventory

    Operator->>Registry: gcloud alpha agent-registry services create github-mcp<br/>--mcp-server-spec-type=no-spec<br/>--interfaces=url=https://api.githubcopilot.com/mcp/,protocolBinding=JSONRPC
    Registry->>AppHub: Sync MCP endpoint into App Hub inventory
    Registry-->>Operator: Created service [github-mcp]
    Operator->>Registry: gcloud alpha agent-registry mcp-servers list --location=us-central1
    Registry-->>Operator: Returns mcpServerId urn:mcp:...:services:github-mcp
```

---

## Task 6 Workflow: Viewing the Unified Multi-Runtime Agent Topology Graph

```mermaid
flowchart TB
    subgraph Inputs["Discovery & Telemetry Data Sources"]
        AR_Nodes["Agent Registry & App Hub Nodes:<br/>1. github-agent (Agent Runtime)<br/>2. salesforce_agent (Cloud Run)<br/>3. github-mcp (External MCP Server)"]
        Trace_Spans["Cloud Trace Spans:<br/>agent_run / call_llm / execute_tool"]
    end

    Batch["Agent Topology Batch Aggregator<br/>(apptopology.googleapis.com)"]

    subgraph TopologyUI["Google Cloud Console: Agent Registry > Agents > Topology Tab"]
        Node_GH["Node: github-agent<br/>(Runtime: Agent Runtime)"]
        Node_SF["Node: salesforce_agent<br/>(Runtime: Cloud Run)"]
        Node_MCP["Node: github-mcp<br/>(Type: MCP Server)"]
        Node_LLM["Node: gemini-3.5-flash<br/>(Vertex AI Model)"]

        Node_GH -->|"execute_tool (JSON-RPC)"| Node_MCP
        Node_GH -->|"call_llm"| Node_LLM
        Node_GH -.->|"A2A agent_run"| Node_SF
    end

    AR_Nodes --> Batch
    Trace_Spans --> Batch
    Batch --> TopologyUI
```

---

## Tasks 7, 8 & 9 Workflow: SCC AI Protection Risk Simulation, Policy Analyzer Scope Proof & Least-Privilege Remediation

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator (Cloud Shell / Console)
    participant IAM as Project IAM Policy
    participant CAI as Cloud Asset Inventory
    participant SCC as SCC AI Protection<br/>(Agent Platform > Security)
    participant PA as IAM Policy Analyzer

    Note over Operator,SCC: Task 7: Simulate Over-Privileged Agent Service Account
    Operator->>IAM: gcloud projects add-iam-policy-binding PROJECT_ID<br/>--member="serviceAccount:${SF_SA}" --role="roles/editor"
    IAM->>CAI: Propagate IAM binding update
    CAI->>SCC: Flag salesforce_agent under "Agents with excessive permissions" (Non-human identity risk)

    Note over Operator,PA: Task 8: Prove Exact Blast Radius with Policy Analyzer
    Operator->>PA: Query Principal = ${SF_SA} on Scope = projects/${PROJECT_ID}
    PA->>CAI: Evaluate effective resource permissions
    PA-->>Operator: Shows roles/editor grants modify/delete access across almost every project resource
    Operator->>Operator: Identify required narrow roles vs. excessive roles/editor

    Note over Operator,IAM: Task 9: Remediate Service Account & Verify Least Privilege
    Operator->>IAM: List current roles for ${SF_SA}
    IAM-->>Operator: roles/aiplatform.user, roles/cloudtrace.agent, roles/editor, roles/logging.logWriter, roles/telemetry.tracesWriter
    Operator->>IAM: gcloud projects remove-iam-policy-binding PROJECT_ID<br/>--member="serviceAccount:${SF_SA}" --role="roles/editor"
    IAM-->>Operator: Binding removed
    Operator->>IAM: Verify filter="bindings.members:${SF_SA} AND bindings.role:roles/editor"
    IAM-->>Operator: Empty output (Confirmed least privilege)
```

---

## Task 10 Workflow: Triggering & Viewing Real-Time Agent Platform Threat Detection

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator (Cloud Shell)
    participant SCC_Mgmt as Security Center Management API
    participant Script as threat_test/main.py
    participant Runtime as Vertex AI Agent Runtime<br/>(scc_threat_test_agent)
    participant Sensor as Agent Platform Threat Detection<br/>(Container Runtime Sensor)
    participant SCC_Findings as Security Command Center Findings

    Operator->>SCC_Mgmt: Enable containerthreatdetection.googleapis.com &<br/>gcloud scc manage services update agent-engine-threat-detection --enablement-state=ENABLED
    SCC_Mgmt-->>Operator: effectiveEnablementState: ENABLED (All 42 AGENT_ENGINE_* modules active)
    Operator->>Script: python3 main.py
    Script->>Runtime: client.agent_engines.create(display_name="scc_threat_test_agent")
    Runtime-->>Script: Deployed reasoningEngines/6469757590153723904
    Script->>Runtime: async_stream_query("Run the threat detection test")
    Runtime->>Runtime: Call tool threat_detection_test()
    Runtime->>Runtime: 1. sleep 60 (Wait for sensor attachment)
    Runtime->>Runtime: 2. Write EICAR signature to /tmp/test_mal_file
    Runtime->>Runtime: 3. chmod 700 /tmp/test_mal_file && sh -c /tmp/test_mal_file
    Sensor-->>SCC_Findings: Emit CRITICAL Finding:<br/>Category: "Execution: Added Malicious Binary Executed"
    Runtime->>Runtime: 4. sleep 10
    Runtime-->>Script: Return tool output & model summary
    Script->>Runtime: finally: client.agent_engines.delete(force=True)
    Runtime-->>Script: Throwaway agent deleted
    Operator->>SCC_Findings: gcloud scc findings list projects/PROJECT_NUMBER
    SCC_Findings-->>Operator: CRITICAL | Execution: Added Malicious Binary Executed | reasoningEngines/6469757590153723904
```
