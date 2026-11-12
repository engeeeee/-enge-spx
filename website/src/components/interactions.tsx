"use client";

import {
    createContext,
    useContext,
    useEffect,
    useRef,
    useState,
    type ReactNode,
    type CSSProperties,
} from "react";
import {
    ArrowDownToLine,
    ArrowLeft,
    ArrowRight,
    ArrowUpRight,
    Check,
    Expand,
    Menu,
    X,
    ZoomIn,
    ZoomOut,
} from "lucide-react";
import {
    asset,
    docs,
    navigation,
    product,
    screenshots,
    type ScreenshotId,
} from "@/lib/content";

const Gallery = createContext<(id: ScreenshotId) => void>(() => {});

export function SiteInteractions({ children }: { children: ReactNode }) {
    const [selected, setSelected] = useState<ScreenshotId>("overview");
    const [reading, setReading] = useState(false);
    const dialog = useRef<HTMLDialogElement>(null);
    const picture = screenshots.find((item) => item.id === selected)!;
    const change = (direction: number) =>
        setSelected(
            (id) =>
                screenshots[
                    (screenshots.findIndex((s) => s.id === id) +
                        direction +
                        screenshots.length) %
                        screenshots.length
                ].id,
        );

    useEffect(() => {
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches)
            return;
        const observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries)
                    if (entry.isIntersecting) {
                        entry.target.removeAttribute("data-pending");
                        observer.unobserve(entry.target);
                    }
            },
            { threshold: 0.09 },
        );
        document.querySelectorAll("[data-reveal]").forEach((element) => {
            if (element.getBoundingClientRect().top > window.innerHeight * 0.95)
                element.setAttribute("data-pending", "true");
            observer.observe(element);
        });
        return () => observer.disconnect();
    }, []);

    return (
        <Gallery.Provider
            value={(id) => {
                setSelected(id);
                setReading(false);
                dialog.current?.showModal();
            }}
        >
            {children}
            <dialog
                ref={dialog}
                className="screenshot-dialog"
                aria-labelledby="screenshot-dialog-title"
                onClick={(event) => {
                    if (event.target === event.currentTarget)
                        dialog.current?.close();
                }}
                onKeyDown={(event) => {
                    if (reading) return;
                    if (event.key === "ArrowRight") change(1);
                    if (event.key === "ArrowLeft") change(-1);
                }}
            >
                <div className="gallery-inner">
                    <div className="gallery-toolbar">
                        <div>
                            <span className="eyebrow">
                                WINDOWS · {product.screenshotVersion}
                            </span>
                            <h2 id="screenshot-dialog-title">
                                {picture.title}
                            </h2>
                        </div>
                        <div className="gallery-view-controls">
                            <button
                                className="gallery-reading-button"
                                aria-pressed={reading}
                                onClick={() => setReading((value) => !value)}
                            >
                                {reading ? (
                                    <ZoomOut size={15} />
                                ) : (
                                    <ZoomIn size={15} />
                                )}
                                {reading ? "适应窗口" : "放大阅读"}
                            </button>
                            <a
                                className="gallery-original"
                                href={asset(picture.source)}
                                target="_blank"
                                rel="noreferrer"
                            >
                                高清原图 <ArrowUpRight size={13} />
                            </a>
                            <button
                                className="icon-button"
                                onClick={() => dialog.current?.close()}
                                aria-label="关闭截图"
                            >
                                <X />
                            </button>
                        </div>
                    </div>
                    <div
                        key={selected}
                        className={`gallery-image-viewport ${reading ? "is-reading" : ""}`}
                        tabIndex={0}
                        style={
                            {
                                "--shot-width": `${picture.width}px`,
                                "--shot-height": `${picture.height}px`,
                            } as CSSProperties
                        }
                        aria-label="高清软件截图，放大后可滚动阅读"
                    >
                        <img
                            src={asset(picture.source)}
                            width={picture.width * picture.pixelRatio}
                            height={picture.height * picture.pixelRatio}
                            alt={picture.alt}
                            className="gallery-image"
                        />
                    </div>
                    <div className="gallery-bottom">
                        <div className="gallery-select">
                            {screenshots.map((item) => (
                                <button
                                    key={item.id}
                                    onClick={() => setSelected(item.id)}
                                    aria-pressed={item.id === selected}
                                >
                                    {item.title}
                                </button>
                            ))}
                        </div>
                        <div className="gallery-arrows">
                            <button
                                className="icon-button"
                                onClick={() => change(-1)}
                                aria-label="上一张截图"
                            >
                                <ArrowLeft />
                            </button>
                            <button
                                className="icon-button"
                                onClick={() => change(1)}
                                aria-label="下一张截图"
                            >
                                <ArrowRight />
                            </button>
                        </div>
                    </div>
                    <p className="gallery-caption">
                        Windows 原生 {picture.pixelRatio}× 截图 ·{" "}
                        {picture.width * picture.pixelRatio} ×{" "}
                        {picture.height * picture.pixelRatio} ·{" "}
                        <a
                            href={docs.screenshots}
                            target="_blank"
                            rel="noreferrer"
                        >
                            截图来源 <ArrowUpRight size={12} />
                        </a>
                    </p>
                </div>
            </dialog>
        </Gallery.Provider>
    );
}

export function Screenshot({
    id,
    className = "",
    priority = false,
    caption = false,
}: {
    id: ScreenshotId;
    className?: string;
    priority?: boolean;
    caption?: boolean;
}) {
    const open = useContext(Gallery);
    const item = screenshots.find((s) => s.id === id)!;
    return (
        <figure className={`product-shot ${className}`}>
            <button
                className="shot-button"
                onClick={() => open(id)}
                aria-label={`放大查看${item.title}真实截图`}
            >
                <img
                    src={asset(item.source)}
                    alt={item.alt}
                    width={item.width}
                    height={item.height}
                    loading={priority ? "eager" : "lazy"}
                    fetchPriority={priority ? "high" : "auto"}
                    decoding="async"
                />
                <span className="shot-zoom">
                    <Expand size={14} />
                    <span>查看高清原图</span>
                </span>
            </button>
            {caption && (
                <figcaption>
                    <span className="tiny-dot" /> Windows 原生界面 · v
                    {product.screenshotVersion}{" "}
                    <span className="caption-separator">/</span>{" "}
                    未配置账号与节点
                </figcaption>
            )}
        </figure>
    );
}

export function HeroVisual() {
    return (
        <div className="hero-visual">
            <div className="hero-orbit orbit-one" aria-hidden="true" />
            <div className="hero-orbit orbit-two" aria-hidden="true" />
            <div className="hero-cross cross-one" aria-hidden="true">
                +
            </div>
            <div className="hero-cross cross-two" aria-hidden="true">
                +
            </div>
            <div className="hero-frame">
                <Screenshot id="overview" priority />
                <div className="hero-underlabel">
                    <span>YOUR PROJECT. ITS OWN WORKSPACE.</span>
                    <span>WINDOWS / NATIVE 3×</span>
                </div>
            </div>
        </div>
    );
}

export function Navigation() {
    const dialog = useRef<HTMLDialogElement>(null);
    const [active, setActive] = useState("");
    const [scrolled, setScrolled] = useState(false);
    useEffect(() => {
        const scroll = () => setScrolled(window.scrollY > 24);
        scroll();
        window.addEventListener("scroll", scroll, { passive: true });
        const observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries)
                    if (entry.isIntersecting) setActive(entry.target.id);
            },
            { rootMargin: "-15% 0px -60% 0px" },
        );
        navigation.forEach(({ id }) => {
            const element = document.getElementById(id);
            if (element) observer.observe(element);
        });
        return () => {
            window.removeEventListener("scroll", scroll);
            observer.disconnect();
        };
    }, []);
    return (
        <>
            <a className="skip-link" href="#main">
                跳到主要内容
            </a>
            <header className={`site-header ${scrolled ? "is-scrolled" : ""}`}>
                <div className="nav-inner">
                    <a href="#" className="brand" aria-label="ENGE SPX 首页">
                        <img
                            src={asset("/brand/logo.svg")}
                            alt=""
                            width="35"
                            height="35"
                        />
                        <span>ENGE SPX</span>
                    </a>
                    <nav className="desktop-nav" aria-label="主要导航">
                        {navigation.map(({ id, label }) => (
                            <a
                                key={id}
                                href={`#${id}`}
                                aria-current={
                                    active === id ? "location" : undefined
                                }
                            >
                                {label}
                            </a>
                        ))}
                        <a
                            href={docs.quickstart}
                            target="_blank"
                            rel="noreferrer"
                        >
                            文档 <ArrowUpRight size={12} />
                        </a>
                    </nav>
                    <div className="nav-actions">
                        <a
                            className="nav-github"
                            href={product.repository}
                            target="_blank"
                            rel="noreferrer"
                        >
                            GitHub <ArrowUpRight size={13} />
                        </a>
                        <a
                            className="button button-small button-primary nav-download"
                            href={product.installer}
                        >
                            <ArrowDownToLine size={15} />
                            下载 Windows 版
                        </a>
                        <button
                            className="menu-button icon-button"
                            aria-label="打开导航菜单"
                            aria-haspopup="dialog"
                            onClick={() => dialog.current?.showModal()}
                        >
                            <Menu />
                        </button>
                    </div>
                </div>
            </header>
            <dialog ref={dialog} className="mobile-menu" aria-label="导航菜单">
                <div className="mobile-menu-head">
                    <a
                        href="#"
                        className="brand"
                        onClick={() => dialog.current?.close()}
                    >
                        <img
                            src={asset("/brand/logo.svg")}
                            alt=""
                            width="35"
                            height="35"
                        />
                        <span>ENGE SPX</span>
                    </a>
                    <button
                        className="icon-button"
                        onClick={() => dialog.current?.close()}
                        aria-label="关闭导航菜单"
                    >
                        <X />
                    </button>
                </div>
                <nav>
                    {navigation.map(({ id, label }, i) => (
                        <a
                            key={id}
                            href={`#${id}`}
                            onClick={() => dialog.current?.close()}
                        >
                            <span className="mono">0{i + 1}</span>
                            {label}
                            <ArrowUpRight />
                        </a>
                    ))}
                    <a
                        href={docs.quickstart}
                        target="_blank"
                        rel="noreferrer"
                        onClick={() => dialog.current?.close()}
                    >
                        <span className="mono">05</span>使用文档
                        <ArrowUpRight />
                    </a>
                </nav>
                <a className="button button-primary" href={product.installer}>
                    <ArrowDownToLine size={17} />
                    下载 Windows 安装版
                </a>
                <p>v{product.version} · Windows x64</p>
            </dialog>
        </>
    );
}

export function CopyChecksum() {
    const [copied, setCopied] = useState(false);
    const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
    useEffect(
        () => () => {
            if (timer.current) clearTimeout(timer.current);
        },
        [],
    );
    return (
        <button
            className="text-button checksum-button"
            onClick={async () => {
                try {
                    await navigator.clipboard.writeText(
                        product.installerSha256,
                    );
                    setCopied(true);
                    if (timer.current) clearTimeout(timer.current);
                    timer.current = setTimeout(() => setCopied(false), 2500);
                } catch {
                    window.open(
                        product.release,
                        "_blank",
                        "noopener,noreferrer",
                    );
                }
            }}
        >
            <Check size={13} />
            <span aria-live="polite">
                {copied ? "安装版 SHA-256 已复制" : "复制安装版 SHA-256"}
            </span>
        </button>
    );
}
