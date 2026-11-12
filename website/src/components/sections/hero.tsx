import {
    ArrowDownToLine,
    ArrowRight,
    ArrowUpRight,
    Box,
    Globe,
    Monitor,
    SquareTerminal,
} from "lucide-react";
import { HeroVisual } from "@/components/interactions";
import { product } from "@/lib/content";

export function HeroSection() {
    return (
        <section className="hero" aria-labelledby="hero-title">
            <div className="hero-aura" aria-hidden="true" />
            <div className="hero-grid" aria-hidden="true" />
            <div className="container hero-main">
                <div className="hero-copy">
                    <a
                        className="release-pill"
                        href={product.release}
                        target="_blank"
                        rel="noreferrer"
                    >
                        <span className="tiny-dot" />v{product.version}
                        <span className="pill-divider" />
                        正式版现已发布
                        <ArrowUpRight size={12} />
                    </a>
                    <p className="hero-eyebrow mono">YOUR SPACE TO BUILD.</p>
                    <h1 id="hero-title">
                        为 AI 编程，
                        <br />
                        <span>留一块独立空间。</span>
                    </h1>
                    <p className="hero-description">
                        Windows 上的 AI 编程隔离工作台。
                        <br />让 Claude Code、Codex 与浏览器在容器中工作，
                        <br className="desktop-break" />
                        项目、身份和网络路径，由你掌控。
                    </p>
                    <div className="hero-actions">
                        <a
                            className="button button-primary"
                            href={product.installer}
                        >
                            <ArrowDownToLine size={18} />
                            下载 Windows 版
                            <ArrowRight size={16} className="button-arrow" />
                        </a>
                        <a
                            className="button button-secondary"
                            href={product.repository}
                            target="_blank"
                            rel="noreferrer"
                        >
                            查看 GitHub
                            <ArrowUpRight size={16} />
                        </a>
                    </div>
                    <p className="hero-platform">
                        <Monitor size={13} />
                        Windows x64<span>·</span>Docker Desktop / WSL2
                        <span>·</span>无需另装 Python
                    </p>
                </div>
                <HeroVisual />
            </div>
            <div className="container tool-strip">
                <span className="tool-strip-heading">
                    熟悉的工具
                    <br />
                    <strong>独立的运行空间</strong>
                </span>
                <div className="tool-name">
                    <span className="claude-symbol" aria-hidden="true">
                        ✳
                    </span>
                    Claude Code
                </div>
                <div className="tool-name">
                    <SquareTerminal />
                    Codex
                </div>
                <div className="tool-name">
                    <Globe />
                    Chromium
                </div>
                <span className="tool-strip-divider" />
                <div className="tool-environment">
                    <Box size={18} />
                    <span>
                        Docker Linux 容器
                        <br />
                        <small>Windows 桌面统一管理</small>
                    </span>
                </div>
            </div>
        </section>
    );
}
