#!/usr/bin/env bash
# Local equivalent of .github/workflows/validate.yml
# Usage:
#   ./scripts/validate.sh              # validate only (kustomize build)
#   ./scripts/validate.sh --reconcile # validate + flux reconcile (requires KUBECONFIG)
#   ./scripts/validate.sh -r --prune   # reconcile + prune (delete resources no longer in Git)
#   ./scripts/validate.sh --delete      # delete all Flux Kustomizations and their resources (destructive)
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RECONCILE=false
PRUNE=false
DELETE=false
for arg in "$@"; do
  case "$arg" in
    -r|--reconcile) RECONCILE=true ;;
    -p|--prune)     PRUNE=true ;;
    -d|--delete)    DELETE=true ;;
    -h|--help)
      echo "Usage: $0 [--reconcile] [--prune] [--delete]"
      echo "  --reconcile, -r  After validate, run flux reconcile (requires flux CLI and KUBECONFIG)"
      echo "  --prune, -p      With --reconcile: force full reconcile so resources no longer in Git are deleted (Kustomizations must have spec.prune: true)"
      echo "  --delete, -d    Delete all Flux Kustomizations and their applied resources (destructive; requires kubectl and KUBECONFIG)"
      exit 0
      ;;
  esac
done

if $DELETE; then
  if ! command -v kubectl &>/dev/null; then
    echo "kubectl not found. Install kubectl to use --delete."
    exit 1
  fi
  echo "==> DELETE: Remove all Flux Kustomizations and their resources (prune)."
  echo "    This will delete resources in: kong, kyc, app, apis, core-banking, iam, infra, platform, ingress-nginx, cert-manager, sources, and flux-system."
  read -r -p "Type 'yes' to continue: " confirm
  if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
  fi
  # Reverse order: delete leaf Kustomizations first, then roots
  DEL_KUSTOMIZATIONS=(
    kong kyc app apis core-banking iam infra platform
    ingress-nginx cert-manager-issuers cert-manager
    sources flux-system
  )
  for name in "${DEL_KUSTOMIZATIONS[@]}"; do
    echo "Deleting Kustomization — $name"
    kubectl delete kustomization "$name" -n flux-system --timeout=60s --ignore-not-found=true 2>/dev/null || true
  done
  echo ""
  echo "Done. Kustomizations and their resources (where prune was true) have been removed."
  exit 0
fi

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
  echo "Done. Use --reconcile to run flux reconcile. Use --prune to delete resources no longer in Git. Use --delete to remove all Kustomizations and their resources."
  exit 0
fi

# Reconcile (requires flux + kubeconfig)
if ! command -v flux &>/dev/null; then
  echo "flux CLI not found. Install: curl -sSL https://fluxcd.io/install.sh | bash"
  exit 1
fi
if ! kubectl get namespace flux-system &>/dev/null; then
  echo "Namespace flux-system not found. Flux is not installed on this cluster."
  echo "Bootstrap with: flux bootstrap git --url=<repo> --branch=<branch> --path=clusters/dev"
  exit 0
fi

echo "==> Reconciling Flux..."
if $PRUNE; then
  echo "Prune enabled: resources no longer in Git will be deleted."
fi
echo "Reconciling source git flux-system..."
if ! flux reconcile source git flux-system -n flux-system 2>/dev/null; then
  echo "GitRepository flux-system not found. Re-create with:"
  echo "  kubectl apply -f clusters/dev/flux-system/gotk-sync.yaml"
  echo "  See docs/flux-recreate-source.md for details."
  exit 0
fi
echo "Reconciling kustomization flux-system (may take 1–2 min)..."
flux reconcile kustomization flux-system -n flux-system --timeout=2m $($PRUNE && echo --force) || true

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
)

for name in "${KUSTOMIZATIONS[@]}"; do
  echo "Reconcile Kustomization — $name"
  flux reconcile kustomization "$name" -n flux-system --timeout=3m $($PRUNE && echo --force) || true
done

for ns in iam core-banking api app kyc infra payment-hub; do
  echo "Reconcile HelmReleases — $ns"
  kubectl get helmreleases.helm.toolkit.fluxcd.io -n "$ns" --no-headers -o custom-columns="NAME:.metadata.name" 2>/dev/null | while read -r name; do
    [ -z "$name" ] && continue
    flux reconcile helmrelease "$name" -n "$ns" --timeout=3m || true
  done
done

echo ""
echo "Done."
