# ADR 017 — Application 是惰性声明，不是第二个 Server

**Status:** accepted, implemented
**Date:** 2026-08-21

## Context

内核已经有清楚的运行时分工：`ControllerManager` 持有与供给、`Index` 编译地址与
binding、`Disclosure` 决定呈现、`ContextureServer` 放到 MCP transport。业务用户却
仍要在 TOML 中重复 name/roots/channels/publish，或在 `main()` 手工重组这些对象。
这让“第一份文件是什么”和“默认命令与高级入口是不是同一应用”没有答案。

曾经的 `ContextureApp` 在模块 import 时就构造并编译了森林；那既违反 ADR 013 的
“构造函数即声明”，也把业务组合和运行中的 server 混成一个对象。

## Decision

新增顶层公开值对象 `Contexture`，作为业务项目的唯一 Application declaration：

```python
app = Contexture(name="operations", roots=(OperationsRole,))
```

它只保存 root、Channels、Prompt、Resource 的类 factory；构造时不实例化节点、不打开
连接、不创建 Index/Disclosure/Server，也不导入 MCP SDK。每次 `compile_application(app)`
都创建一棵新森林，并沿既有的 `ControllerManager → Index → Disclosure →
ContextureServer` 路径完成构建。

`[tool.contexture]` 只命名这个对象：

```toml
[tool.contexture]
app = "operations:app"
```

CLI 的 check/list/inspect/call/serve 与高级入口的 `serve(app, options)` 共享 compiler；
它们不是两套装配 API。历史 table 和显式 Role target 暂由 CLI adapter 兼容，但不再是
新项目教学路径。

## Consequences

- 新用户默认不写 `main()`，但嵌入已有进程仍可从同一 `app` 写 `main()`。
- Role、Skill、Tool 在脚手架第一屏同时出现；Application 只负责组合，不增加第四种
  capability node。
- 公开 Python API 通过 facade 和 stub 交付，不要求移动内部平铺目录或创建 runtime
  `interfaces` 包。
- Go、TypeScript、PHP 可用 struct/object/DTO 表达同一 declaration；Python 的 class
  factory 语法不是跨语言协议。
- Application 编译层是唯一新增桥接层，不吸收已有 Manager、Index、Disclosure 的职责。
