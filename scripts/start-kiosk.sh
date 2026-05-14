#!/bin/bash
# Daedalus GCS — Kiosk browser launcher
# Started by XDG/LXDE autostart after desktop login.
# Waits for the backend (systemd service) to be ready before opening the browser.

GCS_PORT=8080
GCS_URL="http://127.0.0.1:${GCS_PORT}"

# ─── Wait for backend ─────────────────────────────────────────────
echo "[kiosk] Waiting for GCS backend on port ${GCS_PORT}..."
for i in $(seq 1 60); do
    if curl -sf "${GCS_URL}/api/health" >/dev/null 2>&1; then
        echo "[kiosk] Backend ready (${i}s)."
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "[kiosk] WARNING: Backend not ready after 60s — opening anyway."
    fi
    sleep 1
done

# ─── Disable screen blanking / power save ─────────────────────────
xset s off s noblank -dpms 2>/dev/null || true

# ─── Hide mouse cursor after 0.5 s of inactivity ──────────────────
unclutter -idle 0.5 -root &

# ─── Launch browser ───────────────────────────────────────────────
if command -v firefox-esr &>/dev/null; then
    BROWSER="firefox-esr"
elif command -v firefox &>/dev/null; then
    BROWSER="firefox"
else
    echo "[kiosk] ERROR: No browser found (firefox-esr / firefox)."
    exit 1
fi

exec "$BROWSER" "$GCS_URL"
