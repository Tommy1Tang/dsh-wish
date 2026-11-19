/**
 * dsh-wish 的类型声明。
 *
 * 只声明宿主半侧的对外形状。内核在 Python 里，不在这里。
 */

export interface WishConfig {
  /**
   * 关掉系统提示片段（工具照常注册）。
   *
   * 同时装了本目录的 skill 时可以关掉，避免同样的规则说两遍。
   */
  promptSection?: boolean
}

export declare const name: 'dsh-wish'
export declare const inject: string[]

/** 找 Python 解释器：显式配置 → dsh 自带运行时 → PATH。 */
export declare function pythonExe(): string

/** 清掉解释器缓存，让下一次重新探测（测试用）。 */
export declare function resetPythonCache(): void

/**
 * 跑一个内核脚本。
 *
 * **非零退出不抛异常** —— 退出码 1 是"契约不合格"，是正常语义，不是错误。
 */
export declare function runScript(
  script: string,
  args?: string[],
  cwd?: string,
): Promise<{ code: number; stdout: string; stderr: string }>

export declare function apply(ctx: unknown, config?: WishConfig): void
