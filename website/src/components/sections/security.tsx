import { Fingerprint, Layers3, LockKeyhole, ShieldCheck } from "lucide-react";
import { SectionLabel, TextLink } from "@/components/section-ui";
import { docs } from "@/lib/content";

export function SecuritySection() {
    return (
        <section className="security-section" aria-labelledby="security-title">
            <div className="container security-inner" data-reveal>
                <div className="security-heading">
                    <span className="security-mark">
                        <ShieldCheck size={31} />
                    </span>
                    <SectionLabel number="05">让信任有据可查</SectionLabel>
                    <h2 id="security-title">
                        边界写清楚。
                        <br />
                        <span className="muted-heading">才值得放心使用。</span>
                    </h2>
                    <TextLink href={docs.security}>阅读隔离与安全模型</TextLink>
                </div>
                <div className="security-facts">
                    <article>
                        <LockKeyhole size={18} />
                        <div>
                            <h3>沙箱与最小权限</h3>
                            <p>
                                Chromium 以非 root 运行，验证命名空间与 seccomp
                                沙箱；初始化失败不退回无沙箱模式。
                            </p>
                        </div>
                    </article>
                    <article>
                        <Fingerprint size={18} />
                        <div>
                            <h3>当前用户的凭据保护</h3>
                            <p>
                                Windows DPAPI
                                保护应用代理配置与内部令牌，减少静态存储和意外暴露。
                            </p>
                        </div>
                    </article>
                    <article>
                        <Layers3 size={18} />
                        <div>
                            <h3>隔离仍有信任边界</h3>
                            <p>
                                容器依赖宿主、Docker 与
                                WSL2。只读仍能读取项目密钥，读写会允许修改；请按需授权。
                            </p>
                        </div>
                    </article>
                    <p className="security-transparency">
                        源码公开 · 非商业许可 · 尚未经过独立安全审计
                    </p>
                </div>
            </div>
        </section>
    );
}
