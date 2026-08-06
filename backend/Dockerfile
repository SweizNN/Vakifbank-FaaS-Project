# ============================================================
#  Vakifbank-FaaS-Project/backend/Dockerfile
#  Multi-stage build for the FastAPI FaaS Orchestrator
#
#  The final image includes:
#  - Python 3.11 (slim)
#  - kubectl (latest stable)
#  - Knative func CLI (latest stable)
#  - docker CLI (for Buildpack push auth)
# ============================================================

# ── Stage 1: Python dependency builder ───────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY backend/requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Final runtime image ──────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Install system tools needed at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    apt-transport-https \
    gnupg \
    lsb-release \
    && rm -rf /var/lib/apt/lists/*

# ── Install kubectl ────────────────────────────────────────────────────────────
RUN KUBECTL_VERSION=$(curl -sSL https://dl.k8s.io/release/stable.txt) && \
    curl -sSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
         -o /usr/local/bin/kubectl && \
    chmod +x /usr/local/bin/kubectl

# ── Install Knative func CLI ───────────────────────────────────────────────────
RUN FUNC_VERSION=$(curl -sSL https://api.github.com/repos/knative/func/releases/latest \
      | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/') && \
    curl -sSL "https://github.com/knative/func/releases/download/${FUNC_VERSION}/func_linux_amd64" \
         -o /usr/local/bin/func && \
    chmod +x /usr/local/bin/func

# ── Install Docker CLI (for registry auth) ─────────────────────────────────────
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | \
    gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
      https://download.docker.com/linux/debian $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list && \
    apt-get update && apt-get install -y --no-install-recommends docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

# ── Copy Python packages from builder ─────────────────────────────────────────
COPY --from=builder /install /usr/local

# ── Copy application code ──────────────────────────────────────────────────────
# Copy everything into /app, then set WORKDIR to /app/backend.
# This mirrors local dev (running uvicorn from the backend/ directory)
# so 'from config import ...' resolves identically in both environments.
WORKDIR /app
COPY backend/ ./backend/
COPY frontend/ ./frontend/
WORKDIR /app/backend

# ── Non-root user ─────────────────────────────────────────────────────────────
RUN useradd -m -u 1001 faas && \
    mkdir -p /tmp/faas-workspace && \
    chown -R faas:faas /app /tmp/faas-workspace
USER faas

# ── Health check ──────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ── Runtime ───────────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Run from /app/backend — matches the local dev command exactly:
#   cd backend && uvicorn main:app --reload
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
