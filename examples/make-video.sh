#!/usr/bin/env bash
# Make a whiteboard video with the KolaVid REST API and download it when it's ready.
# Needs curl and jq, and an API key from https://kolavid.com/app/account?tab=api in KOLAVID_API_KEY.
set -euo pipefail

: "${KOLAVID_API_KEY:?Set KOLAVID_API_KEY first}"
API=https://kolavid.com/api/v1

id=$(curl -sf "$API/videos" \
  -H "Authorization: Bearer $KOLAVID_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How vaccines work, for 12-year-olds", "length_minutes": 1}' | jq -r .id)
echo "Started video $id"

while true; do
  video=$(curl -sf "$API/videos/$id" -H "Authorization: Bearer $KOLAVID_API_KEY")
  status=$(echo "$video" | jq -r .status)
  echo "status: $status"
  case "$status" in
    completed) break ;;
    failed) echo "$video" | jq . ; exit 1 ;;
  esac
  sleep 10
done

curl -sfL "$(echo "$video" | jq -r .video_url)" -o "kolavid-$id.mp4"
echo "Saved kolavid-$id.mp4"
