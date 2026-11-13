import { ArrowRight, ArrowUpRight, ChevronDown } from "lucide-react";
import { SectionLabel, TextLink } from "@/components/section-ui";
import { docs, faqs, product } from "@/lib/content";

export function FaqSection() {
    return (
        <section className="section faq-section" id="faq">
            <div className="container faq-layout">
                <div className="faq-intro" data-reveal>
                    <SectionLabel number="07">
                        开始之前，也许你想知道
                    </SectionLabel>
                    <h2>
                        把问题，
                        <br />
                        <span className="muted-heading">先说清楚。</span>
                    </h2>
                    <p>关于工作区、账号和你的现有环境。</p>
                    <TextLink href={docs.issues}>
                        还有问题？在 GitHub 交流
                    </TextLink>
                    <a
                        className="release-note"
                        href={product.release}
                        target="_blank"
                        rel="noreferrer"
                    >
                        <span className="eyebrow">
                            LATEST RELEASE / {product.published}
                        </span>
                        <div>
                            <strong>v{product.version}</strong>
                            <ArrowUpRight size={18} />
                        </div>
                        <p>
                            修复 Docker 退出核验预算耗尽。
                            支持身份内更新 AI 工具，保留终端查看结果。
                        </p>
                        <span className="release-note-link">
                            查看更新记录
                            <ArrowRight size={13} />
                        </span>
                    </a>
                </div>
                <div className="faq-list" data-reveal>
                    {faqs.map((faq, i) => (
                        <details key={faq.question}>
                            <summary>
                                <span className="mono faq-number">
                                    0{i + 1}
                                </span>
                                <span>{faq.question}</span>
                                <ChevronDown size={17} />
                            </summary>
                            <p>{faq.answer}</p>
                        </details>
                    ))}
                </div>
            </div>
        </section>
    );
}
