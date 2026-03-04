#!/usr/bin/env bash
# Local equivalent of .github/workflows/validate.yml
# Usage:
#   ./scripts/validate.sh           # validate only (kustomize build)
#   ./scripts/validate.sh --reconcile  # validate + flux reconcile (requires KUBECONFIG)
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RECONCILE=false
for arg in "$@"; do
  case "$arg" in
    -r|--reconcile) RECONCILE=true ;;
    -h|--help)
      echo "Usage: $0 [--reconcile]"
      echo "  --reconcile, -r  After validate, run flux reconcile (requires flux CLI and KUBECONFIG)"
      exit 0
      ;;
  esac
done

echo "==> Validating (kustomize build)..."
echo ""

# Cluster config
echo "Building clusters/dev..."
kustomize build clusters/dev >/dev/null
echo "  OK"
echo ""

# App paths (must match validate.yml)
PATHS=(
  apps/sources
  apps/cert-manager-install
  apps/cert-manager
  apps/ingress-nginx
  apps/kong
  apps/monitoring
  apps/overlays/dev/01-platform
  apps/overlays/dev/06-infra
  apps/overlays/dev/02-identity
  apps/overlays/dev/03-core
  apps/overlays/dev/04-apis
  apps/overlays/dev/05-app
  apps/overlays/staging
  apps/overlays/production
)

for path in "${PATHS[@]}"; do
  echo "Building $path..."
  kustomize build "$path" >/dev/null
  echo "  OK"
done

echo ""
echo "All kustomize builds succeeded."
echo ""

if ! $RECONCILE; then
  echo "Done. Use --reconcile to run flux reconcile against the cluster."
  exit 0
fi

# Reconcile (requires flux + kubeconfig)
if ! command -v flux &>/dev/null; then
  echo "flux CLI not found. Install: curl -sSL https://fluxcd.io/install.sh | bash"
  exit 1
fi

echo "==> Reconciling Flux..."
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization flux-system -n flux-system --timeout=5m

for name in platform; do
  flux resume kustomization "$name" -n flux-system 2>/dev/null || true
done

KUSTOMIZATIONS=(
  sources
  cert-manager
  cert-manager-issuers
  ingress-nginx
  platform
  infra
  iam
  core-banking
  apis
  app
  kyc
  kong
  monitoring
)

for name in "${KUSTOMIZATIONS[@]}"; do
  echo "Reconcile Kustomization — $name"
  flux reconcile kustomization "$name" -n flux-system --timeout=3m || true
done

for ns in iam core-banking api app kyc monitoring infra payment-hub; do
  echo "Reconcile HelmReleases — $ns"
  kubectl get helmreleases.helm.toolkit.fluxcd.io -n "$ns" --no-headers -o custom-columns="NAME:.metadata.name" 2>/dev/null | while read -r name; do
    [ -z "$name" ] && continue
    flux reconcile helmrelease "$name" -n "$ns" --timeout=3m || true
  done
done

echo ""
echo "Done."
