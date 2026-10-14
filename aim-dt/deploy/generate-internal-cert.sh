#!/bin/bash
set -euo pipefail
ROOT="${AIM_DT_ROOT:-/Users/quality/yield-analyzer/aim-dt}"
CERT_DIR="$ROOT/certs"
HOST="${AIM_DT_HOST:-quality-server.local}"
IP="${AIM_DT_IP:-192.168.60.9}"
mkdir -p "$CERT_DIR"
openssl req -x509 -nodes -newkey rsa:3072 -days 825 \
  -keyout "$CERT_DIR/aim-dt.key" \
  -out "$CERT_DIR/aim-dt.crt" \
  -subj "/CN=$HOST/O=AIM D-T Internal" \
  -addext "subjectAltName=DNS:$HOST,IP:$IP"
chmod 600 "$CERT_DIR/aim-dt.key"
echo "Generated $CERT_DIR/aim-dt.crt"
echo "Distribute the certificate to client trust stores before production use."
