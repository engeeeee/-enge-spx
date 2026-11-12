import {
    ArrowRight,
    Box,
    CircleDot,
    Fingerprint,
    FolderOpen,
    SquareTerminal,
} from "lucide-react";
import { SectionLabel, TextLink } from "@/components/section-ui";
import { docs } from "@/lib/content";

export function FeaturesSection() {
    return (
        <section id="features" className="section features-section">
            <div className="container">
                <div className="section-heading" data-reveal>
                    <div>
                        <SectionLabel number="01">
                            为工作流留出边界
                        </SectionLabel>
                        <h2>
                            工具各就各位。
                            <br />
                            <span className="muted-heading">
                                你只管把项目做好。
                            </span>
                        </h2>
                    </div>
                    <p className="heading-description">
                        把工具依赖、登录资料和代理路径集中管理。
                        <br />
                        从日常 Windows 环境，划出一块专注的工作区。
                    </p>
                </div>
                <div className="feature-grid">
                    <article
                        className="feature-card feature-container"
                        data-reveal
                    >
                        <span className="card-index mono">
                            01 / A SPACE OF ITS OWN
                        </span>
                        <div className="feature-copy">
                            <span className="feature-icon">
                                <Box />
                            </span>
                            <h3>
                                工具在容器。
                                <br />
                                项目在本机。
                            </h3>
                            <p>
                                Claude Code、Codex 与 Linux
                                命令运行在容器内。只挂载选中的项目，让依赖与日常环境各自安放。
                            </p>
                        </div>
                        <div
                            className="isolation-illustration"
                            aria-label="项目授权挂载到 Linux 工具容器的结构示意"
                        >
                            <div className="local-folder">
                                <FolderOpen size={31} />
                                <span>你选中的项目</span>
                                <small>本机目录</small>
                            </div>
                            <span className="mount-line">
                                <span>授权挂载</span>
                                <ArrowRight size={15} />
                            </span>
                            <div className="isolated-tools">
                                <span className="isolated-tools-label">
                                    <Box size={12} />
                                    LINUX WORKSPACE
                                </span>
                                <div>
                                    <SquareTerminal size={16} />
                                    <span>Claude Code</span>
                                </div>
                                <div>
                                    <SquareTerminal size={16} />
                                    <span>Codex</span>
                                </div>
                                <div>
                                    <span className="illustration-prompt">
                                        &gt;_
                                    </span>
                                    <span>Linux 终端</span>
                                </div>
                            </div>
                        </div>
                        <span className="feature-footnote">
                            目录按需授权，不挂载 Docker 管理接口。
                        </span>
                    </article>
                    <article
                        className="feature-card feature-identity"
                        data-reveal
                    >
                        <span className="card-index mono">
                            02 / IDENTITY MATTERS
                        </span>
                        <div className="identity-art" aria-hidden="true">
                            <div className="identity-ring ring-one" />
                            <div className="identity-ring ring-two" />
                            <Fingerprint />
                            <span className="identity-point point-a" />
                            <span className="identity-point point-b" />
                        </div>
                        <div className="feature-copy">
                            <h3>
                                一个身份，
                                <br />
                                一份登录状态。
                            </h3>
                            <p>
                                为工作区选择独立
                                Profile。工具账号、Cookie、Storage
                                与下载按身份保留，浏览器不继承本机登录资料。
                            </p>
                        </div>
                        <TextLink href={docs.workspaces}>了解身份隔离</TextLink>
                    </article>
                    <article
                        className="feature-card feature-verification"
                        data-reveal
                    >
                        <div>
                            <span className="card-index mono">
                                03 / REVIEW BEFORE YOU RUN
                            </span>
                            <h3>
                                先核对出口。
                                <br />
                                <span>再开始工作。</span>
                            </h3>
                            <p>
                                线路与落地分别核验，由你确认后启用。运行期间检测到连接、出口或拓扑异常，停止本环境。
                            </p>
                        </div>
                        <div className="verification-pair">
                            <div>
                                <span className="verification-number mono">
                                    01
                                </span>
                                <div>
                                    <strong>线路出口</strong>
                                    <span>确认第一跳路径</span>
                                </div>
                                <CircleDot size={16} />
                            </div>
                            <span className="verification-rule" />
                            <div>
                                <span className="verification-number mono">
                                    02
                                </span>
                                <div>
                                    <strong>落地出口</strong>
                                    <span>确认最终出口</span>
                                </div>
                                <CircleDot size={16} />
                            </div>
                        </div>
                    </article>
                </div>
            </div>
        </section>
    );
}
