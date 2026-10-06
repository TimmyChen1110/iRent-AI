#!/bin/sh
set -eu

for dir in /data /data/uploads /data/scratch; do
  if ! mkdir -p "$dir"; then
    echo "ERROR: 無法建立持久化目錄 $dir，請檢查 Docker volume 權限。" >&2
    exit 1
  fi
done

if ! touch /data/.irent-write-check; then
  echo "ERROR: /data 無法寫入，SQLite 與完工照不能持久化。" >&2
  exit 1
fi
rm -f /data/.irent-write-check

base_url="${PUBLIC_BASE_URL:-http://localhost:8000}"
echo "iRent Demo 啟動中"
echo "  車況監理台: ${base_url}/"
echo "  Admin 後台:  ${base_url}/ops"
echo "  站點手機版:  ${base_url}/ops/m"
echo "  Health:       ${base_url}/api/health"
echo "  Demo 登入:    ${IRENT_ADMIN_USERNAME:-admin}（Admin）/ ${IRENT_STATION_USERNAME:-station}（Station）"
if [ -z "${GEMINI_API_KEY:-}" ] && [ -z "${GOOGLE_API_KEY:-}" ]; then
  echo "INFO: 未設定 Gemini API Key；Admin、Task、Fleet、Insights 與完工流程仍可使用，AI 重判/文案生成停用。"
fi

exec "$@"
