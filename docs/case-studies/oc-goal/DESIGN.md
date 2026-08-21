# oc-goal — 当前设计

## 1. 目标

这是 one-creator 的局部重构样本。最终目标是逐个迁移其同构领域；选择 Goal，是因为
它同时包含持久化、跨行不变量、动态外键、CAS、只允许人修改的字段和单例文档，足以
暴露错误抽象，而又小到可以完整验证。

本轮的判断标准是：**业务代码只表达业务，Contexture 已经回答的问题不在模块里再答
一次。**

## 2. 五个边界

```text
oc_goal.app
  └── GoalDomain(Role)
      ├── ReviewAttention(Skill)
      └── ten Tools
            │
            ▼
       GoalRepository
            │
            ▼
       Area / Goal / Focus / ContextConfig
            │
            ▼
       compatible SQLite tables
```

每层只回答一个问题：

| 层 | 回答什么 |
| --- | --- |
| `Contexture` Application | 这个应用由哪些根和 host-facing 文档组成？ |
| `Role / Skill / Tool` | agent 看见什么，谁执行，如何调用？ |
| Pydantic model | 一个有效业务值长什么样？ |
| repository | 值存在哪里，怎样原子更新？ |
| SQLite schema | 与 one-creator 共享的字节如何排列？ |

## 3. 删除了什么

旧 case study 从 one-creator 复制了 `Citizen`、`Field`、`Schema`、`OperationSpec`、
`operation_context`、Store 注入、Manager 写契约和 Resource 内容对象。它能够工作，
但实质上在 Contexture 应用内部保留了第二套框架。

当前对应关系是：

| 旧机制 | 当前落点 |
| --- | --- |
| class-body Role/Skill/Tool 声明 | 显式构造函数；不推断名字、描述或成员 |
| `Manager` 和 decorator 反射 | 删除；一个 operation 就是一个普通 Tool 类 |
| `Citizen` 元类和 Field DSL | 普通 Pydantic model 与 `Annotated` 类型 |
| 手写 JSON Schema 反射 | 删除；Contexture 从 `invoke` 类型派生 |
| `OperationSpec` + context variable | 删除；写权限由 Tool 签名和 repository 方法边界表达 |
| injected store registry | 删除；`GoalRepository` 是显式基础设施边界 |
| 自定义 Resource 内容类 | 无参只读 Tool；Resource 只是稳定 URI 的第二个地址 |

旧运行时代码约 3900 行；当前应用源码约 1280 行，其中 SQLite DDL 和 seed 仍占约
250 行。缩减来自删除重复机制，不来自压缩业务说明或放弃数据库安全。

## 4. Contexture 对象如何分类

- `GoalDomain` 是 Role：它是一个责任边界，协调同一组能力。
- `ReviewAttention` 是 Skill：它需要模型根据证据判断，框架不能确定性计算结论。
- 查询和修改都是 Tool：它们有确定的输入和结果。
- current focus 与 object shapes 也是无参只读 Tool：内容在树中只有一份。
- 两个 Resource 只把上述 Tool 发布到 `goal://focus` 和 `goal://objects`；它们不拥有
  第二份内容。
- Area 和 Goal 实例不是 Role。数据库行不是路由分支；实例数量不能扩大能力树。

Goal 保持扁平，没有 child Role。一次任务通常同时需要 Area 和 Goal 能力，把它们拆成
互斥分支只会增加一次导航。

## 5. 业务不变量

仍然保留：

- Area 永不结束，拥有 `budget` 和 `standard`；Goal 有终点，拥有 `horizon` 和
  `success`。
- agent-facing Tool 的参数中没有 Area 的 `budget/status`，也没有 Goal 的 `status`。
- 新 Area 固定为 `budget=0, status=paused`。
- active Area 的预算合计必须为 100。
- Goal 必须属于当前 active Area。
- 已有 Area/Goal 的修改必须提供 `expected_revision`；比较发生在
  `BEGIN IMMEDIATE` 事务内。
- Goal ContextConfig 是严格嵌套模型，不接受未知字段、物理路径、重复 binding id 或
  Goal 不允许的 inheritance。
- Focus 空更新被拒绝。

约束只有两个合理位置：能由一个值判断的在 Pydantic model；需要数据库当前状态或
事务的在 repository。Tool 只负责一个 use case 的参数和返回形状。

## 6. 与 one-creator 共享数据库

三张表的列和索引保持兼容，`user_version` 不由本模块写入：

- 打开 one-creator 的 `oc.db` 时，`CREATE IF NOT EXISTS` 是 no-op；
- 独立创建库时只创建 Area、Goal、Focus，one-creator 仍可随后完成自己的其余迁移；
- JSON 文档和可查询列同时写入，读取时列值覆盖文档值，避免索引漂移；
- CAS 的读取、比较和 UPDATE 位于同一事务。

## 7. 没有伪装成已解决的问题

两个问题仍应由后续、独立设计处理，而不是塞回这个领域：

1. **实例级 context 编译。** `ContextConfig` 是 Goal 数据；按照 receiver/budget 编译
   `ContextPack` 是 host/application 的披露策略，不是静态 Role 树的第二份实现。
2. **来自 live store 的输入 enum。** Tool schema 能表达 slug 形状，但 active Area
   集合在运行时变化。目前 repository 做权威拒绝；若要在调用前给模型动态 enum，应该
   扩展 Contexture binding seam，而不是让 oc-goal 自建 schema compiler。

## 8. 对后续领域的结论

迁移另一个 one-creator 子模块时，先尝试同一映射：

```text
Manager.summary/instructions  → Role
需要模型判断的 compile/review → Skill
确定性 operation             → Tool
稳定 URI                     → Resource 指向一个无参只读 Tool
Citizen field contract       → Pydantic model
Store / transaction          → 独立 repository
```

只有当任务进入一个分支后不再需要兄弟分支时，才增加 child Role。不要迁移 Manager、
reflector、registration chain 或通用 Citizen 内核；若多个迁移后的领域确实出现相同的
业务基础设施，再从两个已验证实例中抽象，而不是从第一个样本预先造框架。
