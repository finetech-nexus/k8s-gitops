#!/usr/bin/env bash
# Create a JKS truststore containing the internal CA (nbank-dev issuer) and create/update
# the Secret keystore-truststore in namespace iam so Keycloak trusts TLS certs signed by that CA.
# Fixes: PKIX path building failed / unable to find valid certification path to requested target
#
# Prereqs: keytool (JDK), kubectl, cluster access. The secret cert-manager/internal-ca-keypair
# must exist (ClusterIssuer nbank-dev uses it).
#
# Usage:
#   ./scripts/create-iam-truststore-from-internal-ca.sh
#   ./scripts/create-iam-truststore-from-internal-ca.sh --namespace iam --secret-name keystore-truststore
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${SCRIPT_DIR}/ca"
TRUSTSTORE_JKS="${OUT_DIR}/truststore.jks"
TRUSTSTORE_PASSWORD="${TRUSTSTORE_PASSWORD:-password}"
NAMESPACE="iam"
SECRET_NAME="keystore-truststore"
CERT_MANAGER_SECRET="internal-ca-keypair"
CERT_MANAGER_NS="cert-manager"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    --secret-name)
      SECRET_NAME="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [--namespace iam] [--secret-name keystore-truststore]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if ! command -v keytool >/dev/null 2>&1; then
  echo "keytool is required (install a JDK)." >&2
  exit 1
fi
if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required." >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

echo "Fetching CA cert from ${CERT_MANAGER_NS}/${CERT_MANAGER_SECRET}..."
kubectl get secret "$CERT_MANAGER_SECRET" -n "$CERT_MANAGER_NS" -o jsonpath='{.data.tls\.crt}' | base64 -d > "${OUT_DIR}/internal-ca.crt"

if [[ ! -s "${OUT_DIR}/internal-ca.crt" ]]; then
  echo "Failed to get CA cert. Is the secret ${CERT_MANAGER_NS}/${CERT_MANAGER_SECRET} present?" >&2
  exit 1
fi

echo "Creating JKS truststore at ${TRUSTSTORE_JKS}..."
rm -f "$TRUSTSTORE_JKS"
keytool -importcert -alias internal-ca -file "${OUT_DIR}/internal-ca.crt" \
  -keystore "$TRUSTSTORE_JKS" -storepass "$TRUSTSTORE_PASSWORD" -noprompt

echo "Creating/updating Secret ${NAMESPACE}/${SECRET_NAME}..."
kubectl create secret generic "$SECRET_NAME" -n "$NAMESPACE" \
  --from-file=truststore.jks="$TRUSTSTORE_JKS" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Done. Restart Keycloak so it picks up the new truststore:"
echo "  kubectl rollout restart statefulset keycloak -n iam"
echo "  kubectl rollout status statefulset keycloak -n iam"
