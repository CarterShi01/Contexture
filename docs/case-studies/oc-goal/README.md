# oc-goal

`oc-goal` 是从 one-creator 抽出的真实 Goal 领域，也是 Contexture 重构
one-creator 的第一个迁移样本。它保留原数据库结构、CAS 写入和核心业务约束，但不再
携带 one-creator 自己的声明、反射和 MCP 注册框架。

这里要验证的不是“Contexture 能不能包住旧代码”，而是一个业务模块能否只剩下：

```text
Contexture 声明     app → Role → Skill / Tool / Resource
业务               Pydantic models + use-case tools
基础设施           one SQLite repository
```

- [DESIGN.md](DESIGN.md) 解释边界选择和旧、新结构的对应关系。
- [PLAN.md](PLAN.md) 记录这次重做的验收条件，以及后续模块的迁移规则。

## 运行

```bash
cd docs/case-studies/oc-goal
uv run python -m oc_goal.seed
uv run python check.py
uv run contexture check
uv run contexture list
uv run contexture serve
```

默认数据库位于用户数据目录。要使用临时库或指向 one-creator 的兼容 `oc.db`：

```bash
export OC_OBJECT_DB_PATH=/tmp/oc-goal.db
```

`seed` 只写空库；只要已经存在 Area，它就不做任何修改。

## 现在的结构

```text
oc_goal/
├── __init__.py      唯一 Application 声明和两个 Resource 地址
├── role.py          Goal 责任边界及成员清单
├── skills.py        模型执行的 attention review 方法
├── tools.py         10 个可执行能力；签名就是输入 schema
├── models.py        Area / Goal / Focus / ContextConfig 的唯一约束源
├── repository.py    查询、事务、CAS 和领域写入规则
├── db/schema.py     与 one-creator 相同的三张表
└── seed.py          显式样本数据
```

`Contexture` 不持有数据库，也不替业务决定权限和不变量。它负责能力树、渐进披露、
schema 派生、读写入口以及 MCP transport；这些职责在 `oc-goal` 中没有第二份实现。
