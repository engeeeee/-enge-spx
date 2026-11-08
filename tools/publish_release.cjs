// Publish artifacts from the same successful CI run, scoped to the personal repo.
module.exports = async ({github, context, core}) => {
  const fs = require('node:fs');
  const path = require('node:path');
  const crypto = require('node:crypto');
  const {owner, repo} = context.repo;
  if (owner !== 'engeeeee' || repo !== 'ENGE-SPX' || context.ref !== 'refs/heads/main') {
    throw new Error('Publication is limited to the maintained ENGE SPX repository.');
  }
  const digest = async file => {
    const hash = crypto.createHash('sha256');
    for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
    return hash.digest('hex');
  };
  const manifests = fs.readdirSync('verified-runtime').filter(n => /^ENGE-SPX-Runtime-linux-amd64-\d+\.\d+\.\d+\.json$/.test(n));
  if (manifests.length !== 1) throw new Error('Expected one verified runtime manifest.');
  const metadata = JSON.parse(fs.readFileSync(path.join('verified-runtime', manifests[0]), 'utf8'));
  const version = metadata.version;
  if (!/^\d+\.\d+\.\d+$/.test(version) || metadata.platform !== 'linux/amd64' || metadata.schema !== 1) throw new Error('Invalid release manifest.');
  const archive = `ENGE-SPX-Runtime-linux-amd64-${version}.tar.gz`;
  if (metadata.filename !== archive) throw new Error('Unexpected runtime filename.');
  const runtimePath = path.join('verified-runtime', archive);
  if (fs.statSync(runtimePath).size !== metadata.bytes || await digest(runtimePath) !== metadata.sha256) throw new Error('Runtime archive checksum mismatch.');
  for (const field of ['images', 'image_configs']) {
    if (Object.keys(metadata[field]).sort().join(',') !== 'browser,gateway,work' || Object.values(metadata[field]).some(v => !/^sha256:[a-f0-9]{64}$/.test(v))) throw new Error('Invalid runtime image identifiers.');
  }
  const files = [[manifests[0], 'verified-runtime']];
  const names = [
    [`ENGE-SPX-Windows-x64-${version}-Setup.exe`, 'verified-package'],
    [`ENGE-SPX-Windows-x64-${version}-Portable.zip`, 'verified-package'],
    [archive, 'verified-runtime'],
  ];
  for (const [name, directory] of names) {
    const actual = await digest(path.join(directory, name));
    const checksum = fs.readFileSync(path.join(directory, name + '.sha256'), 'utf8').trim();
    if (checksum !== actual + '  ' + name) throw new Error('Package checksum differs: ' + name);
    files.push([name, directory], [name + '.sha256', directory]);
  }
  const tag = `v${version}-windows`;
  const releaseName = `ENGE SPX ${version} Preview`;
  const body = [
    '**ENGE SPX** — Windows 上的 AI 编程隔离工作台，让 Claude Code、Codex 和浏览器通过指定代理出口工作。',
    '',
    '### 下载',
    '',
    `推荐：\`ENGE-SPX-Windows-x64-${version}-Setup.exe\`，当前用户安装，带开始菜单和桌面快捷方式。`,
    `免安装：\`ENGE-SPX-Windows-x64-${version}-Portable.zip\`，完整解压后运行 \`ENGE-SPX.exe\`。命令行入口是 \`spx.exe\`。`,
    '',
    '无需另外安装 Python。需要 Docker Desktop / Linux containers，Engine 28 或更新版本。运行环境会在软件内下载、校验和导入，无需手工处理 runtime 文件。',
    '',
    '### 核心用途',
    '',
    '在独立 Linux 容器中运行 Claude Code、Codex 和共享 Chromium，通过指定线路与落地代理访问服务。项目范围挂载、受控网关、双出口核验与异常停机共同减少对 Windows 日常环境的暴露。',
    '',
    '### 这个版本',
    '',
    '- 一键准备：自动检测或启动已安装的 Docker Desktop，等待 Linux 引擎真正就绪，核验或安装运行环境，再继续连接检查。首次打开不会自动开始大型下载。',
    '- 启动步骤可见、可取消，等待超时或缺少 Docker 时提供处理入口；支持官方启动 CLI 和旧版桌面程序，识别自定义安装盘。',
    '- 已有匹配镜像复用；不切换全局上下文或容器引擎，不自动确认变更后的出口。新增启动偏好、脱敏诊断摘要及 spx start / diagnostics。',
    '- 默认中文主页先说明软件用途、隔离工作区和固定双跳，再介绍 Pebrel、自定义终端、D 盘迁移与下载管理。补齐快速入门、安全模型、贡献和支持文档及问题模板。',
    '- 适配新仓库 engeeeee/ENGE-SPX，更新下载地址、安装器链接与发布流程；中文 About 配置独立保存，需维护者在仓库设置中应用。',
    '- 继续支持加密线路 → SOCKS5 / HTTP / HTTPS 落地的固定双跳、独立出口核验和异常停止，以及 v2ray 本机代理兼容、下载续传、账号与项目数据复用。',
    '',
    '升级前请停止环境并退出旧窗口；安装后重新检查并确认出口。项目目录仍然读写共享，工具账号在项目间共享；Chromium 当前使用 --no-sandbox。此预览版未代码签名，未经过独立安全审计，也不提供匿名或完全宿主机隔离保证。',
    '',
    '本次发布要求同一 CI 的 Windows / Linux 单元检查、原生 Windows 假 Desktop 进程启动、GUI 异步准备与迁移、打包与安装卸载、实际 Linux 双跳故障阻断与两种镜像存储导入检查通过。尚未在用户的真实 Windows + Docker Desktop + v2ray + Pebrel 组合上完成交互验收。',
    '',
    `[使用说明](https://github.com/${owner}/${repo}/blob/${tag}/README.md) · [线路保护](https://github.com/${owner}/${repo}/blob/${tag}/docs/line-protection.zh-CN.md) · [来源与许可](https://github.com/${owner}/${repo}/blob/${tag}/NOTICE.md) · [本次构建](https://github.com/${owner}/${repo}/actions/runs/${context.runId})`,
  ].join('\n');
  let release = (await github.rest.repos.listReleases({owner, repo, per_page: 100})).data.find(r => r.tag_name === tag);
  if (!release) {
    release = (await github.rest.repos.createRelease({owner, repo, tag_name: tag, target_commitish: context.sha, name: releaseName, body, draft: true, prerelease: true})).data;
  }
  const assets = (await github.rest.repos.listReleaseAssets({owner, repo, release_id: release.id})).data;
  for (const [name, directory] of files) {
    const file = path.join(directory, name);
    const size = fs.statSync(file).size;
    const hash = 'sha256:' + await digest(file);
    const previous = assets.find(a => a.name === name);
    if (previous) {
      if (previous.size !== size || previous.digest !== hash) throw new Error('Existing version assets are immutable: ' + name);
      continue;
    }
    if (!release.draft) throw new Error('Cannot add files to an already published version.');
    const data = fs.readFileSync(file);
    await github.rest.repos.uploadReleaseAsset({owner, repo, release_id: release.id, name, data, headers: {'content-type': name.endsWith('.json') ? 'application/json' : 'application/octet-stream', 'content-length': size}});
  }
  if (release.draft) {
    release = (await github.rest.repos.updateRelease({owner, repo, release_id: release.id, name: releaseName, body, draft: false, prerelease: true, make_latest: 'false'})).data;
  }
  core.notice('Published ' + release.html_url);
  if (version === '0.5.2') {
    const notice = `> **请升级到 [0.5.2](${release.html_url})。** 此中间预览版的线路诊断可能受 Docker 注入的 NO_PROXY 环境变量影响；0.5.2 已修复并补充实际容器验证。\n\n`;
    for (const oldTag of ['v0.5.0-windows', 'v0.5.1-windows']) {
      try {
        const old = (await github.rest.repos.getReleaseByTag({owner, repo, tag: oldTag})).data;
        if (!old.draft && !(old.body || '').includes('此中间预览版的线路诊断')) {
          await github.rest.repos.updateRelease({owner, repo, release_id: old.id, body: notice + (old.body || '')});
        }
      } catch (error) {
        core.warning('Could not annotate intermediate preview ' + oldTag + ': ' + error.message);
      }
    }
  }
};
