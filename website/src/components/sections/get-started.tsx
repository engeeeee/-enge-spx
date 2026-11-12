import {
    ArrowDownToLine,
    ArrowUpRight,
    Box,
    HardDrive,
    Monitor,
    Network,
    SquareTerminal,
} from "lucide-react";
import { CopyChecksum } from "@/components/interactions";
import { SectionLabel, TextLink } from "@/components/section-ui";
import { asset, docs, product } from "@/lib/content";

export function GetStartedSection() {
    return (
        <section id="get-started" className="section getting-started">
            <div className="container">
                <div className="section-heading" data-reveal>
                    <div>
                        <SectionLabel number="06">从准备到开始</SectionLabel>
                        <h2>
                            四步。
                            <br />
                            <span className="muted-heading">
                                开始你的下一个项目。
                            </span>
                        </h2>
                    </div>
                    <TextLink href={docs.quickstart}>查看完整快速入门</TextLink>
                </div>
                <div className="start-steps" data-reveal>
                    {[
                        {
                            number: "01",
                            icon: Box,
                            title: "准备 Docker 环境",
                            text: "安装 Docker Desktop，完成 WSL2 与 Linux containers 初始化。使用 Docker Engine 28+。",
                            link: docs.docker,
                            action: "Docker 安装指南",
                        },
                        {
                            number: "02",
                            icon: ArrowDownToLine,
                            title: "安装，或完整解压",
                            text: "运行 ENGE SPX，点击“一键准备环境”，等待已有镜像复用或下载、校验并导入。",
                            link: product.release,
                            action: "获取 Windows 版",
                        },
                        {
                            number: "03",
                            icon: Network,
                            title: "选择线路与落地",
                            text: "配置加密第一跳与 SOCKS5 / HTTP(S) 落地，或选择本机 v2ray 兼容模式。",
                            link: docs.proxies,
                            action: "代理配置说明",
                        },
                        {
                            number: "04",
                            icon: SquareTerminal,
                            title: "核对出口，开始工作",
                            text: "确认线路与落地出口，选择项目与身份，然后打开 Claude Code、Codex 或浏览器。",
                            link: docs.quickstart,
                            action: "进入第一个工作区",
                        },
                    ].map((step) => (
                        <article className="start-step" key={step.number}>
                            <div className="step-top">
                                <span className="step-number mono">
                                    {step.number}
                                </span>
                                <step.icon size={21} />
                            </div>
                            <h3>{step.title}</h3>
                            <p>{step.text}</p>
                            <TextLink href={step.link}>{step.action}</TextLink>
                        </article>
                    ))}
                </div>
                <div id="download" className="download-panel" data-reveal>
                    <div className="download-decoration" aria-hidden="true">
                        <img
                            src={asset("/brand/logo.svg")}
                            alt=""
                            width="370"
                            height="370"
                        />
                    </div>
                    <div className="download-copy">
                        <span className="download-eyebrow mono">
                            A LITTLE SPACE. A BETTER WORKFLOW.
                        </span>
                        <h2>
                            把下一次专注，
                            <br />
                            留给你的项目。
                        </h2>
                        <p>下载 ENGE SPX，为 AI 编程准备一个自己的工作区。</p>
                        <div className="download-meta">
                            <span>v{product.version} 正式版</span>
                            <span>Windows x64</span>
                            <span>安装包无需额外 Python</span>
                        </div>
                    </div>
                    <div className="download-actions">
                        <a
                            className="button button-dark"
                            href={product.installer}
                        >
                            <ArrowDownToLine size={18} />
                            <span>下载 Windows 安装版</span>
                            <ArrowUpRight size={17} />
                        </a>
                        <a
                            className="button button-clay-outline"
                            href={product.portable}
                        >
                            <HardDrive size={17} />
                            <span>下载便携版 ZIP</span>
                            <ArrowUpRight size={17} />
                        </a>
                        <div className="download-secondary">
                            <a
                                href={product.release}
                                target="_blank"
                                rel="noreferrer"
                            >
                                全部版本与校验文件
                                <ArrowUpRight size={12} />
                            </a>
                            <CopyChecksum />
                        </div>
                    </div>
                </div>
                <p className="requirements-line">
                    <Monitor size={13} />
                    需要可运行 Linux containers 的 Docker Desktop / WSL2，Docker
                    Engine 28+。首次运行环境约 1 GB，由软件内获取；Windows
                    包当前未代码签名。
                </p>
            </div>
        </section>
    );
}
