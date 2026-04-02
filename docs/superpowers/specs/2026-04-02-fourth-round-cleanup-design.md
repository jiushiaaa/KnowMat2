# Fourth Round Cleanup Design

**Topic:** docling 兼容层弃用治理 + trustcall/LangGraph 弃用告警根因修复

## Goal

在不破坏现有主流程与外部兼容入口的前提下，完成第四轮中风险治理：

- 将 `parse_pdf_with_docling` 从“静默兼容”升级为“显式弃用但继续兼容”
- 消除测试阶段由 `trustcall` 触发的 `langgraph.constants.Send` 弃用告警
- 通过最小改动保持现有抽取链与测试链稳定

## Current State

### docling 兼容层

- `src/knowmat/nodes/docling_parse_pdf.py` 当前只是一个薄包装：
  - `parse_pdf_with_docling(state)` 直接转发到 `parse_pdf_with_paddleocrvl(state)`
- 仓库内部主流程已经不再调用该入口：
  - CLI 直接使用 PaddleOCR-VL
  - orchestrator 的 `parse_pdf` 节点也直接绑定 PaddleOCR-VL
- 为降低外部破坏风险，该文件仍然保留，但已经从 `nodes.__all__` 中隐藏

### LangGraph 弃用告警

- pytest 中的 warning 来自 `trustcall` 内部，而不是 KnowMat 业务代码
- 根因链路是：
  - KnowMat 导入 `trustcall.create_extractor`
  - `trustcall` 内部从 `langgraph.constants` 导入 `Send`
  - 该导入路径在当前 LangGraph 版本中已标记弃用，推荐改为 `langgraph.types.Send`

## Options

### Option A: 最小根因修复（推荐）

- 保留 `docling_parse_pdf.py` 文件和函数签名
- 在调用 `parse_pdf_with_docling()` 时发出 `DeprecationWarning`
- 对 `trustcall` 的弃用导入做最小兼容修复，改为使用 `langgraph.types.Send`
- 为这两项行为补最小测试

**Pros**

- 改动面最小
- 风险集中且容易验证
- 不需要大规模升级依赖
- 同时解决“对外兼容治理”和“warning 根因”两个问题

**Cons**

- 需要维护一个本地兼容修复点

### Option B: 上游升级优先

- 升级 `trustcall`
- 观察新版是否已修复 LangGraph 弃用导入
- 再验证 KnowMat 抽取行为是否兼容

**Pros**

- 长期更干净
- 更接近“跟随上游”路线

**Cons**

- 依赖变化面更大
- 可能引入非预期行为变化
- 这一轮问题会从“清理治理”扩大成“依赖升级验证”

### Option C: 只做降噪

- `docling` 只加弃用提示
- 对 LangGraph warning 仅做 filter/suppress

**Pros**

- 最快

**Cons**

- 没有解决根因
- 后续升级时仍可能出问题

## Recommended Design

采用 **Option A**。

### 1. docling 弃用治理

- 修改 `src/knowmat/nodes/docling_parse_pdf.py`
- 在 `parse_pdf_with_docling()` 内部添加 `warnings.warn(..., DeprecationWarning, stacklevel=2)`
- warning 只在函数被调用时触发，不在模块 import 时触发
- warning 文案明确迁移目标：
  - `knowmat.nodes.paddleocrvl_parse_pdf.parse_pdf_with_paddleocrvl`

### 2. trustcall 根因修复

- 不改业务代码的 `extractors.py` 调用方式
- 优先做最小兼容修复，而不是升级整套依赖
- 目标是让运行时不再触发 `langgraph.constants.Send` 的弃用导入路径
- 如果仓库内可控实现需要一个兼容封装层，则只在最小范围内引入，不扩散到业务层接口

### 3. 测试策略

- 新增 docling 兼容测试：
  - 调用旧入口时能收到 `DeprecationWarning`
  - 返回值仍来自新的 PaddleOCR-VL 解析函数
- 新增 warning 治理测试或定向验证：
  - 至少确认目标测试运行时不再出现该 warning
- 最终执行完整 `python -m pytest`

## Files Expected To Change

- `src/knowmat/nodes/docling_parse_pdf.py`
- `tests/` 下新增或更新 docling 弃用测试
- 可能新增一个最小兼容修复点来隔离 `trustcall` / `langgraph` 弃用导入
- `CHANGELOG.md` 增加本轮治理记录

## Non-Goals

- 本轮不删除 `docling_parse_pdf.py`
- 本轮不做大版本依赖升级
- 本轮不同时推进日志体系改造
- 本轮不扩展到其他 warning 清理

## Verification

- 定向测试：docling 弃用行为
- 定向测试：warning 根因修复后不再输出对应弃用告警
- 全量测试：`python -m pytest`

## Risk Notes

- `docling` 入口仍可能被包外调用，因此只做弃用不做删除
- `trustcall` 根因修复需要控制改动范围，避免影响 extractor 行为
- 若最小兼容修复不可控，则退回到“显式记录 + 暂时降噪”的保守备选方案
