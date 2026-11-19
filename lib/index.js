/**
 * dsh-wish — 许愿式编程的 dsh 插件宿主半侧。
 *
 * 这一层只做三件事：
 *   1. 把 4 个工具注册给模型（判档 / 对焦 / 出契约 / 查契约）
 *   2. 找到 Python 解释器，调同目录下的 .py（**内核不重写，见 PLAN §13**）
 *   3. 把退出码翻译成模型能理解的话
 *
 * 刻意不做的事：
 *   - 不复制路由判据。判据在 router.py 里，92 个测试盯着它。
 *   - 不缓存判定结果。判据改了要立刻生效，不要重启插件。
 *   - 不吞退出码。契约 lint 返回 1 就是不合格，不许翻译成"基本完成"。
 */
import { execFile } from 'node:child_process'
import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

export const name = 'dsh-wish'

/** webServer 用不上；系统提示片段是可选的（skill 也在讲同样的事）。 */
export const inject = ['tools', 'systemPrompt']

const LIB_DIR = dirname(fileURLToPath(import.meta.url))
const PKG_DIR = dirname(LIB_DIR)

const PY_ENV = {
  PYTHONUTF8: '1',
  PYTHONIOENCODING: 'utf-8',
}

const TIMEOUT_MS = 60_000
const MAX_BUFFER = 8 * 1024 * 1024

// ---------------------------------------------------------------------------
// Python 解释器
// ---------------------------------------------------------------------------

let cachedPython

/**
 * 找 Python。顺序：显式配置 → dsh 自带运行时 → PATH。
 * dsh 的运行时里带 3.12，优先用它，免得用户机器上没装 Python 就跑不了。
 */
export function pythonExe() {
  if (cachedPython) return cachedPython

  const explicit = process.env.DSH_WISH_PYTHON
  if (explicit && existsSync(explicit)) {
    cachedPython = explicit
    return cachedPython
  }

  const dshHome = process.env.DSH_HOME || join(homedir(), '.dsh')
  const runtimes = join(dshHome, 'dsh-runtimes')
  if (existsSync(runtimes)) {
    try {
      for (const entry of readdirSync(runtimes)) {
        const base = join(runtimes, entry, 'dependencies', 'python')
        for (const candidate of ['python.exe', join('bin', 'python3'), 'python3', 'python']) {
          const exe = join(base, candidate)
          if (existsSync(exe)) {
            cachedPython = exe
            return cachedPython
          }
        }
      }
    } catch {
      // 目录读不了就当没找到，继续往下回退
    }
  }

  cachedPython = process.platform === 'win32' ? 'python' : 'python3'
  return cachedPython
}

/** 测试用：清掉缓存，让下一次重新探测。 */
export function resetPythonCache() {
  cachedPython = undefined
}

// ---------------------------------------------------------------------------
// 调 Python
// ---------------------------------------------------------------------------

/**
 * 跑一个内核脚本。
 *
 * 返回 `{ code, stdout, stderr }` —— **非零退出不抛异常**，因为非零退出是
 * 这个产品的正常语义（契约不合格 = 1），不是错误。
 */
export async function runScript(script, args = [], cwd = PKG_DIR) {
  const exe = pythonExe()
  const target = join(PKG_DIR, script)
  try {
    const { stdout, stderr } = await execFileAsync(exe, [target, ...args], {
      cwd,
      timeout: TIMEOUT_MS,
      maxBuffer: MAX_BUFFER,
      env: { ...process.env, ...PY_ENV },
      windowsHide: true,
    })
    return { code: 0, stdout: String(stdout ?? ''), stderr: String(stderr ?? '') }
  } catch (err) {
    return {
      code: typeof err?.code === 'number' ? err.code : 1,
      stdout: String(err?.stdout ?? ''),
      stderr: String(err?.stderr ?? err?.message ?? err),
    }
  }
}

/** 工具统一返回 `{ text }`，把退出码的含义写进文字里。 */
function textOutput() {
  return {
    schema: {
      type: 'object',
      additionalProperties: false,
      properties: { text: { type: 'string' } },
    },
    render: (_args, value) => [{ type: 'text', text: String(value?.text ?? '') }],
  }
}

function fail(prefix, result) {
  const detail = (result.stderr || result.stdout || '').trim()
  return { text: `${prefix}\n退出码=${result.code}\n${detail}` }
}

const PROJECT_CWD = (exec) => exec?.agent?.session?.header?.cwd || process.cwd()

// ---------------------------------------------------------------------------
// 插件入口
// ---------------------------------------------------------------------------

export function apply(ctx, config = {}) {
  ctx.effect(() => {
    const disposers = []

    // --- 1. 判档 -----------------------------------------------------------
    disposers.push(ctx.tools.register({
      name: 'wish_route',
      description:
        '判定一个需求的交付档位（L0 直接做 / L1 走角色链 / L2 先建模）、工作类型（fix/frontend/' +
        'backend/fullstack/report/data/ops/integration）、紧迫度，并给出要走的阶段、人审点、' +
        '风险标记与要问用户的问题。**不要自己判断档位**，用这个工具的结果。' +
        '　下一步：L0 直接做、到此为止；L1/L2 调 wish_focus。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          wish: {
            type: 'string',
            description: '用户的原话，尽量原样传入——判据依赖措辞，改写会判错',
          },
        },
        required: ['wish'],
      },
      output: textOutput(),
      async execute(args, exec) {
        const result = await runScript('router.py', ['--json', args.wish], PROJECT_CWD(exec))
        if (result.code !== 0) return fail('判档失败。', result)
        return { text: result.stdout }
      },
    }))

    // --- 2. 对焦：出题并建目录 ---------------------------------------------
    disposers.push(ctx.tools.register({
      name: 'wish_focus',
      description:
        '在项目的 wish/<slug>/ 下建一份 answers.md：里面是要问用户的问题（每题已预填推荐答案）。' +
        '把这些问题原样交给用户，不要替他答；留空表示接受推荐。' +
        '**只在他问的是 L1/L2 时用**（L0 不要走这一步）。' +
        '　下一步：用户答完后调 wish_contract。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          wish: { type: 'string', description: '用户的原话' },
          root: { type: 'string', description: '可选：wish 目录的根，默认项目根下的 wish/' },
        },
        required: ['wish'],
      },
      output: textOutput(),
      async execute(args, exec) {
        const cwd = PROJECT_CWD(exec)
        const argv = args.root ? ['--root', args.root, args.wish] : [args.wish]
        const result = await runScript('focus.py', argv, cwd)
        if (result.code !== 0) return fail('对焦目录创建失败（可能已存在，加 --force 或换目录）。', result)
        return { text: result.stdout }
      },
    }))

    // --- 3. 回填 → 生成契约并检查 ------------------------------------------
    disposers.push(ctx.tools.register({
      name: 'wish_contract',
      description:
        '读 wish/<slug>/answers.md 生成 contract.md，并立刻跑契约检查。' +
        '**退出码 1 = 契约不合格，此时不许进入实现**；把 lint 报的每一条转成具体动作让用户补。' +
        '退出码 0 才可以写第一行代码，且仍需人确认（不得代签）。' +
        '　用户改完 answers 或手填反例后，再调一次本工具复查。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          dir: { type: 'string', description: 'wish/<slug> 目录（相对项目根或绝对路径）' },
          force: { type: 'boolean', description: '丢弃已手填的反例，重新生成' },
        },
        required: ['dir'],
      },
      output: textOutput(),
      async execute(args, exec) {
        const argv = ['--complete', args.dir]
        if (args.force) argv.push('--force')
        const result = await runScript('focus.py', argv, PROJECT_CWD(exec))
        const body = (result.stdout || result.stderr || '').trim()
        if (result.code === 0) {
          return { text: `${body}\n\n契约合格。下一步要人确认（AI 不得代签），然后才进执行。` }
        }
        if (result.code === 1) {
          return { text: `${body}\n\n契约不合格（退出码 1）。不要开工，先补上面每一条。` }
        }
        return fail('生成契约失败。', result)
      },
    }))

    // --- 4. 单独检查一份契约 -----------------------------------------------
    disposers.push(ctx.tools.register({
      name: 'wish_lint',
      description:
        '检查一份 contract.md 写得实不实：每条 AC 是否有判定方式、是否有反例、是否含模糊词、' +
        '是否有可观测对象、「本次不做」是否为空、状态是否全覆盖。退出码 1 表示不合格。' +
        '　用于复查已有契约（不重新生成），或在你手改了 contract.md 之后验证。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          path: { type: 'string', description: 'contract.md 的路径' },
        },
        required: ['path'],
      },
      output: textOutput(),
      async execute(args, exec) {
        const result = await runScript('contract_lint.py', [args.path], PROJECT_CWD(exec))
        const body = (result.stdout || result.stderr || '').trim()
        if (result.code === 0) return { text: body }
        if (result.code === 1) return { text: `${body}\n\n（退出码 1：不合格）` }
        return fail('检查失败。', result)
      },
    }))

    return () => {
      for (const dispose of disposers) {
        try {
          if (typeof dispose === 'function') dispose()
        } catch {
          // reload 时的清理失败不该让整个插件崩掉
        }
      }
    }
  })

  // --- 提示词片段 ---------------------------------------------------------
  // 注意：这段是否真的进了模型上下文，我无法从会话内部证实（工具描述确定可见，
  // 提示片段不保证）。所以**流程链也写进了每个工具的 description**，
  // 保证"只读工具表"也能拼出正确顺序。改描述时别把那条链拆散。
  if (config?.promptSection !== false) {
    try {
      ctx.systemPrompt.section({
        name: 'dsh-wish',
        order: 520,
        text: [
          '【许愿式编程】用户提出一件要做的事时，按这个顺序走，不要跳：',
          '1. 判档：调 `wish_route`（原话传入）。不要自己判断档位；与直觉冲突时以它为准。',
          '2. L0 = 直接做，到此为止。L1/L2 = 调 `wish_focus` 出题，把问题原样问用户。',
          '   fact 类自己查（读 tech.md / 派 subagent），不要拿去问人。',
          '3. 用户答完后调 `wish_contract`。退出码 1 = 不合格，**不许开工**；',
          '   把 lint 报的每一条转成具体动作让用户补。',
          '4. 只有退出码 0 才可以写第一行代码，且仍需人确认。',
          '',
          '硬约束：脚本通过、没有报错、你自审一遍，都不等于用户批准（不得代签）；',
          '不得为通过 lint 而改 lint；用户答完对焦后要重新判档（升档由系统宣布，不让用户自己判断）。',
        ].join('\n'),
      })
    } catch {
      // 系统提示服务不可用不该让工具一起消失
    }
  }
}
