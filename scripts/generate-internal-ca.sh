#!/usr/bin/env bash
set -euo pipefail

# Generate root CA cert from an existing root key, generate/sign an intermediate CA,
# and create/update cert-manager secret used by ClusterIssuer:
#   cert-manager/internal-ca-keypair
#
# Usage:
#   ./scripts/generate-internal-ca.sh
#   ./scripts/generate-internal-ca.sh --root-key /path/to/root.key --output-dir /path/to/ca
#
# Defaults:
#   --root-key ./scripts/ca/root.key
#   --output-dir ./scripts/ca
#   --namespace cert-manager
#   --secret-name internal-ca-keypair

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CA_DIR="$SCRIPT_DIR/ca"
ROOT_KEY="$CA_DIR/root.key"
OUT_DIR="$CA_DIR"
NAMESPACE="cert-manager"
SECRET_NAME="internal-ca-keypair"
ROOT_SUBJECT="/C=TN/ST=Tunis/L=Tunis/O=NexusBank Ltd/OU=IT/CN=NexusBank Root CA/emailAddress=amiladi@nbank.fr"
INT_SUBJECT="/C=TN/ST=Tunis/L=Tunis/O=NexusBank Ltd/OU=IT/CN=NexusBank Intermediate CA/emailAddress=amiladi@nbank.fr"
ROOT_DAYS=3650
INT_DAYS=1825

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root-key)
      ROOT_KEY="$2"
      shift 2
      ;;
    --out-dir|--output-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    --secret-name)
      SECRET_NAME="$2"
      shift 2
      ;;
    --root-subject)
      ROOT_SUBJECT="$2"
      shift 2
      ;;
    --int-subject)
      INT_SUBJECT="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [--root-key path] [--output-dir dir] [--namespace ns] [--secret-name name] [--root-subject subj] [--int-subject subj]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required." >&2
  exit 1
fi
if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required." >&2
  exit 1
fi
if [[ ! -f "$ROOT_KEY" ]]; then
  echo "Root key not found: $ROOT_KEY" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

ROOT_CRT="$OUT_DIR/root.cer"
ROOT_CSR="$OUT_DIR/root.csr"
INT_KEY="$OUT_DIR/intermediate.key"
INT_CSR="$OUT_DIR/intermediate.csr"
INT_CRT="$OUT_DIR/intermediate.cer"
CHAIN_CRT="$OUT_DIR/fullchain.crt"
ROOT_EXT="$OUT_DIR/root-ca.ext"
INT_EXT="$OUT_DIR/intermediate-ca.ext"

cat > "$ROOT_EXT" <<'EOF'
basicConstraints=critical,CA:TRUE,pathlen:1
keyUsage=critical,keyCertSign,cRLSign
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid:always,issuer
EOF

echo "Generating root CA certificate from root key..."
openssl req -new -sha256 -key "$ROOT_KEY" -out "$ROOT_CSR" -subj "$ROOT_SUBJECT"
openssl x509 -req -sha256 \
  -in "$ROOT_CSR" \
  -signkey "$ROOT_KEY" \
  -out "$ROOT_CRT" \
  -days "$ROOT_DAYS" \
  -extfile "$ROOT_EXT"

cat > "$INT_EXT" <<'EOF'
basicConstraints=critical,CA:TRUE,pathlen:0
keyUsage=critical,keyCertSign,cRLSign
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF

echo "Generating intermediate CA key/csr and signing with root CA..."
openssl genrsa -out "$INT_KEY" 4096
openssl req -new -sha256 -key "$INT_KEY" -out "$INT_CSR" -subj "$INT_SUBJECT"
openssl x509 -req -sha256 \
  -in "$INT_CSR" \
  -CA "$ROOT_CRT" \
  -CAkey "$ROOT_KEY" \
  -CAcreateserial \
  -out "$INT_CRT" \
  -days "$INT_DAYS" \
  -extfile "$INT_EXT"

cat "$INT_CRT" "$ROOT_CRT" > "$CHAIN_CRT"

echo "Creating/updating TLS secret: $SECRET_NAME in $NAMESPACE"
kubectl create secret tls "$SECRET_NAME" -n "$NAMESPACE" \
  --cert="$INT_CRT" \
  --key="$INT_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

echo
echo "Done."
echo "Generated files:"
echo "  Root cert:         $ROOT_CRT"
echo "  Root csr:          $ROOT_CSR"
echo "  Intermediate key:  $INT_KEY"
echo "  Intermediate csr:  $INT_CSR"
echo "  Intermediate cert: $INT_CRT"
echo "  Full chain:        $CHAIN_CRT"
echo
echo "Secret applied:"
echo "  $NAMESPACE/$SECRET_NAME"
echo
echo "Note: clients must trust root CA ($ROOT_CRT)."
