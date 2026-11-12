import { Fingerprint, FolderOpen, SquareTerminal } from "lucide-react";
import { Screenshot } from "@/components/interactions";
import { SectionLabel, TextLink } from "@/components/section-ui";
import { docs } from "@/lib/content";

export function WorkspaceSection() {
    return (
        <section id="workspace" className="section workspace-section">
            <div className="container">
                <div className="workspace-heading" data-reveal>
                    <SectionLabel number="03">从一个项目开始</SectionLabel>
                    <h2>
                        选择你的项目。
                        <br />
                        <span className="muted-heading">
                            定义它的工作方式。
                        </span>
                    </h2>
                    <p>
                        本地目录、账号身份、访问权限与工具入口，
                        <br />
                        在同一个工作区里安排妥当。
                    </p>
                </div>
                <div className="workspace-stage" data-reveal>
                    <div className="workspace-stage-grid" aria-hidden="true" />
                    <span
                        className="stage-corner stage-corner-a"
                        aria-hidden="true"
                    />
                    <span
                        className="stage-corner stage-corner-b"
                        aria-hidden="true"
                    />
                    <Screenshot
                        id="workspace"
                        className="workspace-shot"
                        caption
                    />
                </div>
                <div className="workspace-principles" data-reveal>
                    <article>
                        <span className="principle-icon">
                            <FolderOpen size={20} />
                        </span>
                        <span className="mono principle-number">01</span>
                        <h3>只给必要的目录</h3>
                        <p>
                            选中具体项目，显式授予只读或读写权限。项目保存在原位置，工具在容器中访问。
                        </p>
                    </article>
                    <article>
                        <span className="principle-icon">
                            <Fingerprint size={20} />
                        </span>
                        <span className="mono principle-number">02</span>
                        <h3>身份由你明确选择</h3>
                        <p>
                            独立身份分别保存工具账号与浏览器资料。默认共享模式兼容旧资料，切换项目不自动切身份。
                        </p>
                    </article>
                    <article>
                        <span className="principle-icon">
                            <SquareTerminal size={20} />
                        </span>
                        <span className="mono principle-number">03</span>
                        <h3>使用熟悉的工具</h3>
                        <p>
                            从同一页面进入 Claude Code、Codex、Linux 终端和
                            Chromium；终端窗口可用自己的程序承载。
                        </p>
                    </article>
                </div>
                <div className="section-tail">
                    <span>浏览器不挂载项目目录或工具账号卷。</span>
                    <TextLink href={docs.workspaces}>
                        工作区身份与项目授权
                    </TextLink>
                </div>
            </div>
        </section>
    );
}
