#!/bin/bash
cd "/home/admin/DDL-JS"
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8080 &
sleep 10
export DISPLAY=:0
firefox-esr --kiosk http://127.0.0.1:8080
