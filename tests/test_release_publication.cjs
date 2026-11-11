// Test the real publication helper with private synthetic files and an in-memory API.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {test} = require('node:test');
const publish = require('../tools/publish_release.cjs');

function fixture(t) {
  const previous = process.cwd();
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'spx-publication-'));
  process.chdir(directory);
  t.after(() => { process.chdir(previous); fs.rmSync(directory, {recursive: true, force: true}); });
  fs.mkdirSync('verified-runtime');
  fs.mkdirSync('verified-package');
  const version = '0.13.1';
  const sha = 'a'.repeat(40);
  const hash = value => crypto.createHash('sha256').update(value).digest('hex');
  const archive = `ENGE-SPX-Runtime-linux-amd64-${version}.tar.gz`;
  const manifestName = `ENGE-SPX-Runtime-linux-amd64-${version}.json`;
  const names = [
    [`ENGE-SPX-Windows-x64-${version}-Setup.exe`, 'verified-package'],
    [`ENGE-SPX-Windows-x64-${version}-Portable.zip`, 'verified-package'],
    [archive, 'verified-runtime'],
  ];
  for (const [name, folder] of names) {
    const data = Buffer.from('synthetic publication fixture: ' + name);
    fs.writeFileSync(path.join(folder, name), data);
    fs.writeFileSync(path.join(folder, name + '.sha256'), hash(data) + '  ' + name + '\n');
  }
  const runtime = fs.readFileSync(path.join('verified-runtime', archive));
  const imageIds = Object.fromEntries(['gateway', 'work', 'browser'].map(role => [role, 'sha256:' + 'b'.repeat(64)]));
  const metadata = {schema: 1, version, platform: 'linux/amd64', filename: archive, bytes: runtime.length, sha256: hash(runtime), images: imageIds, image_configs: imageIds};
  fs.writeFileSync(path.join('verified-runtime', manifestName), JSON.stringify(metadata));
  const files = [[manifestName, 'verified-runtime'], ...names.flatMap(([name, folder]) => [[name, folder], [name + '.sha256', folder]])];
  const matchingAssets = files.map(([name, folder], index) => {
    const data = fs.readFileSync(path.join(folder, name));
    return {id: index + 1, name, size: data.length, digest: 'sha256:' + hash(data)};
  });
  const state = {calls: [], release: null, assets: []};
  const record = (method, input) => state.calls.push({method, input});
  const github = {rest: {repos: {
    async listReleases(input) { record('list', input); return {data: state.release ? [{...state.release}] : []}; },
    async createRelease(input) {
      record('create', input);
      state.release = {id: 42, html_url: 'https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.13.1-windows', ...input};
      return {data: {...state.release}};
    },
    async listReleaseAssets(input) { record('assets', input); return {data: state.assets.map(value => ({...value}))}; },
    async uploadReleaseAsset(input) {
      record('upload', input);
      state.assets.push({id: state.assets.length + 1, name: input.name, size: input.data.length, digest: 'sha256:' + hash(input.data)});
      return {data: state.assets.at(-1)};
    },
    async updateRelease(input) {
      record('update', input);
      assert.equal(state.assets.length, 7, 'Never publish before all seven files exist');
      state.release = {...state.release, ...input};
      return {data: {...state.release}};
    },
  }}};
  const args = {github, context: {repo: {owner: 'engeeeee', repo: 'ENGE-SPX'}, ref: 'refs/heads/main', sha, runId: 123}, core: {notice() {}, warning() {}}};
  function existing(preview) {
    state.release = {id: 42, tag_name: 'v0.13.1-windows', target_commitish: sha, name: `ENGE SPX ${version}` + (preview ? ' Preview' : ''), draft: false, prerelease: preview, html_url: 'https://github.com/engeeeee/ENGE-SPX/releases/tag/v0.13.1-windows'};
    state.assets = matchingAssets.map(value => ({...value}));
  }
  return {args, state, metadata, manifestName, existing};
}

function noWrites(state) {
  assert.deepEqual(state.calls.filter(value => ['create', 'upload', 'update'].includes(value.method)), []);
}

test('new full release stays draft until seven verified files upload, then becomes Latest', async t => {
  const {args, state} = fixture(t);
  await publish(args);
  const create = state.calls.find(value => value.method === 'create').input;
  assert.equal(create.draft, true);
  assert.equal(create.prerelease, false);
  assert.equal(create.name, 'ENGE SPX 0.13.1');
  assert.equal(state.calls.filter(value => value.method === 'upload').length, 7);
  const update = state.calls.at(-1).input;
  assert.equal(update.draft, false);
  assert.equal(update.prerelease, false);
  assert.equal(update.make_latest, 'true');
});

test('matching published preview is promoted without replacing assets or the source', async t => {
  const {args, state, existing} = fixture(t);
  existing(true);
  const assets = JSON.stringify(state.assets);
  await publish(args);
  assert.equal(state.calls.filter(value => value.method === 'upload').length, 0);
  assert.equal(JSON.stringify(state.assets), assets);
  assert.equal(state.release.target_commitish, args.context.sha);
  assert.equal(state.release.prerelease, false);
  assert.equal(state.release.make_latest, 'true');
});

test('matching full release rerun is idempotent and does not move Latest backwards', async t => {
  const {args, state, existing} = fixture(t);
  existing(false);
  await publish(args);
  noWrites(state);
});

test('existing mismatched asset blocks promotion and is never overwritten', async t => {
  const {args, state, existing} = fixture(t);
  existing(true);
  state.assets[0].digest = 'sha256:' + '0'.repeat(64);
  await assert.rejects(publish(args), /assets are immutable/);
  noWrites(state);
});

test('published version with a missing asset is not silently repaired or promoted', async t => {
  const {args, state, existing} = fixture(t);
  existing(true);
  state.assets = [];
  await assert.rejects(publish(args), /Cannot add files/);
  noWrites(state);
});

test('different release source is rejected before uploads or metadata changes', async t => {
  const {args, state, existing} = fixture(t);
  existing(true);
  state.release.target_commitish = 'c'.repeat(40);
  await assert.rejects(publish(args), /different source commit/);
  noWrites(state);
});

test('invalid Windows sidecar fails before any API request', async t => {
  const {args, state} = fixture(t);
  fs.writeFileSync('verified-package/ENGE-SPX-Windows-x64-0.13.1-Setup.exe.sha256', 'invalid');
  await assert.rejects(publish(args), /checksum differs/);
  assert.deepEqual(state.calls, []);
});

test('invalid runtime size fails before any API request', async t => {
  const {args, state, metadata, manifestName} = fixture(t);
  fs.writeFileSync(path.join('verified-runtime', manifestName), JSON.stringify({...metadata, bytes: metadata.bytes + 1}));
  await assert.rejects(publish(args), /checksum mismatch/);
  assert.deepEqual(state.calls, []);
});

test('another repository or branch cannot publish', async t => {
  const {args, state} = fixture(t);
  await assert.rejects(publish({...args, context: {...args.context, ref: 'refs/heads/feature'}}), /limited to the maintained/);
  await assert.rejects(publish({...args, context: {...args.context, repo: {owner: 'other', repo: 'ENGE-SPX'}}}), /limited to the maintained/);
  assert.deepEqual(state.calls, []);
});
