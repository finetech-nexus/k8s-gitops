#!/usr/bin/env bash
# Reconcile one app or all apps. Requires flux CLI and KUBECONFIG.
# Usage:
#   ./scripts/reconcile.sh sources
#   ./scripts/reconcile.sh api
#   ./scripts/reconcile.sh app
#   ./scripts/reconcile.sh all
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

APP="${1:-}"
shift 2>/dev/null || true
EXTRA_ARGS=("$@")

if [ -z "$APP" ] || [ "$APP" = "-h" ] || [ "$APP" = "--help" ]; then
  echo "Usage: $0 <app> [--force]"
  echo "  app: flux-system | sources | cert-manager | ingress-nginx | platform | infra | iam | core-banking | api | app | kyc | kong | payment-hub | all"
  exit 0
fi

if ! command -v flux &>/dev/null; then
  echo "flux CLI not found. Install: curl -sSL https://fluxcd.io/install.sh | bash"
  exit 1
fi
if ! kubectl get namespace flux-system &>/dev/null; then
  echo "Namespace flux-system not found. Flux is not installed on this cluster."
  exit 1
fi

reconcile_sources() {
  flux reconcile source git flux-system -n flux-system --timeout=15s || true
  flux reconcile kustomization flux-system -n flux-system --timeout=2m "$@" || true
  flux resume kustomization platform -n flux-system 2>/dev/null || true
  flux reconcile kustomization sources -n flux-system --timeout=3m "$@" || true
}

reconcile_cert_manager() {
  flux reconcile kustomization cert-manager -n flux-system --timeout=3m "$@" || true
  flux reconcile kustomization cert-manager-issuers -n flux-system --timeout=3m "$@" || true
}

reconcile_kustomization() {
  local name="$1"
  shift
  flux reconcile kustomization "$name" -n flux-system --timeout=3m "$@" || true
}

reconcile_helmreleases() {
  local ns="$1"
  shift
  local timeout="3m"
  if [ -n "${1:-}" ] && [[ "$1" =~ ^[0-9]+[ms]$ ]]; then timeout="$1"; shift; fi
  kubectl get helmreleases.helm.toolkit.fluxcd.io -n "$ns" --no-headers -o 'custom-columns=NAME:.metadata.name' 2>/dev/null | while read -r name; do
    [ -z "$name" ] && continue
    flux reconcile helmrelease "$name" -n "$ns" --timeout="$timeout" "$@" || true
  done
}

case "$APP" in
  flux-system)
    echo "==> Reconcile - flux-system (source git + root kustomization)"
    flux reconcile source git flux-system -n flux-system --timeout=15s || true
    flux reconcile kustomization flux-system -n flux-system --timeout=5m "${EXTRA_ARGS[@]}" || true
    ;;
  sources)
    echo "==> Reconcile - sources"
    reconcile_sources "${EXTRA_ARGS[@]}"
    ;;
  cert-manager)
    echo "==> Reconcile - cert-manager"
    reconcile_cert_manager "${EXTRA_ARGS[@]}"
    ;;
  ingress-nginx)
    echo "==> Reconcile - ingress-nginx"
    reconcile_kustomization ingress-nginx "${EXTRA_ARGS[@]}"
    ;;
  platform)
    echo "==> Reconcile - platform"
    flux resume kustomization platform -n flux-system 2>/dev/null || true
    reconcile_kustomization platform "${EXTRA_ARGS[@]}"
    ;;
  infra)
    echo "==> Reconcile - infra"
    reconcile_kustomization infra "${EXTRA_ARGS[@]}"
    reconcile_helmreleases infra "${EXTRA_ARGS[@]}"
    ;;
  iam)
    echo "==> Reconcile - iam"
    reconcile_kustomization iam "${EXTRA_ARGS[@]}"
    reconcile_helmreleases iam "${EXTRA_ARGS[@]}"
    ;;
  core-banking)
    echo "==> Reconcile - core-banking"
    reconcile_kustomization core-banking "${EXTRA_ARGS[@]}"
    reconcile_helmreleases core-banking "${EXTRA_ARGS[@]}"
    ;;
  api)
    echo "==> Reconcile - api"
    reconcile_kustomization apis "${EXTRA_ARGS[@]}"
    reconcile_helmreleases api "${EXTRA_ARGS[@]}"
    ;;
  app)
    echo "==> Reconcile - app"
    reconcile_kustomization app "${EXTRA_ARGS[@]}"
    reconcile_helmreleases app "${EXTRA_ARGS[@]}"
    ;;
  kyc)
    echo "==> Reconcile - kyc"
    reconcile_kustomization kyc "${EXTRA_ARGS[@]}"
    reconcile_helmreleases kyc "${EXTRA_ARGS[@]}"
    ;;
  kong)
    echo "==> Reconcile - kong"
    reconcile_kustomization kong --timeout=5m "${EXTRA_ARGS[@]}"
    reconcile_kustomization kong-routes "${EXTRA_ARGS[@]}"
    reconcile_helmreleases apim "${EXTRA_ARGS[@]}"
    ;;
  payment-hub)
    echo "==> Reconcile - payment-hub (Kustomization + HelmRelease; may take 10-15 min)"
    reconcile_kustomization payment-hub "${EXTRA_ARGS[@]}"
    reconcile_helmreleases payment-hub 15m "${EXTRA_ARGS[@]}"
    ;;
  all)
    echo "==> Reconcile all apps"
    for a in flux-system sources cert-manager ingress-nginx platform infra iam core-banking api app kyc kong payment-hub; do
      "$REPO_ROOT/scripts/reconcile.sh" "$a" "${EXTRA_ARGS[@]}" || true
    done
    echo "Done."
    exit 0
    ;;
  *)
    echo "Unknown app: $APP"
    echo "  Valid: flux-system, sources, cert-manager, ingress-nginx, platform, infra, iam, core-banking, api, app, kyc, kong, payment-hub, all"
    exit 1
    ;;
esac

echo "Done."
