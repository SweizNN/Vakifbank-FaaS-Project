# VakıfBank FaaS Platform — Internal Developer Platform

A custom, platform-agnostic **Function-as-a-Service (FaaS)** environment built on **Kubernetes**, **Knative Serving**, and the **Knative `func` CLI**. Developers paste raw code into a web UI, select a runtime, and receive a live HTTPS URL — no Dockerfiles, no YAML, no friction.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     faas-platform namespace                         │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                 FastAPI Orchestrator (main.py)               │   │
│  │                                                              │   │
│  │  GET  /           → Serves index.html UI                     │   │
│  │  GET  /health     → Tool + cluster health check              │   │
│  │  POST /deploy     → SSE stream: func create + func deploy    │   │
│  │  GET  /functions  → List all Knative Services                │   │
│  │  DEL  /functions/{name} → kubectl delete ksvc                │   │
│  │  GET  /logs/{name}     → Pod log tail                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ func create + func deploy
                                   │ (subprocess + SSE stream)
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   tenant-functions namespace                        │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Knative Service (ksvc) — one per user function              │   │
│  │  Built via Cloud Native Buildpacks (no Dockerfile needed)    │   │
│  │  ✓ Scale-to-Zero        ✓ Auto Scale-up                     │   │
│  │  ✓ Live HTTPS URL       ✓ Isolated namespace                │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
Vakifbank-FaaS-Project/
├── .github/
│   └── workflows/
│       └── deploy.yml          # GitHub Actions CI/CD pipeline
│
├── backend/
│   ├── main.py                 # FastAPI orchestrator (SSE deploy, CRUD)
│   ├── health_check.py         # Phase 1: startup tool verifier
│   ├── requirements.txt        # Python dependencies
│   └── Dockerfile              # Multi-stage build (Python + kubectl + func CLI)
│
├── frontend/
│   └── index.html              # Single-file UI (served by FastAPI)
│
├── k8s/
│   ├── namespace.yaml          # faas-platform + tenant-functions + RBAC
│   └── deployment.yaml         # FastAPI Deployment, ConfigMap, Secret, Service
│
└── README.md                   # This file
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Infrastructure | Kubernetes (k3s), Knative Serving |
| Function Deployment | Knative `func` CLI + Cloud Native Buildpacks |
| Backend | Python 3.11, FastAPI, uvicorn |
| Frontend | HTML5, Vanilla JS, CodeMirror editor |
| Container Registry | Docker Hub |
| CI/CD | GitHub Actions |
| Server | DigitalOcean Droplet (4 vCPU, 8 GB RAM) |

---


## Production Deployment (CI/CD)

###  One-Click Deployment Methods

FaaS Platform uses a modern GitOps approach. You do **not** need to manually download the repository or install dependencies individually.

#### 1. Fresh Server Install (Zero to Hero)
If you have a brand new, empty Ubuntu server (e.g. a DigitalOcean Droplet), you can install Kubernetes, Knative, and deploy the entire FaaS platform with this single command:

```bash
curl -sL https://raw.githubusercontent.com/sweiznn/Vakifbank-FaaS-Project/main/setup_server.sh | bash
```

#### 2. Manual Update (Kustomize / GitOps)
If the server is already running and you just want to pull your latest configuration changes directly from GitHub without triggering CI/CD, run:

```bash
kubectl apply -k https://github.com/sweiznn/Vakifbank-FaaS-Project/k8s
```

### Deploy via GitHub Actions

Push to `main` — the pipeline runs automatically:

```bash
git add .
git commit -m "deploy: initial faas platform"
git push origin main
```

The pipeline will:
1. **Test** — lint + syntax check Python code
2. **Build** — build `sweizn/faas-platform-api:sha-XXXXXXX` and push to Docker Hub
3. **Deploy** — SSH into the droplet, apply manifests, rollout the new image


## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/health` | Tool + cluster health |
| `GET` | `/languages` | Supported runtimes |
| `POST` | `/deploy` | Deploy function (SSE stream) |
| `GET` | `/functions` | List deployed functions |
| `DELETE` | `/functions/{name}` | Delete a function |
| `GET` | `/logs/{name}` | Recent pod logs |
| `GET` | `/jobs/{job_id}` | Deploy job status |
| `GET` | `/docs` | Swagger UI |


### Supported Languages

| Language | Template | Entrypoint |
|----------|----------|------------|
| `python` | `python` | `function/func.py` |
| `node` | `node` | `index.js` |
| `go` | `go` | `function.go` |
| `typescript` | `typescript` | `index.ts` |
| `quarkus` | `quarkus` | `src/main/java/functions/Function.java` |
| `rust` | `rust` | `src/main.rs` |

---

## Monitoring

```bash
# Watch pods in both namespaces
kubectl get pods -n faas-platform -w
kubectl get pods -n tenant-functions -w

# List all deployed Knative functions
kubectl get ksvc -n tenant-functions

# View orchestrator logs
kubectl logs -n faas-platform -l app=faas-platform-api -f

# View a specific function's logs
kubectl logs -n tenant-functions -l serving.knative.dev/service=my-function --prefix -f
```

---

## Access Points (Production)

- 🌐 **FaaS UI**: [http://134.122.61.206:30081](http://134.122.61.206:30081)
- 📚 **API Docs (Swagger)**: [http://134.122.61.206:30081/docs](http://134.122.61.206:30081/docs)
- 🛡️ **Health JSON**: [http://134.122.61.206:30081/health](http://134.122.61.206:30081/health)
