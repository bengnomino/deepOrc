#!/bin/sh
# Legacy entrypoint — delegates to procd-managed deeporc-routing.
exec /opt/gateway-agent/deeporc-routing.sh apply
