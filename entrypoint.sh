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
#
# Cert generation is best-effort: if it fails, the container still starts
# and the app works fine on HTTP — only Spotify OAuth needs HTTPS.
# =============================================================================

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

exec "$@"
