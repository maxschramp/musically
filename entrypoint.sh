#!/bin/bash
# =============================================================================
# Musically — Container Entrypoint
# =============================================================================
# 1. Seed beets config directory with defaults if missing
# 2. Generate a self-signed SSL certificate for LAN HTTPS (if none exists)
# 3. Exec the provided command (supervisord by default)
# =============================================================================

# ---------------------------------------------------------------------------
# Seed beets config directory
# ---------------------------------------------------------------------------
BEETS_DIR="/config/beets"
if [ ! -f "$BEETS_DIR/config.yaml" ]; then
    echo "=== Seeding default beets configuration ==="
    mkdir -p "$BEETS_DIR"
    cat > "$BEETS_DIR/config.yaml" << 'YAMLEOF'
directory: /music/library
library: /config/beets/library.db

import:
  copy: yes
  move: no
  write: yes
  autotag: yes
  quiet: yes
  timid: no
  resume: no
  incremental: no

paths:
  default: $albumartist/$album/$track $artist - $title

plugins: []

ui:
  color: yes
YAMLEOF
    echo "beets config seeded at $BEETS_DIR/config.yaml"
fi

# ---------------------------------------------------------------------------
# Self-signed SSL certificate for LAN HTTPS
# ---------------------------------------------------------------------------
SSL_DIR="/config/ssl"
CERT_FILE="$SSL_DIR/musically.crt"
KEY_FILE="$SSL_DIR/musically.key"

generate_cert() {
    echo "=== Generating self-signed SSL certificate for LAN HTTPS ==="
    mkdir -p "$SSL_DIR"

    # First try with subjectAltName extension (OpenSSL 1.1.1+)
    if openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -subj "/CN=Musically-LAN/O=Musically/OU=SelfSigned" \
        -addext "subjectAltName=DNS:localhost" \
        >/dev/null 2>&1; then
        echo "Certificate generated with SAN extension."
    else
        # Fallback: generate without SAN (works on older OpenSSL)
        echo "SAN extension not supported, generating basic certificate..."
        if openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
            -keyout "$KEY_FILE" \
            -out "$CERT_FILE" \
            -subj "/CN=Musically-LAN/O=Musically/OU=SelfSigned" \
            >/dev/null 2>&1; then
            echo "Basic certificate generated."
        else
            echo "WARNING: Failed to generate SSL certificate." >&2
            echo "The app will still work on HTTP. Spotify OAuth needs HTTPS." >&2
            rm -f "$CERT_FILE" "$KEY_FILE"
            return 1
        fi
    fi

    chmod 600 "$KEY_FILE" 2>/dev/null || true
    chmod 644 "$CERT_FILE" 2>/dev/null || true
    echo "Self-signed certificate generated: $CERT_FILE"
    echo ""
    echo "NOTE: Your browser will show a security warning when accessing via HTTPS."
    echo "      This is expected for self-signed certs on a LAN server."
    echo "      Accept the warning once — Spotify only needs the https:// URL scheme."
    echo ""
    return 0
}

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    generate_cert || true
fi

# ---------------------------------------------------------------------------
# Enable HTTPS nginx config only if the certificate exists
# ---------------------------------------------------------------------------
SSL_NGINX_CONF="/etc/nginx/conf.d/default.ssl.conf"
SSL_NGINX_TEMPLATE="/etc/nginx/ssl/default.ssl.conf"

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    if [ ! -f "$SSL_NGINX_CONF" ] && [ -f "$SSL_NGINX_TEMPLATE" ]; then
        cp "$SSL_NGINX_TEMPLATE" "$SSL_NGINX_CONF"
        echo "HTTPS enabled — nginx listening on port 443"
    fi
else
    rm -f "$SSL_NGINX_CONF"
    echo "HTTPS not available — cert not found, nginx will serve HTTP only"
fi

# ---------------------------------------------------------------------------
# Bootup banner
# ---------------------------------------------------------------------------
BUILD_DATE="${BUILD_DATE:-unknown}"
BUILD_REF="${BUILD_REF:-dev}"
HTTPS_STATUS="disabled"
if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    HTTPS_STATUS="enabled (port 443)"
fi

cat << "BOOTEOF"


  ╔══════════════════════════════════════════════════════════════════╗
  ║                                                                  ║
  ║   ███╗   ███╗██╗   ██╗███████╗██╗ ██████╗ █████╗ ██╗     ██╗   ║
  ║   ████╗ ████║██║   ██║██╔════╝██║██╔════╝██╔══██╗██║     ╚██╗  ║
  ║   ██╔████╔██║██║   ██║███████╗██║██║     ███████║██║      ╚██╗ ║
  ║   ██║╚██╔╝██║██║   ██║╚════██║██║██║     ██╔══██║██║      ██╔╝ ║
  ║   ██║ ╚═╝ ██║╚██████╔╝███████║██║╚██████╗██║  ██║███████╗██╔╝  ║
  ║   ╚═╝     ╚═╝ ╚═════╝ ╚══════╝╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝   ║
  ║                                                                  ║
  ║          Self-hosted music discovery & download automation        ║
  ║                                                                  ║
  ╠══════════════════════════════════════════════════════════════════╣
  ║  Version  : v${VERSION:-?.?.?} (${BUILD_REF:-dev})                    ║
  ║  Built    : ${BUILD_DATE:-unknown}                                    ║
  ║  HTTP     : port 80 (always on)                                  ║
  ║  HTTPS    : ${HTTPS_STATUS}                       ║
  ║  Docs     : /docs  |  /redoc                                    ║
  ╚══════════════════════════════════════════════════════════════════╝

BOOTEOF

exec "$@"
