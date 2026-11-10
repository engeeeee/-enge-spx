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
    '在独立 Linux 容器中运行 Claude Code、Codex 和 Chromium，通过指定线路与落地代理访问服务。可选择独立工作区身份及项目只读/读写授权；受控网关、双出口核验与异常停机共同减少对 Windows 日常环境的暴露。',
    '',
    '### 这个版本',
    '',
    fs.existsSync(path.join('docs', 'releases', `${version}.zh-CN.md`))
      ? fs.readFileSync(path.join('docs', 'releases', `${version}.zh-CN.md`), 'utf8').trim()
      : `本版本改动见 [CHANGELOG](https://github.com/${owner}/${repo}/blob/${tag}/CHANGELOG.md)。`,
    '',
    '本次发布要求同一 CI 的 Windows / Linux、真实文件共享锁、Qt 多档缩放、打包 GUI 手动启动、安装卸载、实际 Linux 长时续期、字体与中文 PTY、双跳故障阻断和两种镜像存储导入检查通过。Windows 界面结果保存在该次 CI 的 UI Artifact。假 Desktop 与 Linux Docker 测试不能代替用户真实 Docker Desktop / WSL、v2ray、自定义终端 和显示器组合验收。Qt / PySide6 / Shiboken6 的许可、上游声明与对应源码链接随包提供。',
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
  if (version === '0.7.1') {
    try {
      const old = (await github.rest.repos.getReleaseByTag({owner, repo, tag: 'v0.7.0-windows'})).data;
      if (!old.draft && !(old.body || '').includes('此版本收到启动后无提示退出的报告')) {
        const notice = `> **建议升级到 [0.7.1](${release.html_url})。** 此版本收到启动后无提示退出的报告；0.7.1 移除了 Python 窗口消息钩子并增加本地崩溃日志与打包冷启动检查。用户故障堆栈尚未取得，仍需实机确认。\n\n`;
        await github.rest.repos.updateRelease({owner, repo, release_id: old.id, body: notice + (old.body || '')});
      }
    } catch (error) {
      core.warning('Could not annotate 0.7.0 preview: ' + error.message);
    }
  }
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
