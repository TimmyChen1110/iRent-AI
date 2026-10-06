import type { NextConfig } from "next";

/**
 * 正式部署：靜態匯出到 out/，由 FastAPI 於 /ops 提供（NEXT_OUTPUT=export npm run build）。
 * 開發：next dev 於 3000，/api 與 /photos 代理到 backend 8000（同源 cookie session）。
 */
const isExport = process.env.NEXT_OUTPUT === "export";
const backend = process.env.BACKEND_ORIGIN || "http://localhost:8000";

const nextConfig: NextConfig = {
  basePath: "/ops",
  output: isExport ? "export" : undefined,
  trailingSlash: false,
  images: { unoptimized: true },
  env: { NEXT_PUBLIC_BASE_PATH: "/ops" },
  ...(isExport
    ? {}
    : {
        async rewrites() {
          return [
            { source: "/api/:path*", destination: `${backend}/api/:path*`, basePath: false as const },
            { source: "/photos/:path*", destination: `${backend}/photos/:path*`, basePath: false as const },
          ];
        },
      }),
};

export default nextConfig;
