/**
 * 插件宿主半侧的测试。不需要真的 dsh，用一个假 ctx 就能验。
 *
 *   node --test test/
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { apply, pythonExe, resetPythonCache, runScript } from '../lib/index.js'

/** 假的 cordis ctx：记录注册了什么，effect 立刻执行并保存 disposer。 */
function fakeCtx() {
  const tools = []
  const sections = []
  const disposers = []
  return {
    tools: { register: (tool) => { tools.push(tool); return () => {} } },
    systemPrompt: { section: (s) => { sections.push(s) } },
    effect: (fn) => { const d = fn(); if (typeof d === 'function') disposers.push(d) },
    _tools: tools,
    _sections: sections,
    _disposers: disposers,
  }
}

test('找得到 Python', () => {
  resetPythonCache()
  const exe = pythonExe()
  assert.equal(typeof exe, 'string')
  assert.ok(exe.length > 0)
})

test('router.py 返回结构化判档结果', async () => {
  const result = await runScript('router.py', ['--json', '做一个前后端都有的工单系统'])
  assert.equal(result.code, 0, result.stderr)
  const data = JSON.parse(result.stdout)
  assert.equal(data.tier, 'L2')
  assert.equal(data.profile, 'fullstack')
  assert.ok(Array.isArray(data.stages) && data.stages.length > 0)
})

test('非零退出不抛异常，code 原样传回', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'dsh-wish-'))
  const path = join(dir, 'contract.md')
  writeFileSync(path, '# 契约\n\n### AC-01\n\n- **判定方式**：\n\n> 反例：\n', 'utf8')
  try {
    const result = await runScript('contract_lint.py', [path])
    assert.equal(result.code, 1)
    assert.match(result.stdout, /不合格|FAIL/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('注册四个工具，名字正确', () => {
  const ctx = fakeCtx()
  apply(ctx, {})
  const names = ctx._tools.map((t) => t.name).sort()
  assert.deepEqual(names, ['wish_contract', 'wish_focus', 'wish_lint', 'wish_route'])
})

test('每个工具有说明、参数与输出约定', () => {
  const ctx = fakeCtx()
  apply(ctx, {})
  for (const tool of ctx._tools) {
    assert.ok(tool.description && tool.description.length > 10, `${tool.name} 缺 description`)
    assert.equal(tool.parameters.type, 'object')
    assert.ok(tool.output && typeof tool.output.render === 'function', `${tool.name} 缺 render`)
    assert.equal(typeof tool.execute, 'function')
  }
})

test('工具确实能调到内核', async () => {
  const ctx = fakeCtx()
  apply(ctx, {})
  const route = ctx._tools.find((t) => t.name === 'wish_route')
  const out = await route.execute({ wish: '实现一个用户登录接口' }, {})
  const data = JSON.parse(out.text)
  assert.equal(data.tier, 'L1')
})

test('系统提示片段注册一次', () => {
  const ctx = fakeCtx()
  apply(ctx, {})
  assert.equal(ctx._sections.length, 1)
  assert.equal(ctx._sections[0].name, 'dsh-wish')
  assert.match(ctx._sections[0].text, /wish_route/)
  assert.equal(ctx._sections[0].order, 520)
})

test('工具描述自带流程链（提示片段不保证可见时仍能拼出顺序）', () => {
  const ctx = fakeCtx()
  apply(ctx, {})
  const byName = Object.fromEntries(ctx._tools.map((t) => [t.name, t.description]))
  // 每个工具都要指出自己的后继动作，否则"只读工具表"拼不出流程
  assert.match(byName.wish_route, /wish_focus/, 'route 没说下一步是 focus')
  assert.match(byName.wish_route, /L0/, 'route 没说 L0 到此为止')
  assert.match(byName.wish_focus, /wish_contract/, 'focus 没说下一步是 contract')
  assert.match(byName.wish_focus, /L1\/L2/, 'focus 没说只对 L1/L2')
  assert.match(byName.wish_contract, /退出码 1/, 'contract 没强调退出码')
  assert.match(byName.wish_contract, /不得代签|人确认/, 'contract 没要求人确认')
  assert.match(byName.wish_lint, /退出码 1/, 'lint 没强调退出码')
})

test('提示片段含完整四步而非只有一句', () => {
  const ctx = fakeCtx()
  apply(ctx, {})
  const text = ctx._sections[0].text
  for (const token of ['wish_route', 'wish_focus', 'wish_contract', 'L0', '不得代签']) {
    assert.ok(text.includes(token), `提示片段缺 ${token}`)
  }
  assert.ok(text.split('\n').length >= 8, '提示片段太短，装不下流程')
})

test('可以用 config 关掉提示词片段', () => {
  const ctx = fakeCtx()
  apply(ctx, { promptSection: false })
  assert.equal(ctx._sections.length, 0)
  assert.equal(ctx._tools.length, 4)
})

test('disposer 关掉后不抛异常', () => {
  const ctx = fakeCtx()
  apply(ctx, {})
  for (const dispose of ctx._disposers) {
    assert.doesNotThrow(() => dispose())
  }
})

test('输出 schema 只允许 {text}', () => {
  const ctx = fakeCtx()
  apply(ctx, {})
  for (const tool of ctx._tools) {
    const rendered = tool.output.render({}, { text: 'ok' })
    assert.deepEqual(rendered, [{ type: 'text', text: 'ok' }])
    assert.equal(tool.output.schema.properties.text.type, 'string')
  }
})
