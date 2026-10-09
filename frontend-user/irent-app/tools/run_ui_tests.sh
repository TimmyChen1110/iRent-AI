#!/bin/zsh
# iRent App UI 測試（irent-appUITests）一鍵執行：
#   1. 複製正式資料庫成測試副本（不碰 backend/app/decisions.sqlite3 本體）
#   2. 以 DEMO_MODE=true 在 127.0.0.1:8011 啟動後端（測試會清空副本內的模擬 Session）
#   3. 從資料集準備測試照片（App 的「使用測試照片」→ 真實 Core ML 車牌辨識）
#   4. 在指定模擬器跑 UI 測試；結束後關閉後端
# 用法：tools/run_ui_tests.sh <模擬器 UDID> [測試名稱，例如 testWrongPlateIsRejectedByRealOCR]
# 注意：完整流程與「分析中取消」兩項會呼叫真實 Gemini（需 GEMINI_API_KEY），約 6–8 分鐘。
set -euo pipefail
UDID=${1:?需要模擬器 UDID（xcrun simctl list devices booted）}
ONLY=${2:-}
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
APP_DIR="$ROOT/frontend-user/irent-app"
DATASET="$ROOT/iRent - 運用 AI 打造 iRent 智能車況管家：優化租還車體驗與營運效率/沒有進行索賠"
WORK=$(mktemp -d -t irent-uitest)
trap '[[ -n "${SERVER_PID:-}" ]] && kill $SERVER_PID 2>/dev/null; true' EXIT

cp "$ROOT/backend/app/decisions.sqlite3" "$WORK/test.sqlite3"
mkdir -p "$WORK/uploads" "$WORK/ok" "$WORK/wrong"
(cd "$ROOT/backend/app" && DEMO_MODE=true IRENT_DB_PATH="$WORK/test.sqlite3" IRENT_UPLOAD_DIR="$WORK/uploads" \
  ../.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8011 > "$WORK/server.log" 2>&1) &
SERVER_PID=$!

# 資料集檔名的「左前／右前」在車頭照是左右相反的，前兩角對調後才會通過 App 的角度檢查
for pair in pickup:借 return:還; do
  stage=${pair%%:*}; tag=${pair##*:}
  cp "$DATASET/RDL7827右前 $tag.jpg" "$WORK/ok/$stage-左前.jpg"
  cp "$DATASET/RDL7827左前 $tag.jpg" "$WORK/ok/$stage-右前.jpg"
  cp "$DATASET/RDL7827左後 $tag.jpg" "$WORK/ok/$stage-左後.jpg"
  cp "$DATASET/RDL7827右後 $tag.jpg" "$WORK/ok/$stage-右後.jpg"
done
cp "$DATASET/RDG9853右前 借.jpg" "$WORK/wrong/pickup-左前.jpg"     # 別台車：應被判定車牌不符

until curl -s -o /dev/null http://127.0.0.1:8011/api/ops/health; do sleep 1; done
xcrun simctl privacy "$UDID" grant location timmy.irent-app || true
xcrun simctl location "$UDID" set 25.0176,121.5390 || true

export TEST_RUNNER_IRENT_API=http://127.0.0.1:8011
export TEST_RUNNER_IRENT_PHOTOS_OK="$WORK/ok"
export TEST_RUNNER_IRENT_PHOTOS_WRONG="$WORK/wrong"
export TEST_RUNNER_IRENT_DATASET="$DATASET"
cd "$APP_DIR"
xcodebuild -project irent-app.xcodeproj -scheme irent-app -destination "id=$UDID" \
  -resultBundlePath "$WORK/result.xcresult" test ${ONLY:+-only-testing:irent-appUITests/IRentUITests/$ONLY}
echo "結果與截圖：$WORK/result.xcresult（後端紀錄：$WORK/server.log）"
