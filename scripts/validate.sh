#!/usr/bin/env bash
# Local equivalent of .github/workflows/validate.yml (kustomize build).
# Reconcile: use scripts/reconcile.sh <app> or scripts/reconcile.sh all.
# Usage:
#   ./scripts/validate.sh                    # validate only (kustomize build)
#   ./scripts/validate.sh --reconcile         # validate then reconcile all (requires KUBECONFIG)
#   ./scripts/validate.sh --reconcile --app=api
#   ./scripts/reconcile.sh api                # reconcile one app only
#   ./scripts/reconcile.sh all                # reconcile all apps
#   ./scripts/validate.sh --delete            # delete all Flux Kustomizations (destructive)
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RECONCILE=false
RECONCILE_APP=""
PRUNE=false
DELETE=false
for arg in "$@"; do
  case "$arg" in
    -r|--reconcile) RECONCILE=true ;;
    -p|--prune)     PRUNE=true ;;
    -d|--delete)    DELETE=true ;;
    --app=*)        RECONCILE_APP="${arg#--app=}" ;;
    -h|--help)
      echo "Usage: $0 [--reconcile] [--app=NAME] [--prune] [--delete]"
      echo "  --reconcile, -r   After validate, run flux reconcile (requires flux CLI and KUBECONFIG)"
      echo "  --app=NAME        With --reconcile: only reconcile this app (sources, api, app, kyc, ...). Default: all"
      echo "  --prune, -p       With --reconcile: pass --force to flux reconcile"
      echo "  --delete, -d     Delete all Flux Kustomizations and their applied resources (destructive)"
      echo "Reconcile one app: ./scripts/reconcile.sh <app>"
      echo "Reconcile all:     ./scripts/reconcile.sh all"
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
  echo "    This will delete resources in: kong, kyc, app, apis, core-banking, iam, infra, platform, docs, ingress-nginx, cert-manager, sources, flux-system, and EU stack (infra-eu, core-banking-eu, payment-hub-eu, api-eu, kyc-eu)."
  read -r -p "Type 'yes' to continue: " confirm
  if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
  fi
  DEL_KUSTOMIZATIONS=(
    kong kong-routes kyc app apis core-banking iam infra platform docs
    ingress-nginx cert-manager-issuers cert-manager
    sources flux-system
    infra-eu core-banking-eu payment-hub-eu api-eu kyc-eu
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

# Cluster config (must match .github/workflows/validate.yml)
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
  apps/kong/install
  apps/kong/overlay
  apps/overlays/dev/01-platform
  apps/overlays/dev/06-infra
  apps/overlays/dev/02-identity
  apps/overlays/dev/03-core
  apps/overlays/dev/04-apis
  apps/overlays/dev/05-app
  apps/docs/overlays/dev
  apps/overlays/staging
  apps/overlays/production
  # EU stack
  apps/infra-eu/overlays/dev
  apps/core-banking-eu/overlays/dev
  apps/payment-hub-eu/overlays/dev
  apps/api-eu/overlays/dev
  apps/kyc-eu/overlays/dev
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
  echo "Done. To reconcile: ./scripts/reconcile.sh <app> or ./scripts/reconcile.sh all"
  echo "  Or: $0 --reconcile [--app=api]"
  exit 0
fi

# Reconcile: delegate to reconcile.sh
if ! command -v flux &>/dev/null; then
  echo "flux CLI not found. Install: curl -sSL https://fluxcd.io/install.sh | bash"
  exit 1
fi
if ! kubectl get namespace flux-system &>/dev/null; then
  echo "Namespace flux-system not found. Flux is not installed on this cluster."
  exit 0
fi

RECONCILE_ARGS=()
$PRUNE && RECONCILE_ARGS+=(--force)

if [ -n "$RECONCILE_APP" ]; then
  "$REPO_ROOT/scripts/reconcile.sh" "$RECONCILE_APP" "${RECONCILE_ARGS[@]}"
else
  "$REPO_ROOT/scripts/reconcile.sh" all "${RECONCILE_ARGS[@]}"
fi
