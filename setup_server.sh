#!/bin/bash
set -e

echo "🚀 VakıfBank FaaS Platform - Otomatik Kurulum Betiği"
echo "Bu betik sıfır bir Ubuntu sunucusunu tam teşekküllü bir Serverless platformuna dönüştürür."
echo "----------------------------------------------------------------------------------"

# 1. MicroK8s (Kubernetes) Kurulumu 
echo "📦 1/5 MicroK8s Kuruluyor..."
sudo snap install microk8s --classic --channel=1.30/stable
sudo microk8s enable dns ingress registry rbac
sudo alias kubectl='microk8s kubectl'
echo "alias kubectl='microk8s kubectl'" >> ~/.bashrc
source ~/.bashrc

# 2. Knative ve Kourier Kurulumu
echo "🦄 2/5 Knative Serving Kuruluyor..."
kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.0/serving-crds.yaml
kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.14.0/serving-core.yaml

echo "🕸️ Kourier Ingress (Ağ Yönlendirici) Kuruluyor..."
kubectl apply -f https://github.com/knative/net-kourier/releases/download/knative-v1.14.0/kourier.yaml
kubectl patch configmap/config-network -n knative-serving \
  --type merge --patch '{"data":{"ingress-class":"kourier.ingress.networking.knative.dev"}}'

# 3. Knative Func CLI Kurulumu
echo "🛠️ 3/5 Knative Func CLI İndiriliyor..."
FUNC_VERSION=$(curl -sSL https://api.github.com/repos/knative/func/releases/latest | grep tag_name | sed -E 's/.*"([^"]+)".*/\1/')
curl -sSL "https://github.com/knative/func/releases/download/${FUNC_VERSION}/func_linux_amd64" \
  -o /usr/local/bin/func && chmod +x /usr/local/bin/func

# 4. Pack CLI (Konteyner İnşa Edici) Kurulumu
echo "🧰 4/5 Buildpacks (Pack CLI) Kuruluyor..."
sudo add-apt-repository -y ppa:cncf-buildpacks/pack-cli
sudo apt-get update
sudo apt-get install -y pack-cli

# 5. Projenin Canlıya Alınması (Deploy)
echo "🌐 5/5 FaaS Platformu Başlatılıyor..."
# Projeyi GitHub'dan çek (Örnek)
# git clone https://github.com/SİZİN_KULLANICI_ADINIZ/Vakifbank-FaaS-Project.git
# cd Vakifbank-FaaS-Project

# Kubernetes manifestlerini uygula
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/deployment.yaml

echo "----------------------------------------------------------------------------------"
echo "✅ KURULUM TAMAMLANDI! FaaS Platformunuz Birkaç Dakika İçinde Hazır Olacak."
echo "Platforma http://<SUNUCU_IP>:30081 adresinden ulaşabilirsiniz."
