#!/bin/sh
# Reopen Zeebe indices and normalize variable fields before indexing.
# A closed index hides every process in Operate. A value whose type does not
# match the existing mapping makes the exporter reject the whole bulk and retry forever.
set -u
es=http://infra-elasticsearch.infra.svc.cluster.local:9200
fail=0

echo "===== elasticsearch"
curl -sS -m 20 "$es" | head -c 400 || fail=1
echo

echo "===== pipeline"
curl -sS -m 30 -X PUT "$es/_ingest/pipeline/zeebe-drop-scalar-fineract-body" \
  -H "Content-Type: application/json" \
  -d '{"description":"Text amount indices: drop a scalar fineract body and store a map amount as its inner value","processors":[{"script":{"lang":"painless","source":"if (ctx.value instanceof java.util.Map && ctx.value.variables instanceof java.util.Map) { if (ctx.value.variables.fineractResponseBody != null && !(ctx.value.variables.fineractResponseBody instanceof java.util.Map)) { ctx.value.variables.remove(\"fineractResponseBody\"); } if (ctx.value.variables.amount instanceof java.util.Map) { def inner = ctx.value.variables.amount.amount; ctx.value.variables.amount = inner == null ? null : inner.toString(); if (ctx.value.variables.amount == null) { ctx.value.variables.remove(\"amount\"); } } }"}}]}' \
  || fail=1
echo
curl -sS -m 30 -X PUT "$es/_ingest/pipeline/zeebe-keep-amount-object" \
  -H "Content-Type: application/json" \
  -d '{"description":"Object amount indices: drop a scalar fineract body and a scalar amount","processors":[{"script":{"lang":"painless","source":"if (ctx.value instanceof java.util.Map && ctx.value.variables instanceof java.util.Map) { if (ctx.value.variables.fineractResponseBody != null && !(ctx.value.variables.fineractResponseBody instanceof java.util.Map)) { ctx.value.variables.remove(\"fineractResponseBody\"); } if (ctx.value.variables.amount != null && !(ctx.value.variables.amount instanceof java.util.Map)) { ctx.value.variables.remove(\"amount\"); } }"}}]}' \
  || fail=1
echo

echo "===== template priority"
curl -sS -m 20 "$es/_index_template/zeebe-record" | head -c 500 || true
echo
curl -sS -m 30 -X PUT "$es/_index_template/zeebe-record-fineract-fix" \
  -H "Content-Type: application/json" \
  -d '{"index_patterns":["zeebe-record*"],"priority":300,"template":{"settings":{"index.default_pipeline":"zeebe-drop-scalar-fineract-body"}}}' \
  || fail=1
echo

echo "===== indices before"
curl -sS -m 30 "$es/_cat/indices?h=status,index&expand_wildcards=all&s=index" | grep -E 'zeebe-record|operate-' || true

: > /tmp/repair-fail
curl -sS -m 30 "$es/_cat/indices?h=status,index&expand_wildcards=all" | grep -E 'zeebe-record|operate-' | while read -r status idx; do
  [ -n "$idx" ] || continue
  if [ "$status" = "close" ]; then
    echo "open $idx"
    curl -sS -m 30 -X POST "$es/$idx/_open" || echo "open $idx" >> /tmp/repair-fail
    echo
  fi
  case "$idx" in
    zeebe-record*)
      echo "pipeline $idx"
      curl -sS -m 30 -X PUT "$es/$idx/_settings" \
        -H "Content-Type: application/json" \
        -d '{"index.default_pipeline":"zeebe-drop-scalar-fineract-body"}' \
        || echo "pipeline $idx" >> /tmp/repair-fail
      echo
      ;;
  esac
done
echo "===== amount object indices"
curl -sS -m 30 "$es/_cat/indices?h=index&expand_wildcards=open" | grep '^zeebe-record' | while read -r idx; do
  [ -n "$idx" ] || continue
  mapping=$(curl -sS -m 20 "$es/$idx/_mapping")
  case "$mapping" in
    *'"amount":{"properties":{"amount"'*)
      echo "object pipeline $idx"
      curl -sS -m 30 -X PUT "$es/$idx/_settings" \
        -H "Content-Type: application/json" \
        -d '{"index.default_pipeline":"zeebe-keep-amount-object"}' \
        || echo "object pipeline $idx" >> /tmp/repair-fail
      echo
      ;;
  esac
done
if [ -s /tmp/repair-fail ]; then
  echo "===== failures"
  cat /tmp/repair-fail
  fail=1
fi

echo "===== still closed"
closed=$(curl -sS -m 30 "$es/_cat/indices?h=status,index&expand_wildcards=all" | awk '$1=="close" && $2 ~ /^(zeebe-record|operate-)/ { print }')
if [ -n "$closed" ]; then
  echo "$closed"
  fail=1
else
  echo none
fi

echo "===== operate aliases"
# Operate 8.2 reads alias zeebe-record-<type>. This broker writes zeebe-record_<type>_8.2.12_<date>.
for pair in \
  "process:zeebe-record_process_*" \
  "process-instance:zeebe-record_process-instance_*" \
  "job:zeebe-record_job_*" \
  "variable:zeebe-record_variable_*" \
  "incident:zeebe-record_incident_*" \
  "variable-document:zeebe-record_variable-document_*" \
  "decision:zeebe-record_decision_*" \
  "decision-requirements:zeebe-record_decision-requirements_*" \
  "decision-evaluation:zeebe-record_decision-evaluation_*" \
  "process-message-subscription:zeebe-record_process-message-subscription_*" \
  "deployment:zeebe-record_deployment_*"
do
  type=${pair%%:*}
  pattern=${pair#*:}
  alias="zeebe-record-${type}"
  echo -n "template $alias "
  curl -sS -m 20 -X PUT "$es/_index_template/operate-alias-${type}" \
    -H "Content-Type: application/json" \
    -d "{\"index_patterns\":[\"${pattern}\"],\"priority\":310,\"template\":{\"aliases\":{\"${alias}\":{}}}}" \
    || echo "template $alias" >> /tmp/repair-fail
  echo
  echo -n "alias $alias "
  curl -sS -m 20 -X POST "$es/_aliases" -H "Content-Type: application/json" \
    -d "{\"actions\":[{\"add\":{\"index\":\"${pattern}\",\"alias\":\"${alias}\"}}]}" \
    || echo "alias $alias" >> /tmp/repair-fail
  echo
done

echo "===== counts"
curl -sS -m 20 "$es/zeebe-record_process_*/_count?expand_wildcards=all" || true
echo
curl -sS -m 20 "$es/zeebe-record_deployment_*/_count?expand_wildcards=all" || true
echo
exit "$fail"
