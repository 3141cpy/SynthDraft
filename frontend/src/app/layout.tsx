import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Layers } from "lucide-react";
import { ThemeProvider } from "next-themes";
import { Badge } from "@/components/ui/badge";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Toaster } from "@/components/ui/sonner";
import { Sidebar } from "@/components/Sidebar";
import { MobileNav } from "@/components/MobileNav";
import { cn } from "@/lib/utils";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "SynthDraft - AI 驱动工程设计辅助系统",
  description: "AI 驱动工程设计辅助系统的 Web 控制台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className={cn(inter.variable, "font-sans antialiased")}>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <div className="flex min-h-screen flex-col">
            {/* 顶部 header */}
            <header className="flex h-header-height items-center justify-between border-b border-border bg-background px-4 sm:px-6">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
                  <Layers className="h-4 w-4" />
                </div>
                <span className="text-lg font-semibold tracking-tight">
                  SynthDraft
                </span>
                <span className="hidden text-xs text-muted-foreground sm:inline">
                  AI 驱动工程设计辅助系统
                </span>
              </div>
              <div className="flex items-center gap-2">
                <MobileNav />
                {process.env.NODE_ENV === "development" && (
                  <Badge variant="secondary">开发模式</Badge>
                )}
                <ThemeToggle />
              </div>
            </header>

            <div className="flex flex-1">
              {/* 桌面 sidebar（md: 及以上） */}
              <Sidebar />

              {/* 主内容区 */}
              <main className="flex-1 overflow-auto bg-background p-6">
                {children}
              </main>
            </div>
          </div>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
