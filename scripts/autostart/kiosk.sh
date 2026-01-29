#!/bin/bash
# kiosk.sh - Launch Chromium in Kiosk mode for Ground Station
# This script is called by the autostart configuration

# Wait for the backend to be ready
sleep 5

# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Hide cursor after 0.5 seconds of inactivity
unclutter -idle 0.5 -root &

# Launch Chromium in Kiosk mode
chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --no-first-run \
    --start-fullscreen \
    --window-size=800,480 \
    --window-position=0,0 \
    http://localhost:8000
