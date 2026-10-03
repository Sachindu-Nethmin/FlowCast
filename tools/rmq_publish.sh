#!/usr/bin/env bash
# rmq_publish.sh QUEUE PAYLOAD
#
# Publish one message to a RabbitMQ queue through the management HTTP API — the
# same thing the docs do by hand in the Management UI, done as a producer from
# outside the integration. Used by event-driven workflows as a shell action.
#
# Prints {"routed":true} when a queue took the message. {"routed":false} means
# nothing is bound to that queue name yet, usually because the integration is
# not running or the queue was never declared.
set -euo pipefail
queue="${1:?usage: rmq_publish.sh QUEUE PAYLOAD}"
payload="${2:?usage: rmq_publish.sh QUEUE PAYLOAD}"
host="${RABBITMQ_MGMT:-http://localhost:15672}"
auth="${RABBITMQ_AUTH:-guest:guest}"
curl -fsS -u "$auth" -H 'content-type: application/json' \
  -X POST "$host/api/exchanges/%2F/amq.default/publish" \
  -d "{\"properties\":{},\"routing_key\":\"$queue\",\"payload\":\"$payload\",\"payload_encoding\":\"string\"}"
echo
