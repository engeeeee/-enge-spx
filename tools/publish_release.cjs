// Publish artifacts from the same successful CI run, scoped to the personal repo.
module.exports = async ({github, context, core}) => {
  const fs = require('node:fs');
  const path = require('node:path');
  const crypto = require('node:crypto');
  const {owner, repo} = context.repo;
  if (owner !== 'engeeeee' || repo !== '-enge-spx' || context.ref !== 'refs/heads/main') {
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
    '**ENGE SPX** — engeeeee 的个人 Windows 容器工作环境项目。',
    '',
    '### 下载',
    '',
    `推荐：\`ENGE-SPX-Windows-x64-${version}-Setup.exe\`，当前用户安装，带开始菜单和桌面快捷方式。`,
    `免安装：\`ENGE-SPX-Windows-x64-${version}-Portable.zip\`，完整解压后运行 \`ENGE-SPX.exe\`。命令行入口是 \`spx.exe\`。`,
    '',
    '无需另外安装 Python。需要 Docker Desktop / Linux containers，Engine 28 或更新版本。运行环境会在软件内下载、校验和导入，无需手工处理 runtime 文件。',
    '',
    '### 这个版本',
    '',
    '- 软件内双跳：导入 v2ray 中受支持的线路分享链接，由 ENGE SPX 固定串联加密线路与落地；不配置直连或自动回退出口。域名线路需填写服务器 IPv4，TLS 校验和 SNI 保留。',
    '- 分别核对线路出口与落地出口；线路不符或失败时拒绝继续连接落地，已确认线路出口变化后停止环境。线路检查入口只监听网关回环，工作区不能用它绕过落地。',
    '- 启用前置线路时，落地域名经线路解析，不再提前查询宿主机 DNS。兼容 v2ray 本机代理，并提供不含凭据的 v2rayN 目的地址规则导出。兼容模式的出口检查不能证明外部客户端所有目标的分流。',
    '- 选择代理下载时，找不到代理就停止；主动取消该选项才直连。订阅下载使用同一代理设置，并拒绝降级至 HTTP。',
    '- 下载代理独立于工作区线路开关，首次安装不必先导入完整线路。订阅使用当前输入的下载代理，读取系统代理不会改变工作区模式。',
    '- 保留 Pebrel 和其他终端设置、应用数据跨盘迁移及 Docker 数据盘迁移助手。原有匹配镜像和账号、项目数据继续复用。',
    '- 保留 SOCKS5 / HTTP / HTTPS 导入、本机线路 → 落地代理、出口核对、下载暂停与续传。',
    '- 识别此前 Windows 版的数据目录及镜像，保留项目容器、账号与浏览器资料；首次连接检查完成后台交接。',
    '',
    '升级前请停止环境并退出旧窗口，安装后重新检查并确认落地出口。项目文件仍是读写共享，工具账号在项目间共享。Chromium 当前使用 --no-sandbox；此预览版尚未代码签名，也未经过独立安全审计或真实 Windows 桌面的全流程交互验收。',
    '',
    '本次发布由同一 CI 流程的 Windows / Linux 检查、真实 GUI 迁移、打包与安装卸载检查、原生 x64 双跳线路故障阻断与数据迁移、两种 Docker 存储的完整导入检查完成后生成。未在用户的真实 v2ray、Docker Desktop 或 Pebrel 桌面环境中验收；线路服务商仍是信任边界。',
    '',
    `[使用说明](https://github.com/${owner}/${repo}/blob/${tag}/README.zh-CN.md) · [v2ray 线路保护](https://github.com/${owner}/${repo}/blob/${tag}/docs/line-protection.zh-CN.md) · [来源与许可](https://github.com/${owner}/${repo}/blob/${tag}/NOTICE.md) · [本次构建](https://github.com/${owner}/${repo}/actions/runs/${context.runId})`,
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
};
