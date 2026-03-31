#!/usr/bin/env bash
# Create or update the Kubernetes secret used by nginx ingress basic auth for docs.
# Alternative: set ingress.basicAuth.password in Helm values (chart 0.1.2+) to create the same secret on install.
# Requires: kubectl, htpasswd (apache2-utils / httpd-tools).
#
# Usage:
#   DOCS_AUTH_USER=admin DOCS_AUTH_PASSWORD='your-pass' ./create-docs-basic-auth-secret.sh
# Or interactively (password prompt):
#   ./create-docs-basic-auth-secret.sh
set -euo pipefail

NS="${DOCS_NAMESPACE:-docs}"
SECRET="${DOCS_AUTH_SECRET_NAME:-docs-basic-auth}"
USER="${DOCS_AUTH_USER:-docs}"

if ! command -v kubectl &>/dev/null; then
  echo "kubectl not found" >&2
  exit 1
fi
if ! command -v htpasswd &>/dev/null; then
  echo "htpasswd not found. Install apache2-utils (Debian/Ubuntu) or httpd-tools (RHEL/Fedora/macOS brew install httpd)." >&2
  exit 1
fi

PASS="${DOCS_AUTH_PASSWORD:-}"
if [[ -z "$PASS" ]]; then
  read -r -s -p "Password for user '${USER}' (namespace ${NS}): " PASS
  echo
fi
if [[ -z "$PASS" ]]; then
  echo "Password required." >&2
  exit 1
fi

htpasswd -nbB "$USER" "$PASS" \
  | kubectl create secret generic "$SECRET" -n "$NS" \
    --from-file=auth=/dev/stdin \
    --dry-run=client -o yaml \
  | kubectl apply -f -

echo "Applied secret ${SECRET} in namespace ${NS} (user: ${USER})."
