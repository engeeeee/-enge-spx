export const product = {
    name: "ENGE SPX",
    version: "0.13.3",
    published: "2026-11-12",
    site: "https://enge1337.cn",
    repository: "https://github.com/engeeeee/ENGE-SPX",
    release:
        "https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.13.3-windows",
    installer:
        "https://github.com/engeeeee/ENGE-SPX/releases/download/v0.13.3-windows/ENGE-SPX-Windows-x64-0.13.3-Setup.exe",
    portable:
        "https://github.com/engeeeee/ENGE-SPX/releases/download/v0.13.3-windows/ENGE-SPX-Windows-x64-0.13.3-Portable.zip",
    installerSha256:
        "a314207f8376aabce1ec8bcbd54948501601d9977a1eded79fbf8b1bacccca51",
    portableSha256:
        "93572aad3816e267709553dd28cb7ee8fdee4bdfb318ab3c6779afdbc0c4cd50",
    screenshotVersion: "0.13.2",
} as const;

export const docs = {
    quickstart: `${product.repository}/blob/main/docs/quickstart.zh-CN.md`,
    proxies: `${product.repository}/blob/main/docs/proxies.zh-CN.md`,
    protocols: `${product.repository}/blob/main/docs/proxy-p1.zh-CN.md`,
    security: `${product.repository}/blob/main/docs/security-model.zh-CN.md`,
    workspaces: `${product.repository}/blob/main/docs/workspaces.zh-CN.md`,
    resources: `${product.repository}/blob/main/docs/resources.zh-CN.md`,
    recording: `${product.repository}/blob/main/docs/field-recording.zh-CN.md`,
    diagnostics: `${product.repository}/blob/main/docs/network-diagnostics.zh-CN.md`,
    exit: `${product.repository}/blob/main/docs/exit.zh-CN.md`,
    screenshots: `${product.repository}/blob/main/docs/screenshots/README.md`,
    license: `${product.repository}/blob/main/LICENSE`,
    issues: `${product.repository}/issues`,
    docker: "https://docs.docker.com/desktop/setup/install/windows-install/",
} as const;

export const navigation = [
    { id: "features", label: "产品能力" },
    { id: "architecture", label: "网络路径" },
    { id: "workspace", label: "项目工作区" },
    { id: "resources", label: "资源管理" },
] as const;

export const screenshots = [
    {
        id: "overview",
        title: "工作台",
        alt: "ENGE SPX 0.13.2 Windows 工作台：一键准备、线路和落地出口、工作区路径",
        source: "/screenshots/overview-web@3x.png",
        width: 960,
        height: 840,
        pixelRatio: 3,
    },
    {
        id: "workspace",
        title: "项目工作区",
        alt: "真实项目工作区界面：本地目录、身份授权、Claude Code、Codex、终端及 Chromium 入口",
        source: "/screenshots/workspace-web@3x.png",
        width: 1120,
        height: 1050,
        pixelRatio: 3,
    },
    {
        id: "connection",
        title: "连接与代理",
        alt: "真实连接与代理界面：分别选择落地、前置线路和本机代理",
        source: "/screenshots/connection-web@3x.png",
        width: 840,
        height: 1050,
        pixelRatio: 3,
    },
    {
        id: "resources",
        title: "资源与性能",
        alt: "真实资源预算界面：网关、会话、CLI 与 Chromium 的 CPU、内存上限",
        source: "/screenshots/resources-web@3x.png",
        width: 840,
        height: 1000,
        pixelRatio: 3,
    },
] as const;

export type ScreenshotId = (typeof screenshots)[number]["id"];
export const asset = (path: string) =>
    `${process.env.NEXT_PUBLIC_BASE_PATH || ""}${path}`;

export const faqs = [
    {
        question: "这是 Windows 虚拟机吗？",
        answer: "Windows 运行 ENGE SPX 控制界面和你选择的终端窗口。Claude Code、Codex 和 Chromium 实际运行在 Docker Linux 容器中，通常由 Docker Desktop / WSL2 承载，并不是一套独立安装的 Windows 虚拟机。",
    },
    {
        question: "我已经在用 v2rayN，可以继续用吗？",
        answer: "可以。选择本机 v2ray 兼容模式即可沿用现有客户端，外部客户端的按目标分流仍由你配置。也可以导入受支持的加密线路，由 ENGE SPX 固定“线路 → 落地”路径；两种模式的控制边界不同。",
    },
    {
        question: "不同项目会共享账号和浏览器登录状态吗？",
        answer: "默认共享模式保留旧资料，同一身份内的项目会共享账号。需要分开时，请显式创建并绑定不同 Workspace Profile；工具账号、Cookie、Local Storage 和下载按身份保留。切换项目本身不会自动切换身份。",
    },
    {
        question: "打开软件就会启动 Docker 吗？",
        answer: "不会。打开软件只检查状态，由你点击“一键准备环境”或“启动并检测”后才启动 Docker。X 隐藏到托盘；真正退出默认先停止工作区，也可以保存同时正常关闭 Docker Desktop 的偏好。",
    },
    {
        question: "可以把数据放到 D 盘吗？",
        answer: "可以迁移应用配置、日志和下载缓存。Docker 的镜像、容器、数据卷则使用单独的数据盘迁移助手，并在 Docker Desktop 中应用位置变更。这两项迁移相互独立，项目目录也保留在你选择的位置。",
    },
] as const;
