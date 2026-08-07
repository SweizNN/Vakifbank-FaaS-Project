# Technical Documentation

Architecture, self-hosting, production hardening, and the API reference for the VakıfBank FaaS Platform. For the product pitch and screenshots, see [README.md](README.md).

## Contents

- [Project Structure](#project-structure)
- [Tech Stack](#tech-stack)
- [Production Deployment (CI/CD)](#production-deployment-cicd)
- [Fork & Self-Host This Project](#fork--self-host-this-project)
- [Production Hardening](#production-hardening)
- [API Reference](#api-reference)
- [Monitoring](#monitoring)

---

## Project Structure

```
Vakifbank-FaaS-Project/
├── .github/workflows/deploy.yml    # CI/CD: test → build → deploy
├── setup_server.sh                 # One-time fresh-droplet prerequisites (Docker, kubectl, Minikube, git, ufw)
│
├── backend/
│   ├── main.py                     # FastAPI app wiring (routers, CORS, lifespan)
│   ├── config.py                   # Env vars + LANGUAGE_CONFIG (all 7 runtimes)
│   ├── models.py                   # Pydantic request/response schemas
│   ├── routers/                    # One file per route group
│   │   ├── deploy.py               #   POST /deploy      (code editor)
│   │   ├── sql_deploy.py           #   POST /sql/deploy  (SQL-to-API)
│   │   ├── functions.py            #   list / get / rollback / delete
│   │   └── health.py, jobs.py, languages.py, logs.py, proxy.py
│   ├── services/                   # Business logic — no FastAPI imports
│   │   ├── pipeline.py             #   func create/deploy + Docker build orchestration
│   │   ├── job_store.py            #   Redis-backed deploy-job status (shared across replicas)
│   │   ├── dependencies.py         #   injects deps into each language's manifest file
│   │   ├── k8s.py                  #   kubectl wrapper functions
│   │   └── sql_pipeline.py, sql_validator.py, secret_provisioning.py, sse.py, health_check.py
│   ├── generators/sql_to_python.py # Generates func.py from a SQL table schema
│   ├── scaffolds/dotnet/           # Static Dockerfile-build scaffold (see Supported Languages)
│   ├── tests/                      # pytest suite
│   └── Dockerfile                  # Multi-stage: Python + kubectl + func CLI + docker CLI
│
├── frontend/
│   ├── index.html                  # Single-page UI shell
│   ├── style.css
│   └── js/                         # config, templates, editor, deploy, functions,
│                                    # sql-deploy, health, theme, library-modal, utils
│
├── k8s/
│   ├── namespace.yaml              # faas-platform + tenant-functions + RBAC + ResourceQuota
│   ├── resource-quota.yaml         # LimitRange — per-container CPU/memory floor+ceiling
│   ├── deployment.yaml             # Deployment (2 replicas), ConfigMap, Secret, Service
│   ├── redis.yaml                  # Shared deploy-job store (backs services/job_store.py)
│   ├── tls.yaml                    # cert-manager ClusterIssuers + Ingress (Let's Encrypt)
│   └── kustomization.yaml
│
├── docs/screenshots/                # Images used in README.md
├── README.md                        # Product overview
└── TECHNICAL.md                     # This file
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Infrastructure | Kubernetes, Knative Serving, Docker |
| Function Builds | Knative `func` CLI + Cloud Native Buildpacks (6 languages) · plain `docker build` for .NET |
| Backend | Python 3.11, FastAPI, uvicorn |
| Shared state | Redis — deploy-job status, so the orchestrator can run >1 replica (see [High Availability](#high-availability--shared-state)) |
| TLS | cert-manager + Let's Encrypt, terminated at ingress-nginx (see [TLS](#tls)) |
| Frontend | HTML5, Vanilla JS, CodeMirror editor |
| Container Registry | Docker Hub |
| CI/CD | GitHub Actions |
| Server | DigitalOcean Droplet (4 vCPU, 8 GB RAM) |

---

## Production Deployment (CI/CD)

This platform follows a GitOps approach: push to `main`, GitHub Actions does the rest.

```bash
git add .
git commit -m "deploy: initial faas platform"
git push origin main
```

The pipeline (`.github/workflows/deploy.yml`):
1. **Test** — lint, syntax, unit, and integration tests for the Python backend
2. **Build** — builds `<your-dockerhub-user>/faas-platform-api:sha-XXXXXXX` and pushes it to Docker Hub
3. **Deploy** — SSHes into the droplet and, idempotently on every run:
   - installs/verifies Knative Serving, Kourier, cert-manager, and ingress-nginx
   - applies `k8s/namespace.yaml`, `resource-quota.yaml`, `redis.yaml`, `tls.yaml`, `deployment.yaml`
   - rolls out the new image and re-points the host's port-80/443 proxies

**Manual update**, without triggering full CI/CD, if the server is already running and you just want the latest manifests:

```bash
kubectl apply -k https://github.com/sweiznn/Vakifbank-FaaS-Project/k8s
```

---

## Fork & Self-Host This Project

Everything environment-specific is driven by GitHub Secrets and substituted into the manifests at deploy time — forking this repo onto your own Docker Hub account and droplet does **not** require hand-editing any YAML.

**1. Provision a fresh Ubuntu droplet** (DigitalOcean or otherwise) and run the prerequisites script once, over SSH:

```bash
curl -sL https://raw.githubusercontent.com/sweiznn/Vakifbank-FaaS-Project/main/setup_server.sh | bash
```

This installs Docker, kubectl, Minikube, git, and ufw — nothing Kubernetes-specific. The CD pipeline installs and configures the rest (Knative, cert-manager, ingress-nginx, the application) on every push.

**2. Set these GitHub Secrets** (repo → Settings → Secrets and variables → Actions):

| Secret | Used for |
|--------|----------|
| `DOCKER_HUB_USER` | Image name prefix (`<user>/faas-platform-api`) and `REGISTRY_PREFIX` for tenant function images |
| `DOCKER_HUB_USERNAME` / `DOCKER_HUB_TOKEN` | Docker Hub login (build-push job + in-cluster `docker-hub-creds` pull secret) |
| `DO_DROPLET_IP` | SSH target; also substituted into every `*.sslip.io` hostname in `k8s/tls.yaml` and Knative's magic-DNS config |
| `DO_SSH_USER` / `DO_SSH_KEY` | SSH access to the droplet |
| `LETSENCRYPT_EMAIL` | ACME account contact for both ClusterIssuers in `k8s/tls.yaml` — **use a real address**, not `@example.com`/`.org`/`.net`: Let's Encrypt hard-rejects those reserved domains and the ClusterIssuer fails to register |

**3. Push to `main`.** First run takes longer (installing Knative/cert-manager/ingress-nginx from scratch); subsequent runs are fast, idempotent updates.

**4. Verify:**

```bash
kubectl get pods -n faas-platform                                    # 2 orchestrator pods + redis
kubectl describe certificate faas-platform-tls -n faas-platform      # wait for Ready=True
```

New deploys default to the Let's Encrypt **staging** issuer (see [TLS](#tls) below) — flip to production once verified.

---

## Production Hardening

### Resource Quotas

Every function deploy used to run with no CPU/memory bounds at all — a single
runaway function could take down every other tenant on the droplet.
[`k8s/resource-quota.yaml`](k8s/resource-quota.yaml) adds a `LimitRange` for
`tenant-functions`: containers that don't request their own limits (every
deploy today) get `100m`/`128Mi` requests and a `500m`/`512Mi` cap by default,
with a hard `2` vCPU / `2Gi` ceiling even for functions that do set their own.
[`k8s/namespace.yaml`](k8s/namespace.yaml)'s pre-existing `ResourceQuota` was
extended the same way, capping the namespace as a whole (`requests.cpu: 3`,
`limits.cpu: 6`, etc.) so it can't consume the entire 4 vCPU / 8 GB droplet
and starve `faas-platform` itself or the node's system pods.

> **Watch the floor, not just the ceiling.** Knative Serving's own revision
> controller sets a `25m` CPU request on every user-container itself,
> unconditionally — it's not something `func deploy` sends or a LimitRange
> default fills in. `min.cpu` in the LimitRange must stay at or below that
> (currently `10m`) or *every single deploy* is rejected outright
> (`FailedCreate: minimum cpu usage per Container is 50m, but request is
> 25m`) and every Route reports `RevisionMissing` — found this the hard way
> in production.

```bash
kubectl describe limitrange tenant-functions-limits -n tenant-functions
kubectl describe resourcequota tenant-functions-quota -n tenant-functions
```

### High Availability / Shared State

Deploy-job status (`GET /jobs/{id}`) used to live in a plain in-memory `dict`
inside the FastAPI process. That only works with exactly one orchestrator
pod — a rollout or a crash would silently drop every in-flight job's status.
[`services/job_store.py`](backend/services/job_store.py) moves that state into
Redis ([`k8s/redis.yaml`](k8s/redis.yaml)), which is what makes
`replicas: 2` in [`k8s/deployment.yaml`](k8s/deployment.yaml) safe: any
orchestrator pod can now answer a status lookup for a job a *different* pod
wrote. Job records expire after `JOB_TTL_SECONDS` (24h by default) — it's a
status cache, not a database; a deployed function's real state still lives as
ksvc/Revision annotations in the cluster, not in Redis.

```bash
kubectl get pods -n faas-platform -l app=faas-platform-api   # 2 pods
kubectl exec -n faas-platform deploy/faas-redis -- redis-cli keys 'faas:job:*'
```

### TLS

The platform's UI/API (not the deployed tenant functions — see
[`k8s/tls.yaml`](k8s/tls.yaml) for why that's a separate problem requiring a
wildcard cert) is served over HTTPS via **cert-manager** issuing a real
**Let's Encrypt** certificate, terminated at an **ingress-nginx** controller
that the CD pipeline installs as the droplet's single host-port-80/443
entrypoint — Knative/Kourier function traffic keeps flowing through it
unchanged via a passthrough `Ingress`. No purchased domain needed: it's
served on `https://<droplet-ip>.sslip.io`, since [sslip.io](https://sslip.io)
resolves any hostname containing an IP back to that IP.

> **ingress-nginx redirects HTTP → HTTPS by default**, even for hosts with no
> `tls:` block on any Ingress (it uses its own fake default cert for that
> redirect). The passthrough Ingress for Knative function traffic explicitly
> sets `nginx.ingress.kubernetes.io/ssl-redirect: "false"` to opt back out —
> without it, every plain `http://<fn>....sslip.io` link 308s to an https
> host nothing serves a real cert for, the request never reaches Kourier, and
> no pod ever cold-starts.

New deploys default to the **staging** Let's Encrypt issuer (untrusted-by-
design cert, but proves HTTP-01 end to end without touching production rate
limits: 5 failures/hour, 50 certs/week/domain). Once verified, flip the
`cert-manager.io/cluster-issuer` annotation on `faas-platform-ingress` in
`k8s/tls.yaml` to `letsencrypt-prod`:

```bash
kubectl describe certificate faas-platform-tls -n faas-platform   # wait for Ready=True
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/health` | Liveness/readiness probe |
| `GET` | `/health/detail` | Full system + tool health check (includes Redis) |
| `GET` | `/languages` | Supported runtimes |
| `POST` | `/deploy` | Deploy a function from code (SSE stream) |
| `POST` | `/sql/deploy` | Deploy a SQL-to-API function (SSE stream) |
| `GET` | `/functions` | List deployed functions |
| `GET` | `/functions/{name}/code` | Get a function's current code + config |
| `GET` | `/functions/{name}/revisions` | List revision history |
| `GET` | `/functions/{name}/revision/{revision_name}/code` | Get code saved in a specific revision |
| `POST` | `/functions/{name}/rollback` | Roll traffic back to a specific revision |
| `DELETE` | `/functions/{name}` | Delete a function |
| `GET` | `/logs/{name}` | Recent pod logs |
| `POST` | `/proxy` | Proxy a request to a deployed function (CORS bypass for testing) |
| `GET` | `/jobs/{job_id}` | Deploy job status (Redis-backed, shared across replicas) |
| `GET` | `/docs` | Swagger UI |

---

## Monitoring

```bash
# Watch pods in both namespaces
kubectl get pods -n faas-platform -w
kubectl get pods -n tenant-functions -w

# List all deployed Knative functions
kubectl get ksvc -n tenant-functions

# View orchestrator logs (either replica)
kubectl logs -n faas-platform -l app=faas-platform-api -f

# View a specific function's logs
kubectl logs -n tenant-functions -l serving.knative.dev/service=my-function --prefix -f

# Inspect a revision that failed to become Ready
kubectl describe revision <name> -n tenant-functions
kubectl get events -n tenant-functions --sort-by='.lastTimestamp'
```
