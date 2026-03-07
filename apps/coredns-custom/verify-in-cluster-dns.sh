#!/usr/bin/env bash
# Verify in-cluster DNS for *.dev.sandbox.internal.nbank.fr (coredns-custom).
# Run from your machine (kubectl + cluster access). No args needed.

set -e
echo "=== 1. ConfigMap coredns-custom in kube-system ==="
kubectl get configmap coredns-custom -n kube-system -o yaml 2>/dev/null || { echo "FAIL: ConfigMap coredns-custom not found. Apply apps/coredns-custom (e.g. flux reconcile kustomization coredns-custom -n flux-system)"; exit 1; }
echo ""

echo "=== 2. CoreDNS workload (must restart after ConfigMap change) ==="
kubectl get deployment,daemonset -n kube-system -l k8s-app=kube-dns 2>/dev/null || kubectl get deployment,daemonset -n kube-system | grep -i coredns || true
echo "  -> If you changed the ConfigMap, run: kubectl rollout restart deployment -n kube-system coredns"
echo "     (or: kubectl rollout restart daemonset -n kube-system coredns)"
echo ""

echo "=== 3. Is this k3s? (coredns-custom is only loaded by k3s) ==="
kubectl get nodes -o wide 2>/dev/null | head -3
if kubectl get configmap coredns -n kube-system -o yaml 2>/dev/null | grep -q "import.*custom"; then
  echo "  -> Corefile imports custom: OK"
else
  echo "  -> WARNING: Corefile may not import coredns-custom. If this is not k3s, coredns-custom is ignored."
fi
echo ""

echo "=== 4. DNS resolution from a test pod (iam.dev.sandbox.internal.nbank.fr) ==="
echo "  Running: kubectl run dns-test --rm -i --restart=Never --image=busybox:1.36 -- nslookup iam.dev.sandbox.internal.nbank.fr"
if kubectl run dns-test --rm -i --restart=Never --image=busybox:1.36 -- nslookup iam.dev.sandbox.internal.nbank.fr 2>&1; then
  echo "  -> Resolution OK"
else
  echo "  -> Resolution FAILED. Check: (1) ConfigMap applied, (2) CoreDNS restarted, (3) cluster is k3s."
fi
echo ""

echo "=== 5. Keycloak service exists (target of rewrite) ==="
kubectl get svc keycloak -n iam 2>/dev/null || echo "  -> keycloak.iam service not found (wrong namespace or name?)"
echo ""
echo "Done. If nslookup failed, fix the steps above then restart CoreDNS and retry."
