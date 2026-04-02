# Fifth Round Logging Cleanup Design

**Topic:** validator / evaluation / aggregator 模块级日志收敛

## Goal

在不改变现有业务语义和 CLI 用户输出体验的前提下，将库模块中的直接 `print()` 调用收敛为模块级 logger，减少调试噪声、输出副作用和后续日志治理成本。

## Scope

本轮只覆盖以下三个模块：

- `src/knowmat/nodes/validator.py`
- `src/knowmat/nodes/evaluation.py`
- `src/knowmat/nodes/aggregator.py`

## Non-Goals

- 不改 CLI 层的用户可见输出
- 不做全局 logging 架构重构
- 不新增统一 formatter / handler / logging config
- 不扩展到其他节点或脚本模块

## Current Problems

- 这三个模块属于库/节点逻辑，但当前包含直接 `print()` 输出
- 直接输出会带来：
  - 污染测试输出
  - 作为库调用时产生非结构化 side effect
  - 后续难以按级别、来源和场景控制日志

## Options

### Option A: 只替换 print

- 把 `print()` 逐个替换成 logger
- 不统一消息级别

**Pros**

- 改动最少

**Cons**

- 语义不统一
- 后续还要再整理一次

### Option B: 模块级统一收敛（推荐）

- 每个模块创建 `logger = logging.getLogger(__name__)`
- 按消息语义映射到 `info` / `warning` / `error`
- 尽量保持原消息文本不变
- 不引入新的全局 logging 配置

**Pros**

- 收益明显
- 风险可控
- 与现有项目规模匹配

**Cons**

- 仍保留默认 logging 行为，未做统一格式治理

### Option C: 全局日志体系重构

- 同时统一 logger、handler、formatter、CLI 级别控制

**Pros**

- 最完整

**Cons**

- 范围过大
- 超出“第五轮清理”目标

## Recommended Design

采用 **Option B**。

### 1. 模块边界

- 仅修改 `validator.py`、`evaluation.py`、`aggregator.py`
- 不修改 orchestrator 与 CLI 中面向用户的直接输出

### 2. 实现方式

- 为每个模块增加：
  - `import logging`
  - `logger = logging.getLogger(__name__)`
- 将 `print()` 替换为合适级别：
  - 进度/说明性信息 → `logger.info`
  - 可疑输入/跳过/回退 → `logger.warning`
  - 明确失败/异常上下文 → `logger.error`

### 3. 兼容原则

- 保持原有消息内容尽量稳定
- 不改变现有控制流
- 不额外引入注释或日志封装层

### 4. 测试策略

- 新增定向测试，验证三个模块源码中不再包含 `print(`
- 保持已有测试全部通过
- 最终执行完整 `python -m pytest`

## Files Expected To Change

- `src/knowmat/nodes/validator.py`
- `src/knowmat/nodes/evaluation.py`
- `src/knowmat/nodes/aggregator.py`
- `tests/` 下新增一个日志收敛契约测试
- `CHANGELOG.md` 记录第五轮治理内容

## Risks

- 某些原本依赖 stdout 的人工调试习惯会改变
- 如果日志级别判断失当，可能导致重要信息默认不可见

## Mitigations

- 保持消息文本基本不变
- 优先将原先“普通提示”映射到 `info`
- 对原先明显异常/失败上下文使用 `warning` 或 `error`
- 通过全量 pytest 确认无行为回归

## Verification

- 定向测试：日志收敛契约测试通过
- 全量测试：`python -m pytest`
