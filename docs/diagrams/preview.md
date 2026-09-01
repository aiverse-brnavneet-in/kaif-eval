# kaif-eval diagrams (Mermaid preview)

Use this file if Excalidraw files do not open. Open markdown preview: **Cmd+Shift+V** (Mac) / **Ctrl+Shift+V** (Windows).

---

## 1. kaif-eval overview

```mermaid
flowchart LR
  subgraph signals [Signals]
    T[Telemetry\nJaeger · Prometheus · OTel]
    A[Agent runtimes\nkagent · ADK]
    AR[Artifact systems\nGit · S3]
    B[Business apps\nJira · CRM]
  end

  subgraph engine [kaif-eval engine]
    ED[Eval designer] --> CFG[Configuration]
    CFG --> W[Worker job]
    W --> O[Outcome engine]
    W --> Q[Quality engine]
    O --> ST[(Eval store)]
    Q --> ST
  end

  subgraph value [kaif-value]
    ST --> R[Read eval store]
    R --> K[Export KPIs]
    K --> G[Grafana dashboards]
    K --> AG[Agents feedback loop]
  end

  signals -. evidence .-> W
```

---

## 2. Eval designer (mother file)

```mermaid
flowchart TB
  MF[eval-designer.yaml\nkind: EvalDesigner]

  MF --> SID[Unique ID / session_id]
  MF --> LAB[Labels]
  MF --> CON[Connectors]
  MF --> SRC[Sources]
  MF --> POL[Policies]
  MF --> STO[Eval store + schema]
  MF --> WRK[Worker config]
  MF --> EVD[Evidence map]

  SID & LAB & CON & SRC & POL & STO & WRK & EVD --> ASM[Configuration assembly\napp/config.py]

  UI[UI wizard] -.-> MF
  CRD[K8s EvalDesigner CRD] -.-> MF
  GIT[GitOps overlay] -.-> MF
```

---

## 3. Worker job

```mermaid
flowchart TB
  subgraph triggers [Triggers]
    CLI[Manual / CLI]
    API[HTTP API]
    SCH[Scheduler cron]
    EVT[Events Kafka · Argo · K8s · SNS]
  end

  triggers --> W[Worker job]

  W --> L[1 Config load]
  L --> V[2 Validation]
  V --> F[3 Fetch evidence]
  F --> P[4 Policy engine]
  P --> C[5 Pluggable rules]
  C --> AL[6 Alerting on failure]
  AL --> OUT[7 Write eval store]

  subgraph policy [Policy engine]
    D[Deterministic rules]
    J[LLM-as-judge G-Eval]
    BYO[Bring your own eval]
  end

  P --> D & J & BYO
```

---

## 4. Correlation engine

```mermaid
flowchart TB
  subgraph otel [OTel telemetry - primary]
    TR[Traces Jaeger/Tempo]
    ME[Metrics Prometheus]
    LO[Logs Loki]
  end

  CID[Correlation ID\nsession_id / job_id]

  TR & ME --> CID

  CID --> RT[Agent runtime data]
  CID --> BD[Business data]
  CID --> AF[Artifacts Git/S3]
  CID --> API[Custom HTTP sources]

  subgraph quality [Quality measurement]
    OOB[OOB deterministic]
    CD[Custom deterministic]
    GEV[LLM-as-judge]
    FW[BYO framework]
  end

  RT & AF --> OOB & CD
  CID --> GEV
  OOB & CD & GEV & FW --> REC[(Eval store record)]
```
