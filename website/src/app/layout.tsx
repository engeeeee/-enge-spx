import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { product } from "@/lib/content";
import { SiteInteractions } from "@/components/interactions";
import "./globals.css";

export const metadata: Metadata = {
    metadataBase: new URL(product.site),
    title: "ENGE SPX — Windows AI 编程隔离工作台",
    description:
        "为 Claude Code、Codex 与 Chromium 建立独立容器工作区。选择项目与身份，固定线路和落地代理，核对出口，按需要分配资源。Windows x64 版现已提供下载。",
    applicationName: product.name,
    alternates: { canonical: "/" },
    openGraph: {
        title: "ENGE SPX — 给 AI 编程，一个独立空间",
        description:
            "Windows 上的 AI 编程隔离工作台。容器工作区、独立身份、固定代理链路与出口核验。",
        url: product.site,
        siteName: product.name,
        locale: "zh_CN",
        type: "website",
        images: [
            {
                url: "/og.png",
                width: 1200,
                height: 630,
                alt: "ENGE SPX 官网与真实 Windows 软件界面",
            },
        ],
    },
    twitter: {
        card: "summary_large_image",
        title: "ENGE SPX — Windows AI 编程隔离工作台",
        images: ["/og.png"],
    },
    icons: { icon: "/brand/logo.svg", apple: "/apple-touch-icon.png" },
    robots: { index: true, follow: true },
};

export const viewport: Viewport = {
    themeColor: "#191815",
    colorScheme: "dark",
    width: "device-width",
    initialScale: 1,
};

export default function RootLayout({
    children,
}: Readonly<{ children: React.ReactNode }>) {
    return (
        <html lang="zh-CN" className={GeistSans.variable}>
            <body>
                <SiteInteractions>{children}</SiteInteractions>
            </body>
        </html>
    );
}
