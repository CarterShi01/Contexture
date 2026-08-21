# oc-goal — 重做计划与验收记录

本文取代 2026-08-19 的旧计划。旧计划基于已经删除的 Contexture class-body 声明、
旧 Resource 模型和旧启动方式，不再用于执行。

## 目标状态

完成时，oc-goal 应当是当前 Contexture Application 的正常用户，而不是框架兼容层：

- 从 `oc_goal:app` 惰性加载；import 不构建能力树、不打开数据库；
- 所有节点使用显式构造函数声明；
- 一个 Role、一个 Skill、十个 Tool、两个 Resource URI；
- Tool 的类型签名是 agent 输入 schema 的唯一来源；
- Pydantic model 是持久化值约束的唯一来源；
- repository 保留 SQLite/CAS，Contexture 不持有业务状态；
- 不存在 `Manager`、decorator reflector、自定义 schema compiler、operation context 或
  store registry 的本地副本。

## 执行阶段

### 1. 重新建立基线 — 完成

- 确认旧 `GoalDomain()` 在当前 Role API 上直接失败。
- 读取 ADR 013/016/017，按“构造函数即声明、register/compile/disclose、Application
  是惰性值”重新划分边界。
- 从当前 one-creator 核对 Goal 的业务权威：Area/Goal 分形、human-owned 字段、CAS、
  active budget 总和与 ContextConfig。

### 2. 删除第二套框架 — 完成

- 删除 `citizens/`、旧 `surface.py`、`wiring.py` 和通用 `db/rows.py`。
- 用 `models.py`、`repository.py` 代替，不保留兼容 shim。
- 保留与 one-creator 共享数据库所需的三表 DDL。

### 3. 迁移到当前 Contexture — 完成

- 增加 `Contexture(name="oc-goal", roots=(GoalDomain,))`。
- Role/Skill/Tool 全部改为显式构造。
- Skill `uses` 使用完整 ref，并在 Index 编译时校验。
- 内容先作为树中的无参只读 Tool，再由 Resource 发布稳定 URI。
- `[tool.contexture]` 只指向 `oc_goal:app`。

### 4. 生产路径验证 — 完成

`check.py` 必须经 `compile_application → TypeHintBinding → SystemAPI` 调用，而不是直接
调用 Tool 方法。验收覆盖：

- 两次编译产生互不共享的节点；
- 12 个 ref 完整且稳定；
- schema 含 slug/长度/嵌套 ContextConfig 约束，且不含 human-owned 字段；
- seed、列表、单项读取、两个 Resource 内容；
- 新 Area 的暂停/零预算默认；
- CAS 成功与 stale revision 拒绝；
- inactive Area 外键拒绝；
- ContextConfig URI 拒绝；
- Focus 空更新拒绝；
- read/write gateway 双向错门拒绝。

### 5. 仓库级回归 — 待每次变更执行

```bash
cd docs/case-studies/oc-goal
uv run python check.py
uv run contexture check
uv run contexture list

cd ../../..
uv run python run_tests.py
```

本次重做的结果：case study 检查通过；CLI 报告 1 Role、1 Skill、10 Tool；真实
stdio MCP 客户端完成 discover/open/invoke/resource read；仓库全量 347 项测试通过。

## 下一个子模块的启动门

只有以下事实成立，才开始迁移 one-creator 的第二个领域：

1. oc-goal 的本地检查、CLI check/list 和 Contexture 全量测试全部通过；
2. 没有为了 oc-goal 的个例修改 Contexture 内核；
3. 迁移规则能明确区分 Role、Skill、Tool、Resource、model 和 repository；
4. 新领域先记录行为基线，再删除其旧 Manager/reflector；
5. 只有两个迁移实例确实重复的业务设施才进入共享抽象候选。

优先选择与 Goal 结构不同的领域，以检验规则而不是复制答案。旧计划建议的
`project / project-intent / workitem` 仍是有价值的下一组，因为它们能验证 child Role
是否真的是“互斥进入的责任分支”。
