#!/bin/sh
# procd long-running helper — re-apply routing every minute.
ROUTING_SCRIPT=/opt/gateway-agent/deeporc-routing.sh
[ -x "$ROUTING_SCRIPT" ] || exit 1
while true; do
	"$ROUTING_SCRIPT" apply || true
	sleep 60
done
