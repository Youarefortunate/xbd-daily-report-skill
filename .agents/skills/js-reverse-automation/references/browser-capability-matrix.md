# 浏览器能力矩阵 (Antigravity Browser Agent & Playwright-CLI)

本文件定义了在不同环境下进行浏览器调查的边界：直接能力、受限能力以及推断逻辑。

## 1. 默认工具：Antigravity 内置 Browser Agent (`browser_subagent`)

### 优势 (Direct Capabilities)
- **视觉感知**：能够看到页面布局、截图和元素位置，适合直观验证 UI 状态。
- **Agentic 交互**：能够理解复杂的页面结构并进行逻辑性操作。
- **集成性**：与 Antigravity 深度集成，无需额外配置。

### 限制 (Limitations)
- **底层细节**：在获取详细的网络请求 Body、Headers 以及精确的 Trace 轨迹时，可能需要结合 `playwright-cli` 来获取更详细的数据。
- **预加载脚本**：对于注入 `initScript` 等极早期 Hook，通常需要底层 CLI 支持。

## 2. 通用/专业工具：Playwright-CLI

### 优势 (Direct Capabilities)
- **精准观测**：通过 `playwright-cli network` 和 `playwright-cli console` 获取物理级的请求响应数据和实时日志。
- **协议深度**：支持 `playwright-cli tracing-start` 等，可以导出完整的上下文轨迹。
- **环境隔离**：支持 `--persistent` 或 `--profile`，方便在不同会话间切换。
- **早期注入**：支持在导航前注入脚本，对抗早期检测。

### 限制 (Limitations)
- **非视觉**：主要通过命令行输出或 YML 快照交互，不如内置代理直观。

## 3. 共同约束 (Common Constraints)

### 二者均不能直接做的
- 直接确认 TLS 指纹（如 JA3）或更细的底层握手参数（通常在更底层的 Proxy 层处理）。
- 直接确认底层连接复用状态（HTTP/2 Keep-Alive 等）。

### 二者均需推断的
- 浏览器内请求成功、页面外请求失败是否由 TLS/JA3 指纹差异导致。
- 某个协议层差异（如 Header 顺序）是否对服务端验签产生实质影响。

## 4. 使用规则
- **优先观察**：能直接捕获证据的（如 Network 数据），不要写成推断。
- **交叉验证**：如果内置代理看到的现象与命令行结果不一致，必须记录差异。
- **标记风险**：所有通过“推断”得出的结论（如：猜测可能是因为少传了某个 Cookie），必须标记为“风险”或“待验证”。
