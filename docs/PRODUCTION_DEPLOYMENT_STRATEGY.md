# Production Deployment Strategy — job-hunter-agent

## Executive Summary

This document proposes a production deployment strategy for the job-hunter-agent, covering:
1. **Temporal orchestration** — replacing JSON checkpoint files with durable workflows
2. **Cloud infrastructure** — AWS-based deployment with Terraform IaC
3. **Kubernetes deployment** — EKS for container orchestration
4. **Cost optimization** — right-sizing, spot instances, and autoscaling
5. **Observability & reliability** — production-grade monitoring and alerting

---

## 1. Temporal Orchestration (Phase 2)

### Why Temporal?

The current pipeline uses a sequential async loop with JSON checkpoint files. This works for single-machine MVP but has limitations:

| Current (Checkpoints) | Temporal |
|---|---|
| Single-machine only | Distributed workers across nodes |
| File-based crash recovery (JSON) | Built-in durable execution history |
| No activity-level retries (agent = all-or-nothing) | Per-activity retry policies with backoff |
| No visibility into running workflows | Temporal Web UI for workflow inspection |
| Manual resume via `--resume-from` | Automatic resume after worker restart |
| Sequential only | Supports parallelism (e.g., scrape multiple companies concurrently) |

### Architecture

```
                    ┌─────────────────┐
                    │  Temporal Server │
                    │  (self-hosted or │
                    │   Temporal Cloud) │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───────┐ ┌───▼────────┐ ┌──▼─────────────┐
     │ Pipeline Worker │ │ LLM Worker │ │ Scraping Worker │
     │ (orchestration) │ │ (CPU-light)│ │ (Chromium-heavy)│
     └────────────────┘ └────────────┘ └─────────────────┘
```

### Workflow Design

```python
# workflows/job_hunt_workflow.py
@workflow.defn
class JobHuntWorkflow:
    @workflow.run
    async def run(self, config: RunConfigPayload) -> RunResultPayload:
        # Step 1: Parse resume (lightweight LLM call)
        profile = await workflow.execute_activity(
            parse_resume, config.resume_path,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Step 2: Parse preferences (lightweight LLM call)
        preferences = await workflow.execute_activity(
            parse_preferences, config.preferences_text,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Step 3: Find companies (Sonnet + web search)
        companies = await workflow.execute_activity(
            find_companies, profile, preferences,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue="llm-workers",
        )

        # Step 4: Scrape jobs — PARALLEL per company
        scrape_futures = [
            workflow.execute_activity(
                scrape_company_jobs, company,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=3),
                task_queue="scraping-workers",
            )
            for company in companies
        ]
        raw_jobs_per_company = await asyncio.gather(*scrape_futures)
        raw_jobs = [job for batch in raw_jobs_per_company for job in batch]

        # Step 5: Process jobs (normalize + embed)
        normalized_jobs = await workflow.execute_activity(
            process_jobs, raw_jobs,
            start_to_close_timeout=timedelta(minutes=5),
            task_queue="llm-workers",
        )

        # Step 6: Score jobs (Sonnet LLM + semantic)
        scored_jobs = await workflow.execute_activity(
            score_jobs, profile, preferences, normalized_jobs,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue="llm-workers",
        )

        # Step 7: Aggregate output
        output_files = await workflow.execute_activity(
            aggregate_results, scored_jobs,
            start_to_close_timeout=timedelta(minutes=2),
        )

        # Step 8: Notify
        await workflow.execute_activity(
            send_notification, output_files, config.email,
            start_to_close_timeout=timedelta(minutes=1),
        )

        return RunResultPayload(...)
```

### Worker Task Queues

| Queue | Purpose | Resource Profile | Scaling |
|-------|---------|-----------------|---------|
| `default` | Pipeline orchestration, aggregation | Low CPU, low memory | 1-2 replicas |
| `llm-workers` | LLM calls (parsing, scoring, company discovery) | Low CPU, low memory (I/O bound) | 2-5 replicas |
| `scraping-workers` | Web scraping (crawl4ai + Playwright) | Medium CPU, 1-2GB RAM (Chromium) | 2-10 replicas (autoscale) |

### Key Benefit: Per-Company Parallelism

The biggest performance win is **scraping multiple companies in parallel** (Step 4). Today the pipeline runs sequentially — with 20 companies this means 20 serial scrapes (~60s each = ~20 min). With Temporal, each company scrape is an independent activity that runs on separate workers concurrently.

**Estimated speedup**: 20 companies × 60s serial → ~60-90s parallel with 10 scraping workers.

### Temporal Deployment Options

| Option | Cost | Ops Burden | Best For |
|--------|------|-----------|----------|
| **Temporal Cloud** (managed) | ~$200/mo for 100K actions | Zero | Teams wanting managed service |
| **Self-hosted on EKS** | ~$50-100/mo (infra) | Medium | Cost-sensitive, full control |
| **Self-hosted on single EC2** | ~$30/mo | Low | Dev/staging environments |

**Recommendation**: Start with **Temporal Cloud** for production (zero ops), self-hosted for staging.

### Migration Strategy

The migration is **backward-compatible**: the existing `Pipeline` class continues to work as-is. Temporal is introduced as a new orchestration mode:

1. Create `src/job_hunter_agents/orchestrator/temporal_workflow.py` and `temporal_activities.py`
2. Each activity wraps the existing agent `.run()` method — no agent code changes needed
3. Add `JH_ORCHESTRATOR=checkpoint|temporal` setting to `Settings`
4. CLI gets `--temporal` flag; defaults to checkpoint mode
5. Workers registered via `src/job_hunter_cli/worker.py` CLI command

```
# Run with existing checkpoint pipeline (default)
job-hunter run resume.pdf --prefs "..."

# Run via Temporal workflow
job-hunter run resume.pdf --prefs "..." --temporal

# Start a Temporal worker
job-hunter worker --queue llm-workers
job-hunter worker --queue scraping-workers
```

### New Dependencies

```toml
# pyproject.toml additions
"temporalio>=1.7",
```

---

## 2. Cloud Infrastructure (AWS)

### Target Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          AWS VPC                                │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │ Public Subnet │  │ Private Subnet│  │   Private Subnet     │ │
│  │              │  │              │  │                       │ │
│  │   ALB/NLB    │  │  EKS Nodes   │  │   RDS PostgreSQL     │ │
│  │   (future    │  │  (workers)   │  │   (pgvector)         │ │
│  │    web UI)   │  │              │  │                       │ │
│  │              │  │  Temporal    │  │   ElastiCache Redis   │ │
│  │              │  │  Workers     │  │   (cache layer)       │ │
│  └──────────────┘  └──────────────┘  └───────────────────────┘ │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │     ECR      │  │     S3       │  │  CloudWatch / OTEL    │ │
│  │  (container  │  │  (output     │  │  (logs, metrics,      │ │
│  │   registry)  │  │   files)     │  │   traces)             │ │
│  └──────────────┘  └──────────────┘  └───────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Component Choices

| Component | AWS Service | Why | Estimated Cost |
|-----------|------------|-----|----------------|
| **Container Orchestration** | EKS (Fargate or managed nodes) | K8s-native, scales to demand | $73/mo (control plane) + nodes |
| **Database** | RDS PostgreSQL 16 + pgvector | Managed, automated backups | ~$30-60/mo (db.t4g.medium) |
| **Cache** | ElastiCache Redis | Managed, HA, auto-failover | ~$25/mo (cache.t4g.micro) |
| **Container Registry** | ECR | Integrated with EKS, low latency | ~$5/mo |
| **Object Storage** | S3 | Output files (CSV/Excel), resume uploads | ~$1/mo |
| **Secrets** | AWS Secrets Manager | API keys (Anthropic, Tavily, etc.) | ~$5/mo |
| **Logging** | CloudWatch Logs | Centralized, auto-retention | ~$5-10/mo |
| **Tracing** | AWS X-Ray or Jaeger on EKS | OTEL-compatible | ~$5/mo |
| **DNS/TLS** | Route 53 + ACM | Future web UI | ~$1/mo |

### Cost Tiers

#### Tier 1: Minimal Production (~$150-200/mo)
- EKS Fargate (pay per pod, no idle node cost)
- RDS db.t4g.micro (2 vCPU, 1 GB) — single AZ
- ElastiCache cache.t4g.micro — single node
- S3 Standard
- 1-2 Fargate pods (0.5 vCPU, 1 GB each)

**Best for**: Low-traffic, single-user or small team usage

#### Tier 2: Standard Production (~$400-600/mo)
- EKS managed nodes (t3.medium spot instances)
- RDS db.t4g.medium (2 vCPU, 4 GB) — multi-AZ
- ElastiCache cache.t4g.small — 2 node cluster
- S3 Standard + lifecycle rules
- 3-5 worker pods, HPA autoscaling
- Temporal Cloud ($200/mo)

**Best for**: Multi-user, recurring scheduled runs

#### Tier 3: High Scale (~$1000-1500/mo)
- EKS managed nodes (c6g.large for scraping workers)
- RDS db.r6g.large (2 vCPU, 16 GB) — multi-AZ, read replica
- ElastiCache cache.r6g.large — 3 node cluster
- S3 Intelligent-Tiering
- 10-20 worker pods, KEDA event-driven autoscaling
- Temporal Cloud or self-hosted cluster

**Best for**: SaaS deployment, hundreds of concurrent users

---

## 3. Terraform Structure

```
infra/
├── terraform/
│   ├── environments/
│   │   ├── dev/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   ├── terraform.tfvars
│   │   │   └── backend.tf
│   │   ├── staging/
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   ├── terraform.tfvars
│   │   │   └── backend.tf
│   │   └── prod/
│   │       ├── main.tf
│   │       ├── variables.tf
│   │       ├── terraform.tfvars
│   │       └── backend.tf
│   │
│   └── modules/
│       ├── vpc/
│       │   ├── main.tf           # VPC, subnets, NAT gateway, security groups
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── eks/
│       │   ├── main.tf           # EKS cluster, node groups, IRSA
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── rds/
│       │   ├── main.tf           # RDS PostgreSQL + pgvector
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── elasticache/
│       │   ├── main.tf           # ElastiCache Redis cluster
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── ecr/
│       │   ├── main.tf           # ECR repository + lifecycle policy
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── s3/
│       │   ├── main.tf           # S3 bucket for outputs + resumes
│       │   ├── variables.tf
│       │   └── outputs.tf
│       ├── secrets/
│       │   ├── main.tf           # Secrets Manager entries
│       │   ├── variables.tf
│       │   └── outputs.tf
│       └── monitoring/
│           ├── main.tf           # CloudWatch log groups, alarms, dashboards
│           ├── variables.tf
│           └── outputs.tf
```

### Key Terraform Modules

#### VPC Module
- 3 AZ deployment (us-east-1a/b/c)
- Public subnets (ALB/NAT), Private subnets (EKS nodes, RDS, ElastiCache)
- NAT Gateway for outbound internet (scraping, API calls)
- Security groups: workers → RDS (5432), workers → Redis (6379), workers → internet (443)

#### EKS Module
- Managed node groups with mixed instance types
- **Spot instances** for scraping workers (70% cost savings)
- On-demand instances for pipeline/LLM workers (reliability)
- Cluster autoscaler or Karpenter for node scaling
- IRSA (IAM Roles for Service Accounts) for fine-grained AWS access

#### RDS Module
- PostgreSQL 16 with pgvector extension pre-installed
- Automated backups (7-day retention)
- Encryption at rest (KMS)
- Parameter group with pgvector-specific settings
- Multi-AZ for prod, single AZ for dev/staging

#### ElastiCache Module
- Redis 7 cluster mode
- Encryption in transit + at rest
- Automatic failover for prod
- Single node for dev/staging

---

## 4. Kubernetes Manifests

```
infra/
├── k8s/
│   ├── base/                        # Kustomize base
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── configmap.yaml           # Non-secret configuration
│   │   ├── secret-external.yaml     # ExternalSecret CRD (AWS Secrets Manager)
│   │   ├── deployment-worker-default.yaml
│   │   ├── deployment-worker-llm.yaml
│   │   ├── deployment-worker-scraping.yaml
│   │   ├── hpa-scraping.yaml        # HorizontalPodAutoscaler
│   │   ├── pdb.yaml                 # PodDisruptionBudget
│   │   └── serviceaccount.yaml      # IRSA annotation
│   │
│   ├── overlays/
│   │   ├── dev/
│   │   │   ├── kustomization.yaml
│   │   │   └── patches/             # Lower replicas, smaller resources
│   │   ├── staging/
│   │   │   ├── kustomization.yaml
│   │   │   └── patches/
│   │   └── prod/
│   │       ├── kustomization.yaml
│   │       └── patches/             # Higher replicas, PDB, anti-affinity
│   │
│   └── jobs/
│       └── cronjob-scheduled-run.yaml  # Optional: scheduled pipeline runs
```

### Worker Deployment (Scraping Workers Example)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker-scraping
  namespace: job-hunter
spec:
  replicas: 2
  selector:
    matchLabels:
      app: job-hunter
      component: worker-scraping
  template:
    metadata:
      labels:
        app: job-hunter
        component: worker-scraping
    spec:
      serviceAccountName: job-hunter-worker
      containers:
        - name: worker
          image: <account>.dkr.ecr.<region>.amazonaws.com/job-hunter-agent:latest
          command: ["job-hunter", "worker", "--queue", "scraping-workers"]
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              cpu: "1000m"
              memory: "2Gi"       # Chromium needs memory
          env:
            - name: JH_DB_BACKEND
              value: "postgres"
            - name: JH_CACHE_BACKEND
              value: "redis"
          envFrom:
            - configMapRef:
                name: job-hunter-config
            - secretRef:
                name: job-hunter-secrets
          livenessProbe:
            exec:
              command: ["python", "-c", "import job_hunter_agents; print('ok')"]
            initialDelaySeconds: 30
            periodSeconds: 60
          readinessProbe:
            exec:
              command: ["python", "-c", "import job_hunter_agents; print('ok')"]
            initialDelaySeconds: 10
            periodSeconds: 30
      tolerations:
        - key: "workload-type"
          operator: "Equal"
          value: "scraping"
          effect: "NoSchedule"
      nodeSelector:
        workload-type: scraping         # Schedule on spot nodes
```

### HorizontalPodAutoscaler (Scraping Workers)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: worker-scraping-hpa
  namespace: job-hunter
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: worker-scraping
  minReplicas: 1
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300    # Wait 5 min before scaling down
```

---

## 5. Cost Optimization Strategies

### 5.1 Spot Instances for Scraping Workers
- Scraping workers are stateless and fault-tolerant (Temporal retries failed activities)
- **Spot savings**: ~70% cheaper than on-demand
- Mix instance types: `c6g.medium`, `c6g.large`, `m6g.medium` for availability
- Karpenter automatically selects cheapest available spot instances

### 5.2 Fargate for Low-Traffic Deployments
- No idle node cost — pay only when pods run
- Good for Tier 1 deployments where runs are infrequent (e.g., weekly job searches)
- Each pipeline run spins up pods, completes, and shuts down

### 5.3 RDS Right-Sizing
- Start with `db.t4g.micro` (free tier eligible) for dev
- Scale to `db.t4g.medium` for prod based on actual query load
- Enable Performance Insights ($0) to monitor before scaling up
- Storage autoscaling (start 20 GB, grow as needed)

### 5.4 S3 Lifecycle Policies
- Output files → S3 Standard (30 days) → S3 IA (90 days) → Glacier (1 year) → Delete
- Resume PDFs → S3 Standard (keep indefinitely, small files)

### 5.5 LLM Cost Management (Already Implemented)
- Cost guardrails (`max_cost_per_run_usd`, `warn_cost_threshold_usd`)
- Haiku for routine tasks, Sonnet only for complex reasoning
- Token tracking per run in `run_history` table

### 5.6 Scheduled Scaling
- For SaaS: scale down scraping workers at night (cron-based HPA or Karpenter schedules)
- RDS: stop dev/staging instances outside business hours (Aurora Serverless v2 alternative)

---

## 6. CI/CD Pipeline Enhancement

### GitHub Actions Workflow (Updated)

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      id-token: write       # OIDC for AWS
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-arn: arn:aws:iam::role/github-actions-deploy
          aws-region: us-east-1
      - uses: aws-actions/amazon-ecr-login@v2
      - name: Build and push
        run: |
          docker build -t $ECR_REPO:${{ github.sha }} .
          docker push $ECR_REPO:${{ github.sha }}
          docker tag $ECR_REPO:${{ github.sha }} $ECR_REPO:latest
          docker push $ECR_REPO:latest

  deploy-staging:
    needs: build-and-push
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to staging
        run: |
          cd infra/k8s
          kustomize build overlays/staging | \
            sed "s|IMAGE_TAG|${{ github.sha }}|g" | \
            kubectl apply -f -
      - name: Run smoke test
        run: |
          kubectl exec -n job-hunter deploy/worker-default -- \
            job-hunter run /app/data/test_resume.pdf \
            --prefs "test preferences" --dry-run --lite

  deploy-prod:
    needs: deploy-staging
    if: startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to production
        run: |
          cd infra/k8s
          kustomize build overlays/prod | \
            sed "s|IMAGE_TAG|${{ github.sha }}|g" | \
            kubectl apply -f -
```

---

## 7. Observability for Production

### Logging
- **structlog** → JSON format → CloudWatch Logs (via Fluent Bit DaemonSet)
- Log groups: `/job-hunter/workers`, `/job-hunter/pipeline-runs`
- Retention: 30 days (dev), 90 days (prod)

### Metrics
- **CloudWatch Container Insights** for EKS node/pod metrics
- **Custom metrics** via OTEL Collector:
  - `pipeline.runs.total` (counter)
  - `pipeline.runs.duration_seconds` (histogram)
  - `pipeline.runs.cost_usd` (histogram)
  - `pipeline.jobs.scored` (counter)
  - `agent.errors.total` (counter, by agent_name)
  - `scraper.requests.total` (counter, by domain)

### Tracing
- **OTEL Collector** on EKS → AWS X-Ray or Jaeger
- Pipeline root span → per-agent child spans (already implemented)
- Activity spans added by Temporal SDK automatically

### Alerting
- Pipeline failure rate > 10% (5 min window) → PagerDuty/Slack
- Cost per run > $3.00 → Slack warning
- Worker pod crash loops → PagerDuty
- RDS CPU > 80% for 5 min → Slack
- Redis memory > 80% → Slack

---

## 8. Security

### Secrets Management
- All API keys in **AWS Secrets Manager** (not env vars in manifests)
- ExternalSecrets Operator syncs to K8s Secrets
- Rotation policy: 90-day rotation for SMTP/DB credentials

### Network Security
- RDS + ElastiCache in private subnets (no public access)
- Security groups: only EKS worker nodes can access RDS/Redis
- NAT Gateway for outbound internet (scraping, API calls)
- Network policies: workers can only reach allowed endpoints

### Container Security
- Non-root user in Dockerfile (already implemented: `appuser:1000`)
- Read-only root filesystem where possible
- No privileged containers
- Image scanning via ECR native scanning or Trivy

### IAM
- IRSA: each service account has minimal IAM role
- Workers: ECR pull, S3 read/write (output bucket), Secrets Manager read
- No broad `*` permissions

---

## 9. Implementation Order

| Phase | What | Effort | Priority |
|-------|------|--------|----------|
| **Phase 12a** | Terraform modules (VPC, EKS, RDS, ElastiCache, ECR, S3, Secrets) | 3-5 days | High |
| **Phase 12b** | Kubernetes base manifests + Kustomize overlays | 2-3 days | High |
| **Phase 12c** | CI/CD deploy workflow (ECR push + K8s deploy) | 1-2 days | High |
| **Phase 13a** | Temporal activities + workflow definition | 3-4 days | Medium |
| **Phase 13b** | Worker CLI command (`job-hunter worker`) | 1 day | Medium |
| **Phase 13c** | Temporal worker K8s deployments | 1 day | Medium |
| **Phase 14** | OTEL Collector + CloudWatch + alerting | 2-3 days | Medium |
| **Phase 15** | S3 integration for output files + resume uploads | 1-2 days | Low |
| **Phase 16** | KEDA/Karpenter advanced autoscaling | 1-2 days | Low |

### What I'll Build Now (Phases 12a-12c)

Upon your approval, I'll implement:

1. **Terraform modules** — VPC, EKS, RDS (pgvector), ElastiCache, ECR, S3, Secrets Manager, monitoring
2. **Terraform environments** — dev, staging, prod with appropriate sizing
3. **Kubernetes manifests** — Kustomize base + overlays for dev/staging/prod
4. **CI/CD workflow** — GitHub Actions deploy pipeline (build → push ECR → deploy staging → deploy prod)
5. **Updated Makefile** — Terraform and K8s deployment targets

### What's Deferred (Phases 13-16)

Temporal orchestration, OTEL collector, S3 integration, and advanced autoscaling are documented but not implemented in this PR. They require the infrastructure to be deployed first and will be follow-up PRs.

---

## 10. Alternative Approaches Considered

### ECS Fargate vs EKS
| | ECS Fargate | EKS |
|--|---|---|
| **Ops overhead** | Lower (no nodes) | Medium (node groups, but Karpenter helps) |
| **Cost (low traffic)** | Cheaper (pay per task) | More expensive (control plane $73/mo) |
| **Cost (high traffic)** | More expensive (no spot for Fargate tasks) | Cheaper (spot nodes) |
| **Ecosystem** | AWS-only | K8s ecosystem (Helm, Kustomize, service mesh) |
| **Temporal** | Supported but less flexible | Native fit with Temporal Helm chart |
| **Future web UI** | Need separate ALB config | Ingress controller built-in |

**Recommendation**: EKS for standard/high-scale; ECS Fargate acceptable for minimal deployments. The Terraform modules will support both via a variable toggle.

### GCP / Azure
The Terraform modules target AWS but use standard patterns. Equivalents:
- **GCP**: GKE + Cloud SQL + Memorystore + GCR + GCS
- **Azure**: AKS + Azure Database for PostgreSQL + Azure Cache for Redis + ACR + Blob Storage

If you prefer GCP or Azure, I can adjust the modules.

### Serverless (Lambda)
Not recommended. The pipeline runs are long-lived (5-30 minutes), use Playwright/Chromium (not Lambda-friendly), and benefit from persistent connections to DB/Redis. Lambda's 15-min timeout and cold starts make it a poor fit.

---

## Open Questions for Your Input

1. **Cloud provider**: AWS (proposed) vs GCP vs Azure?
2. **Cost tier**: Tier 1 (~$150/mo), Tier 2 (~$500/mo), or Tier 3 (~$1500/mo)?
3. **Temporal**: Temporal Cloud (managed, ~$200/mo) vs self-hosted on EKS?
4. **Region**: us-east-1 (cheapest), or another region closer to your users?
5. **Domain name**: Do you have a domain for the future web UI and API?
6. **Implement Temporal now**: Should I include Temporal workflow code in this PR, or just infrastructure?
