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

# ─── Launch browser (windowed) ────────────────────────────────────
# Prefer chromium (lighter on Pi); fall back to firefox-esr
if command -v chromium-browser &>/dev/null; then
    BROWSER="chromium-browser"
elif command -v chromium &>/dev/null; then
    BROWSER="chromium"
elif command -v firefox-esr &>/dev/null; then
    BROWSER="firefox-esr"
    exec "$BROWSER" "$GCS_URL"
else
    echo "[kiosk] ERROR: No supported browser found (chromium-browser / firefox-esr)."
    exit 1
fi

exec "$BROWSER" \
    --no-sandbox \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --disable-features=TranslateUI \
    --noerrdialogs \
    --check-for-update-interval=31536000 \
    "$GCS_URL"
