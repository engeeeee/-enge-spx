// One short browser pass plus actual rendered-page previews; no long regression.
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import path from "node:path";

const origin = process.env.PREVIEW_URL || "http://127.0.0.1:4173";
const output = path.resolve("previews");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_PATH
        ? { executablePath: process.env.CHROMIUM_PATH }
        : {}),
});
const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const captures = [];
const capture = async (file, label, target = page, options = {}) => {
    await page.evaluate(() => {
        document.activeElement?.blur();
        window.scrollTo(0, 0);
    });
    if (target === page) {
        await page.screenshot({ path: path.join(output, file), ...options });
    } else {
        const rect = await target.boundingBox();
        await page.screenshot({
            path: path.join(output, file),
            fullPage: true,
            clip: { x: 0, y: rect.y, width: 1440, height: rect.height },
        });
    }
    captures.push({ file, label });
};
try {
    await page.goto(origin, { waitUntil: "networkidle" });
    await page.evaluate(() => document.fonts.ready);
    assert.match(await page.title(), /ENGE SPX/);
    if (process.env.CAPTURE_ONLY !== "1") {
        assert.equal(
            await page
                .locator('a[href$="-Setup.exe"]')
                .first()
                .getAttribute("href"),
            (await readFile("src/lib/content.ts", "utf8")).match(
                /installer:\s*"([^\"]+)"/,
            )[1],
        );
        assert.equal(await page.locator('a[href$="-Portable.zip"]').count(), 1);
        const anchors = await page
            .locator('a[href^="#"]')
            .evaluateAll((links) =>
                links
                    .map((a) => a.getAttribute("href"))
                    .filter((h) => h !== "#"),
            );
        for (const anchor of new Set(anchors))
            assert.equal(
                await page.locator(anchor).count(),
                1,
                `Missing anchor ${anchor}`,
            );

        await page.getByRole("tab", { name: "本机 v2ray 兼容" }).click();
        assert.equal(
            await page.locator("#local-tab").getAttribute("aria-selected"),
            "true",
        );
        assert.match(
            await page.locator("#route-panel").innerText(),
            /外部客户端/,
        );
        await page.locator("#local-tab").press("Home");
        assert.equal(
            await page.locator("#managed-tab").getAttribute("aria-selected"),
            "true",
        );
        assert.equal(await page.locator(".landing-node").count(), 1);
        assert.equal(await page.locator(".landing-options > span").count(), 3);

        await page
            .getByRole("button", { name: "放大查看工作台真实截图" })
            .click();
        assert.equal(
            await page.locator(".screenshot-dialog").evaluate((d) => d.open),
            true,
        );
        await page.keyboard.press("ArrowRight");
        assert.match(
            await page.locator("#screenshot-dialog-title").innerText(),
            /项目工作区/,
        );
        await page.keyboard.press("Escape");
        assert.equal(
            await page.locator(".screenshot-dialog").evaluate((d) => d.open),
            false,
        );
        await page.locator(".faq-list summary").first().click();
        assert.equal(
            await page
                .locator(".faq-list details")
                .first()
                .getAttribute("open"),
            "",
        );
        await page.locator(".faq-list summary").first().click();
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    await capture("hero-desktop.png", "首页首屏 · 1440px");
    for (const [id, file, label] of [
        ["features", "features.png", "核心功能"],
        ["architecture", "architecture.png", "网络路径与代理架构"],
        ["workspace", "workspace.png", "项目工作区"],
        ["resources", "resources.png", "资源与性能"],
        ["get-started", "get-started.png", "快速开始与下载"],
    ]) {
        const section = page.locator(`#${id}`);
        await section.scrollIntoViewIfNeeded();
        await page.waitForTimeout(120);
        for (const image of await section.locator("img").all())
            await image.evaluate((img) => {
                img.loading = "eager";
                return img.decode();
            });
        await capture(file, label, section);
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    await capture("desktop-full.png", "完整桌面端网页", page, {
        fullPage: true,
    });
    await page.setViewportSize({ width: 1920, height: 1080 });
    await capture("desktop-1920.png", "宽屏首页 · 1920px");
    await page.getByRole("button", { name: "放大查看工作台真实截图" }).click();
    await page.getByRole("button", { name: "放大阅读" }).click();
    await capture("high-resolution-reading.png", "原始逻辑尺寸阅读 · 1080p");
    await page.keyboard.press("Escape");
    await page.setViewportSize({ width: 768, height: 1024 });
    assert(
        (await page.evaluate(() => document.documentElement.scrollWidth)) <=
            769,
        "Tablet overflows horizontally",
    );
    await capture("tablet.png", "平板预览 · 768px");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => window.scrollTo(0, 0));
    if (process.env.CAPTURE_ONLY !== "1") {
        await page.getByRole("button", { name: "打开导航菜单" }).click();
        assert.equal(
            await page.locator(".mobile-menu").evaluate((d) => d.open),
            true,
        );
        await page.getByRole("button", { name: "关闭导航菜单" }).click();
        assert.equal(
            await page.locator(".mobile-menu").evaluate((d) => d.open),
            false,
        );
    }
    assert(
        (await page.evaluate(() => document.documentElement.scrollWidth)) <=
            391,
        "Mobile overflows horizontally",
    );
    await capture("mobile-home.png", "手机首页 · 390px");
    await capture("mobile-full.png", "完整移动端网页", page, {
        fullPage: true,
    });
    await page.setViewportSize({ width: 1200, height: 630 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: "public/og.png" });
    assert.deepEqual(errors, [], "Browser runtime errors");
    await writeFile(
        path.join(output, "verification.json"),
        JSON.stringify(
            {
                source: origin,
                browser: await browser.version(),
                capturedAt: new Date().toISOString(),
                checks:
                    process.env.CAPTURE_ONLY === "1"
                        ? [
                              "Live page capture only; prior interaction pass recorded separately",
                              "1440/1920/768/390 viewport previews",
                              "no page runtime errors",
                          ]
                        : [
                              "static page and title",
                              "real release download URLs",
                              "navigation anchors",
                              "network mode click and keyboard switch",
                              "single landing with three protocol alternatives",
                              "image zoom/next/Escape",
                              "FAQ",
                              "mobile menu",
                              "1440/1920/768/390 layouts",
                              "reduced-motion previews",
                              "no page runtime errors",
                          ],
                captures,
            },
            null,
            2,
        ) + "\n",
    );
    const cards = captures
        .map(
            ({ file, label }) =>
                `<a class="card" href="${file}"><img loading="lazy" src="${file}" alt="${label}"><span>${label}<small>PNG 原图 ↗</small></span></a>`,
        )
        .join("");
    await writeFile(
        path.join(output, "index.html"),
        `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>ENGE SPX 官网交付预览</title><style>*{box-sizing:border-box}body{margin:0;background:#191815;color:#eee7db;font-family:system-ui,sans-serif;padding:50px 24px}main{max-width:1200px;margin:auto}h1{font-size:32px;font-weight:550}p{color:#aaa193;line-height:1.8}a{color:#dca280;text-decoration:none}.links{display:flex;gap:24px;flex-wrap:wrap;margin:24px 0 36px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}.card{display:block;border:1px solid #50412f;border-radius:9px;overflow:hidden;background:#24221c}.card img{display:block;width:100%;height:300px;object-fit:cover;object-position:top}.card span{display:flex;justify-content:space-between;padding:18px 20px;color:#eee5d5;font-size:14px}.card small{font-size:11px;color:#a38b6b}@media(max-width:650px){.grid{grid-template-columns:1fr}.card img{height:270px}h1{font-size:26px}}</style></head><body><main><p>ENGE SPX / WEBSITE DELIVERY</p><h1>官网的每一面，都来自真实页面。</h1><p>以下是实际运行网页的浏览器截图，软件界面使用仓库 0.13.2 的原始 Windows 截图。页面预览启用系统“减少动态效果”以固定画面；线上版本保留克制的动效。</p><div class="links"><a href="/">打开正式网站 ↗</a><a href="/deliverables/ENGE-SPX-website-previews.zip">下载全部预览图</a><a href="/deliverables/ENGE-SPX-website-source.zip">下载完整网站源码</a></div><div class="grid">${cards}</div><p>截图生成于 ${new Date().toISOString()} · 桌面、平板与移动端</p></main></body></html>`,
    );
    console.log(
        JSON.stringify(
            { passed: true, captures: captures.length, output },
            null,
            2,
        ),
    );
} finally {
    await browser.close();
}
