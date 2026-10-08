# Build context 為專案根目錄：docker build -f fleet-ops-center/Dockerfile .

# 第一階段：安裝依賴並將 Next.js 靜態匯出至 out/。
FROM node:22-alpine AS builder
WORKDIR /fe

COPY fleet-ops-center/package.json fleet-ops-center/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY fleet-ops-center/ ./
RUN NEXT_OUTPUT=export NEXT_TELEMETRY_DISABLED=1 npm run build

# 第二階段：只包含 Nginx、靜態網站與 API 代理設定。
FROM nginx:stable-alpine AS runtime
COPY --from=builder /fe/out/ /usr/share/nginx/html/ops/
COPY fleet-ops-center/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
