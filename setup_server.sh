#!/bin/bash
# ============================================================
#  Vakifbank-FaaS-Project/setup_server.sh
#  Fresh-droplet prerequisites for the FaaS Platform
#
#  This script installs ONLY what .github/workflows/deploy.yml assumes is
#  already on the box when it SSHes in: Docker, Minikube, kubectl, git, ufw.
#  Everything else — Knative, Kourier, cert-manager, ingress-nginx, the
#  faas-platform/tenant-functions namespaces, Redis, the ResourceQuota/
#  LimitRange, TLS Ingress/Certificates, and the application itself — is
#  installed and kept up to date by that CD pipeline on every push to main,
#  idempotently. Duplicating any of that here would just be a second, harder
#  -to-keep-in-sync copy of the same logic, so this script deliberately
#  doesn't try. Run it once on a brand-new Ubuntu server, then let GitHub
#  Actions do the rest.
# ============================================================
set -e

echo "🚀 VakıfBank FaaS Platform — Sunucu Ön Koşulları"
echo "Bu betik sadece CD pipeline'ın (deploy.yml) ihtiyaç duyduğu temel"
echo "araçları kurar: Docker, kubectl, Minikube, git, ufw. Kubernetes/"
echo "Knative/cert-manager kurulumu ve uygulamanın kendisi GitHub Actions"
echo "tarafından otomatik yapılır — bu betiğin işi burada biter."
echo "----------------------------------------------------------------------------------"

# 1. Docker
if ! command -v docker &>/dev/null; then
  echo "🐳 1/5 Docker kuruluyor..."
  curl -fsSL https://get.docker.com | sh
else
  echo "🐳 1/5 Docker zaten kurulu, atlanıyor."
fi

# 2. kubectl
if ! command -v kubectl &>/dev/null; then
  echo "☸️  2/5 kubectl kuruluyor..."
  KUBECTL_VERSION=$(curl -sSL https://dl.k8s.io/release/stable.txt)
  curl -sSLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
  chmod +x kubectl && mv kubectl /usr/local/bin/
else
  echo "☸️  2/5 kubectl zaten kurulu, atlanıyor."
fi

# 3. Minikube — deploy.yml `minikube start --driver=docker` ile kendi
#    kendini ayağa kaldırıyor, burada sadece binary'nin var olması yeterli.
if ! command -v minikube &>/dev/null; then
  echo "📦 3/5 Minikube kuruluyor..."
  curl -sSLo minikube https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
  chmod +x minikube && mv minikube /usr/local/bin/
else
  echo "📦 3/5 Minikube zaten kurulu, atlanıyor."
fi

# 4. git — deploy.yml repoyu droplet üzerinde clone/pull ediyor
if ! command -v git &>/dev/null; then
  echo "🔧 4/5 git kuruluyor..."
  apt-get update -y && apt-get install -y git
else
  echo "🔧 4/5 git zaten kurulu, atlanıyor."
fi

# 5. ufw — deploy.yml portları (30081, 80, 443) burada açıyor, paket kurulu
#    olmalı; etkinleştirmeyi/kuralları CD pipeline'a bırakıyoruz.
if ! command -v ufw &>/dev/null; then
  echo "🛡️  5/5 ufw kuruluyor..."
  apt-get update -y && apt-get install -y ufw
else
  echo "🛡️  5/5 ufw zaten kurulu, atlanıyor."
fi

echo "----------------------------------------------------------------------------------"
echo "✅ ÖN KOŞULLAR HAZIR."
echo ""
echo "Sıradaki adımlar:"
echo "  1) Bu repo'yu fork ettiyseniz, GitHub'da Settings → Secrets and"
echo "     variables → Actions altında şu secret'ları tanımlayın:"
echo "       DOCKER_HUB_USER, DOCKER_HUB_USERNAME, DOCKER_HUB_TOKEN"
echo "       DO_DROPLET_IP        (bu sunucunun genel IP'si)"
echo "       DO_SSH_USER, DO_SSH_KEY"
echo "       LETSENCRYPT_EMAIL    (Let's Encrypt bildirimleri için gerçek bir e-posta)"
echo "  2) main branch'e push edin (veya Actions sekmesinden workflow'u elle"
echo "     tetikleyin) — geri kalan her şeyi .github/workflows/deploy.yml"
echo "     otomatik kurar ve deploy eder."
echo "----------------------------------------------------------------------------------"
