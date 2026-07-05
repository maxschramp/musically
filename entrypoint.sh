#!/bin/bash
# =============================================================================
# Musically — Container Entrypoint
# =============================================================================
# 1. Generate a self-signed SSL certificate for LAN HTTPS (if none exists)
# 2. Exec the provided command (supervisord by default)
#
# The self-signed cert enables Spotify OAuth on LAN-only setups.
# Spotify requires https:// redirect URIs; it never connects to your
# server — only your browser does. Accept the browser warning once.
# =============================================================================
set -e

SSL_DIR="/config/ssl"
CERT_FILE="$SSL_DIR/musically.crt"
KEY_FILE="$SSL_DIR/musically.key"

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "=== Generating self-signed SSL certificate for LAN HTTPS ==="
    mkdir -p "$SSL_DIR"

    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -subj "/CN=Musically-LAN/O=Musically/OU=SelfSigned" \
        -addext "subjectAltName=IP:127.0.0.1,IP:192.168.0.0/16,IP:10.0.0.0/8,IP:172.16.0.0/12,DNS:localhost,DNS:*.local" \
        2>/dev/null

    chmod 600 "$KEY_FILE"
    chmod 644 "$CERT_FILE"
    echo "Self-signed certificate generated: $CERT_FILE"
    echo ""
    echo "NOTE: Your browser will show a security warning when accessing via HTTPS."
    echo "      This is expected for self-signed certs on a LAN server."
    echo "      Accept the warning once — Spotify only needs the https:// URL scheme."
    echo ""
fi

exec "$@"
