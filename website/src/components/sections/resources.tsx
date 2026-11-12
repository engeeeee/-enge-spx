import { ArrowUpRight, Cpu, PanelsTopLeft, Waypoints } from "lucide-react";
import { Screenshot } from "@/components/interactions";
import { SectionLabel, TextLink } from "@/components/section-ui";
import { docs } from "@/lib/content";

export function ResourcesSection() {
    return (
        <section id="resources" className="section resources-section">
            <div className="container resources-layout">
                <div className="resources-copy" data-reveal>
                    <SectionLabel number="04">按需要运行</SectionLabel>
                    <h2>
                        让资源，
                        <br />
                        用在正在做的
                        <br />
                        <span className="clay-text">事情上。</span>
                    </h2>
                    <p className="resource-intro">
                        网关、会话、CLI 项目与 Chromium，分别设置 CPU
                        和内存上限。正常与低资源模式之间，自由选择适合当前工作的预算。
                    </p>
                    <div className="resource-details">
                        <div>
                            <Cpu size={18} />
                            <div>
                                <h3>组件预算，项目也能单独设</h3>
                                <p>
                                    每个环境有自己的上限，多项目按各自预算运行。
                                </p>
                            </div>
                        </div>
                        <div>
                            <PanelsTopLeft size={18} />
                            <div>
                                <h3>需要时，再打开浏览器</h3>
                                <p>
                                    低资源模式默认按需启动；也可停止
                                    Chromium，保留 CLI。
                                </p>
                            </div>
                        </div>
                        <div>
                            <Waypoints size={18} />
                            <div>
                                <h3>看清占用来源</h3>
                                <p>
                                    区分应用、容器与
                                    WSL2，按需记录资源或检查网络。
                                </p>
                            </div>
                        </div>
                    </div>
                    <TextLink href={docs.resources}>了解资源管理</TextLink>
                    <p className="resource-note">
                        预算是上限，不是预留或实测占用；降低预算可能影响编译速度。安全监测独立运行。
                    </p>
                </div>
                <div className="resources-visual" data-reveal>
                    <div className="resource-halo" aria-hidden="true" />
                    <div className="resource-visual-label mono">
                        <span>MAKE ROOM FOR WHAT MATTERS.</span>
                        <span>CPU / MEMORY</span>
                    </div>
                    <Screenshot id="resources" className="resources-shot" />
                    <div className="resource-bottom-note">
                        <span>
                            <span className="tiny-dot" />
                            真实预算设置界面
                        </span>
                        <span>
                            可为当前项目设置独立预算 <ArrowUpRight size={12} />
                        </span>
                    </div>
                </div>
            </div>
        </section>
    );
}
