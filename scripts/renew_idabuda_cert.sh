#!/usr/bin/env sh
set -eu

BASE_DIR="/opt/dazi-server"
CERTBOT_CONF="$BASE_DIR/certbot/conf"
CERTBOT_WWW="$BASE_DIR/certbot/www"
CERT_MODE="${DAZI_CERT_MODE:-webroot}"

cd "$BASE_DIR"

case "$CERT_MODE" in
  webroot)
    docker run --rm \
      -v "$CERTBOT_CONF:/etc/letsencrypt" \
      -v "$CERTBOT_WWW:/var/www/certbot" \
      certbot/certbot renew \
      --webroot \
      --webroot-path /var/www/certbot \
      --quiet
    docker exec dazi-web nginx -s reload
    ;;
  manual-dns)
    echo "[fail] Manual DNS-01 certificates cannot renew unattended." >&2
    echo "[fail] To automate renewal, finish ICP filing so HTTP-01 can work, or provide DNS API credentials for a DNS API authenticator." >&2
    exit 1
    ;;
  *)
    echo "[fail] unsupported DAZI_CERT_MODE: $CERT_MODE" >&2
    exit 1
    ;;
esac
