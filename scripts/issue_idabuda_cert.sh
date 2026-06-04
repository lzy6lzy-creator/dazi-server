#!/usr/bin/env sh
set -eu

DOMAIN="idabuda.com"
WWW_DOMAIN="www.idabuda.com"
BASE_DIR="/opt/dazi-server"
CERTBOT_CONF="$BASE_DIR/certbot/conf"
CERTBOT_WWW="$BASE_DIR/certbot/www"
LIVE_DIR="$CERTBOT_CONF/live/$DOMAIN"
CERT_MODE="${DAZI_CERT_MODE:-webroot}"
BACKUP_DIR=""
CERTBOT_SUCCEEDED="0"

create_self_signed_cert() {
  mkdir -p "$LIVE_DIR"
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout "$LIVE_DIR/privkey.pem" \
    -out "$LIVE_DIR/fullchain.pem" \
    -subj "/CN=$DOMAIN"
}

backup_existing_certbot_state() {
  BACKUP_DIR="$CERTBOT_CONF/.idabuda-cert-backup-$$"
  rm -rf "$BACKUP_DIR"
  mkdir -p "$BACKUP_DIR"

  if [ -e "$LIVE_DIR" ]; then
    mv "$LIVE_DIR" "$BACKUP_DIR/live"
  fi
  if [ -e "$CERTBOT_CONF/archive/$DOMAIN" ]; then
    mv "$CERTBOT_CONF/archive/$DOMAIN" "$BACKUP_DIR/archive"
  fi
  if [ -e "$CERTBOT_CONF/renewal/$DOMAIN.conf" ]; then
    mv "$CERTBOT_CONF/renewal/$DOMAIN.conf" "$BACKUP_DIR/renewal.conf"
  fi
}

restore_removed_certbot_state() {
  if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    rm -rf \
      "$LIVE_DIR" \
      "$CERTBOT_CONF/archive/$DOMAIN" \
      "$CERTBOT_CONF/renewal/$DOMAIN.conf"

    if [ -e "$BACKUP_DIR/live" ]; then
      mkdir -p "$CERTBOT_CONF/live"
      mv "$BACKUP_DIR/live" "$LIVE_DIR"
    fi
    if [ -e "$BACKUP_DIR/archive" ]; then
      mkdir -p "$CERTBOT_CONF/archive"
      mv "$BACKUP_DIR/archive" "$CERTBOT_CONF/archive/$DOMAIN"
    fi
    if [ -e "$BACKUP_DIR/renewal.conf" ]; then
      mkdir -p "$CERTBOT_CONF/renewal"
      mv "$BACKUP_DIR/renewal.conf" "$CERTBOT_CONF/renewal/$DOMAIN.conf"
    fi
    rmdir "$BACKUP_DIR" 2>/dev/null || true
  fi

  if [ ! -f "$LIVE_DIR/fullchain.pem" ] || [ ! -f "$LIVE_DIR/privkey.pem" ]; then
    create_self_signed_cert
  fi
}

cleanup_on_exit() {
  if [ "$CERTBOT_SUCCEEDED" != "1" ]; then
    echo "[fail] certbot DNS issuance did not finish; restoring previous certificate state" >&2
    restore_removed_certbot_state
    docker compose -f docker-compose.prod.yml up -d web
  fi
}

cd "$BASE_DIR"
mkdir -p "$CERTBOT_CONF" "$CERTBOT_WWW"

if [ ! -f "$LIVE_DIR/fullchain.pem" ] || [ ! -f "$LIVE_DIR/privkey.pem" ]; then
  create_self_signed_cert
fi

docker compose -f docker-compose.prod.yml up -d api

if ! openssl x509 -in "$LIVE_DIR/fullchain.pem" -noout -issuer 2>/dev/null | grep -q "Let's Encrypt"; then
  backup_existing_certbot_state
fi

trap cleanup_on_exit EXIT INT TERM

issue_webroot_certificate() {
  docker compose -f docker-compose.prod.yml up -d web
  docker run --rm \
    -v "$CERTBOT_CONF:/etc/letsencrypt" \
    -v "$CERTBOT_WWW:/var/www/certbot" \
    certbot/certbot certonly \
    --webroot \
    --webroot-path /var/www/certbot \
    --non-interactive \
    --agree-tos \
    --register-unsafely-without-email \
    --no-eff-email \
    --cert-name "$DOMAIN" \
    -d "$DOMAIN" \
    -d "$WWW_DOMAIN"
}

issue_manual_dns_certificate() {
  docker run -it --rm \
    -v "$CERTBOT_CONF:/etc/letsencrypt" \
    certbot/certbot certonly \
    --manual \
    --preferred-challenges dns \
    --agree-tos \
    --register-unsafely-without-email \
    --no-eff-email \
    --cert-name "$DOMAIN" \
    -d "$DOMAIN" \
    -d "$WWW_DOMAIN"
}

case "$CERT_MODE" in
  webroot)
    issue_webroot_certificate || exit 1
    ;;
  manual-dns)
    issue_manual_dns_certificate || exit 1
    ;;
  *)
    echo "[fail] unsupported DAZI_CERT_MODE: $CERT_MODE" >&2
    exit 1
    ;;
esac

CERTBOT_SUCCEEDED="1"
trap - EXIT INT TERM

if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
  rm -rf "$BACKUP_DIR"
fi

docker compose -f docker-compose.prod.yml up -d web
