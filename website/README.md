# ENGE SPX 官方网站

正式网站：**https://enge1337.cn/**

Next.js 静态导出、React、TypeScript、Lucide 与 CSS 设计变量。官网介绍实际的 Windows AI 编程工作台，生产环境由 Nginx 直接提供 HTML/CSS/JS，不需要新增 Node 常驻服务。

## 本地运行与构建

需要 Node.js 20.9+：

```bash
cd website
npm ci
npm run dev
```

打开 `http://127.0.0.1:4173`。生成静态站：

```bash
npm run build
```

产物为 `out/`。构建包含 TypeScript 检查；`npm run typecheck` 可单独执行。依赖版本由 `package-lock.json` 固定。

## 源码与内容位置

```text
src/app/page.tsx                  页面组合与结构化 SEO 数据
src/app/layout.tsx                站点元数据、字体和全局交互
src/app/globals.css               颜色、排版、布局、响应式和动效
src/components/sections/          八个内容分区与 Footer
src/components/architecture.tsx   两种接入模式与网络路径示意
src/components/interactions.tsx   导航、高清截图浏览器、滚动呈现
src/lib/content.ts               版本、真实下载地址、文档、截图、FAQ
public/brand/logo.svg             仓库原始 Logo
public/screenshots/               原始 Windows 截图与来源清单
scripts/capture-previews.mjs      短浏览器检查和实际网页预览
scripts/deploy-static.py          Linux 上的静态目录原子发布
```

更新软件版本时，修改 `src/lib/content.ts` 中的版本、发布日期、Releases 与附件地址、SHA-256，并同步 `sections/faq.tsx` 的最新版本说明。下载地址应先从真实 [GitHub Releases](https://github.com/engeeeee/ENGE-SPX/releases)核对。截图版本单独标识，不用新版本号描述旧界面。

## 软件截图的真实性与清晰度

软件窗口直接使用原生 Windows 3× DPI 截图，最高 **3360×3150 PNG**。真实窗口的逻辑尺寸按页面展示空间选择，让软件文字少被缩小，而非简单把原图插值放大。工作台、连接和资源页使用软件原有紧凑导航；项目页使用完整导航。像素、逻辑尺寸与 SHA-256 见 `public/screenshots/capture-web-3x.json`，旧 1× / 2× 图片保留。

在 1920px、100% 缩放的普通 DPI 桌面，四张软件截图按原始逻辑宽度展示，避免额外缩字。普通 DPI 屏幕上的截图保持正视，首屏只展示一个软件窗口，以柔和阴影区分前后；高 DPI 屏幕保留克制透视。首屏只裁切底部，图片内部内容不修改。点击可适应窗口查看、按各图的原始逻辑尺寸滚动阅读，或打开完整高清 PNG。网页中的网络图与挂载图是明确的架构示意，不是软件界面。

当前资料对应 ENGE SPX **0.13.2**。软件截图使用空配置，保留尚未确认连接时禁用的工具按钮。事实、设计与边界见 [DESIGN.md](DESIGN.md)，完整产品说明见 [项目 README](https://github.com/engeeeee/ENGE-SPX#readme)。

## 预览与简短检查

按维护者要求，仅做构建、主要链接/交互及桌面/手机排版检查，没有运行长时间回归。

开发服务器运行时，可生成真实网页截图：

```bash
npx playwright install chromium
npm run preview:capture
```

也可设置 `PREVIEW_URL=https://enge1337.cn` 截取正式网站。已有 Chromium 时可用 `CHROMIUM_PATH` 指定可执行文件；`CAPTURE_ONLY=1` 只更新预览，不重复交互检查。预览写入 `previews/`，包括六个主要分区、桌面长图、1920px、平板、移动端。捕获时启用减少动态效果以固定画面，线上尊重访问者的 `prefers-reduced-motion`。

线上交付入口：[网页预览](https://enge1337.cn/previews/)、[完整源码 ZIP](https://enge1337.cn/deliverables/ENGE-SPX-website-source.zip)、[全部预览 ZIP](https://enge1337.cn/deliverables/ENGE-SPX-website-previews.zip)。

## 部署

### 当前服务器 / Nginx

域名、TLS、Cloudflare 沿用已有设置。将已有 HTTPS 虚拟主机的站点内容指向 `/srv/enge-spx/current`；示例见 [deploy/nginx-static.conf.example](deploy/nginx-static.conf.example)。首次切换前备份旧配置与数据，执行 `nginx -t` 后再 reload。

后续发布：

```bash
npm ci
npm run build
python3 scripts/deploy-static.py --root /srv/enge-spx
```

脚本创建新 release、保留上次构建的哈希静态资源并原子切换 `current`，不会删除旧目录或修改 Nginx。回滚时将 `current` 原子指回上个 release。旧站点的系统配置备份由服务器运维单独保存，不进入源码归档。

### 其它静态平台

| 平台 | 设置 |
| --- | --- |
| Cloudflare Pages | 根目录 `website`，构建 `npm run build`，输出 `out` |
| Vercel | 根目录 `website`；按 Next.js 静态导出构建 |
| GitHub Pages | 构建 `out` 并发布；项目路径可在构建前设置 `NEXT_PUBLIC_BASE_PATH=/ENGE-SPX` |
| 任意静态服务器 | 提供 `out/`，未知路由返回 `404.html`，不要改写成首页 |

已有官网的 canonical 为 `https://enge1337.cn/`。迁移域名时更新 `src/lib/content.ts` 的 `site` 与相应 SEO 配置。`public/.nojekyll` 用于保留 GitHub Pages 的 `_next` 目录。

## 许可

网站源码沿用项目的 **PolyForm Noncommercial 1.0.0**，见 [LICENSE](LICENSE)。第三方依赖与 Geist 字体声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，相应许可证文本位于 `public/licenses/`。
