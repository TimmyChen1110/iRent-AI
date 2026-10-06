import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/store/AuthStore";
import { ThemeProvider, THEME_BOOT_SCRIPT } from "@/store/ThemeStore";
import { OpsProvider } from "@/store/OpsStore";
import { AppShell } from "@/components/layout/AppShell";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "iRent 整備中心 · AI 車隊營運中心",
  description: "iRent 環節三：還車 AI 檢測、車輛數位分身與整備派工管理後台。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body className="min-h-full">
        <ThemeProvider>
          <AuthProvider>
            <OpsProvider>
              <AppShell>{children}</AppShell>
            </OpsProvider>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
