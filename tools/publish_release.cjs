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
    '- 自定义工作区终端：支持 Pebrel 专用预设、自动检测、Windows Terminal、PowerShell，以及自选 exe 和参数。Claude Code、Codex、Linux 终端和登录窗口使用同一设置。',
    '- 应用数据迁移：可选择 D 盘等位置搬迁配置、日志和下载缓存，逐文件校验后切换默认位置，释放原目录中的已校验副本；保留安装标识、断点下载和已有环境。',
    '- Docker 数据盘迁移助手：选择目标目录，记录迁移前资源，提供 Docker Desktop 操作引导并核验迁移结果。数据盘需要在 Docker 的 Disk image location 设置中确认 Apply；不是全自动搬迁 Docker。',
    '- 自动终端选择优先 Pebrel；可在不连接代理、不启动 Docker 工作区的情况下测试终端。迁移后仅更新网关的配置挂载，保留项目容器可写层和账号、浏览器数据卷。',
    '- 保留 SOCKS5 / HTTP / HTTPS 导入、本机线路 → 落地代理、出口核对、下载暂停与续传。',
    '- 识别此前 Windows 版的数据目录及镜像，保留项目容器、账号与浏览器资料；首次连接检查完成后台交接。',
    '',
    '升级前请停止环境并退出旧窗口，安装后重新检查并确认落地出口。项目文件仍是读写共享，工具账号在项目间共享。Chromium 当前使用 --no-sandbox；此预览版尚未代码签名，也未经过独立安全审计或真实 Windows 桌面的全流程交互验收。',
    '',
    '本次发布由同一 CI 流程的 Windows / Linux 检查、真实 GUI 迁移、打包与安装卸载检查、原生 x64 容器迁移和两种 Docker 存储的完整导入检查完成后生成。Docker Desktop 数据盘迁移和真实 Pebrel 窗口仍需在用户桌面上验证。',
    '',
    `[使用说明](https://github.com/${owner}/${repo}/blob/${tag}/README.zh-CN.md) · [来源与许可](https://github.com/${owner}/${repo}/blob/${tag}/NOTICE.md) · [本次构建](https://github.com/${owner}/${repo}/actions/runs/${context.runId})`,
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
