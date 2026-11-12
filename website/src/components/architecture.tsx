"use client";

import { useState } from "react";
import {
    ArrowRight,
    Box,
    Cable,
    Check,
    CircleDot,
    Globe,
    Laptop,
    LockKeyhole,
    Network,
    Route,
    ShieldCheck,
} from "lucide-react";

function Connector() {
    return (
        <span className="route-connector" aria-hidden="true">
            <svg viewBox="0 0 60 20" preserveAspectRatio="none">
                <path d="M0 10H60" className="route-track" />
                <path d="M0 10H60" className="route-pulse" />
            </svg>
            <ArrowRight size={13} />
        </span>
    );
}

export function Architecture() {
    const [mode, setMode] = useState<"managed" | "local">("managed");
    const managed = mode === "managed";
    return (
        <div className="architecture-panel" data-reveal>
            <div className="architecture-toolbar">
                <div
                    className="mode-tabs"
                    role="tablist"
                    aria-label="代理接入模式"
                    onKeyDown={(event) => {
                        if (
                            ["ArrowLeft", "ArrowRight", "Home", "End"].includes(
                                event.key,
                            )
                        ) {
                            event.preventDefault();
                            const next =
                                event.key === "Home"
                                    ? "managed"
                                    : event.key === "End"
                                      ? "local"
                                      : managed
                                        ? "local"
                                        : "managed";
                            setMode(next);
                            document.getElementById(`${next}-tab`)?.focus();
                        }
                    }}
                >
                    <button
                        id="managed-tab"
                        role="tab"
                        tabIndex={managed ? 0 : -1}
                        aria-selected={managed}
                        aria-controls="route-panel"
                        onClick={() => setMode("managed")}
                    >
                        <LockKeyhole size={14} />
                        软件内双跳<span>推荐</span>
                    </button>
                    <button
                        id="local-tab"
                        role="tab"
                        tabIndex={managed ? -1 : 0}
                        aria-selected={!managed}
                        aria-controls="route-panel"
                        onClick={() => setMode("local")}
                    >
                        <Route size={14} />
                        本机 v2ray 兼容
                    </button>
                </div>
                <span className="diagram-label mono">
                    NETWORK PATH / 结构示意
                </span>
            </div>
            <div
                role="tabpanel"
                tabIndex={0}
                id="route-panel"
                aria-labelledby={managed ? "managed-tab" : "local-tab"}
                className="route-panel"
            >
                <div className="control-plane">
                    <Laptop size={15} />
                    <strong>Windows 桌面控制端</strong>
                    <span>配置 · 授权 · 核对出口</span>
                    <span className="control-dash" aria-hidden="true" />
                </div>
                <div className="route-flow">
                    <div className="docker-boundary">
                        <span className="docker-label">
                            <Box size={12} />
                            DOCKER LINUX 工作区
                        </span>
                        <div className="workspace-node">
                            <Box size={23} />
                            <strong>编程工具与浏览器</strong>
                            <span>
                                Claude Code · Codex
                                <br />
                                Linux 终端 · Chromium
                            </span>
                        </div>
                        <Connector />
                        <div className="gateway-node">
                            <ShieldCheck size={23} />
                            <strong>受控网关</strong>
                            <span>工作区外联入口</span>
                        </div>
                    </div>
                    <Connector />
                    <div className="route-node line-node">
                        <span className="hop-label mono">FIRST HOP</span>
                        {managed ? (
                            <LockKeyhole size={24} />
                        ) : (
                            <Laptop size={24} />
                        )}
                        <strong>
                            {managed ? "固定加密线路" : "本机 v2ray"}
                        </strong>
                        <span>
                            {managed ? "由软件固定第一跳" : "由外部客户端转发"}
                        </span>
                        <span className="exit-label">
                            <CircleDot size={10} />
                            线路出口 · 独立核验
                        </span>
                    </div>
                    <Connector />
                    <div className="route-node landing-node">
                        <span className="hop-label mono">LANDING</span>
                        <Network size={24} />
                        <strong>落地代理</strong>
                        <div className="landing-options">
                            <span>SOCKS5</span>
                            <span>HTTP</span>
                            <span>HTTPS</span>
                        </div>
                        <small>三选一，单个落地</small>
                        <span className="exit-label">
                            <CircleDot size={10} />
                            最终出口 · 落地核验
                        </span>
                    </div>
                    <Connector />
                    <div className="destination-node">
                        <Globe size={27} />
                        <strong>目标服务</strong>
                        <span>通过所选出口访问</span>
                    </div>
                </div>
                <div
                    className={`route-explanation ${managed ? "" : "compatibility-note"}`}
                >
                    <span className="route-note-icon">
                        {managed ? (
                            <LockKeyhole size={16} />
                        ) : (
                            <Cable size={16} />
                        )}
                    </span>
                    <p>
                        {managed ? (
                            <>
                                <strong>固定路径，不设 DIRECT 备用。</strong>{" "}
                                分别核验线路与最终出口，由你确认后启用；检测到连接、出口或拓扑异常时停止本环境。
                            </>
                        ) : (
                            <>
                                <strong>
                                    保留熟悉的客户端，也明确它的边界。
                                </strong>{" "}
                                本机 v2ray
                                的按目标分流由外部客户端控制，检测服务出口一致不能证明每个目标都经过同一线路。
                            </>
                        )}
                    </p>
                </div>
            </div>
            <div className="architecture-bottom">
                <span>
                    <Check size={13} />
                    保留 TLS 证书验证
                </span>
                <span>
                    <Check size={13} />
                    线路与落地分别选择
                </span>
                <span>
                    <Check size={13} />
                    出口变化需重新核对
                </span>
            </div>
        </div>
    );
}
