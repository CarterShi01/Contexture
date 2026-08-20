# `core/mcp_interface` — 协议表面的声明

这里声明本服务器对外暴露的完整 MCP 表面,按协议的三个原语组织,一个原语一个模块。

**这里不 import `mcp`,也不 import `mcp_types`。** 一行都不行。

这个目录的名字里有 `mcp`,却是全项目最不该碰 SDK 的地方之一，所以这条写在最前面。
声明「暴露什么」和「怎么挂到 SDK 上」是两件事，后者属于 `contexture.server`。
`tests/test_layering.py` 把这条钉住了两次：`SDK_LAYERS` 不含本层，
`ALLOWED["core.mcp_interface"]` 是空集。任何一次违反都当场失败。

## 三个原语，按「谁控制」区分

这是协议自己的分法，不是本项目发明的：

| 原语 | 协议分类 | 谁决定何时用 | 本目录放什么 |
|---|---|---|---|
| **Tool** | model-controlled | 模型 | `tool.py` — 五个网关入口，整片森林都在它们后面 |
| **Resource** | application-controlled | 宿主应用 | `resource.py` — 宿主可自行取用的内容 |
| **Prompt** | user-controlled | 使用者 | `prompt.py` — 由人按名触发的能力 |

依据是 2026-07-28 revision 的原文：

> Prompts are designed to be **user-controlled** … **This refers to who decides
> when the prompt is used, not who authors its content. Prompt content is
> defined by the server.**

轴是**谁触发**，不是身份、作者或内容。

留意 Resource 是 **application**-controlled 而不是 user-controlled：宿主可以让人
挑，也可以自动附上，协议不规定。

### 宿主如何呈现，不属于协议

举例而非定义：Claude Code 把 prompt 呈现为斜杠命令，把 resource 做成可提及的附件。
Codex 与 Cursor 各有各的做法，`docs/verification/hosts.md` 记录了实测到哪一步。
**任何一种呈现都不能写进本目录的定义**，否则就是把某一个宿主的界面细节固化成了协议。

## 与 `core/model` 的关系：没有依赖关系

`core/model` 的 Role / Skill / Tool 全部落在 **Tool** 那一行——它们由模型决策，
经五个网关入口披露。本目录的 Resource 与 Prompt 落在另外两行，由宿主或人触发。

两者在类型上、依赖上都不相交：

- 这里的对象**不是** `ContextNode`，没有 compile 生命周期，不进森林；
- 它们持有的是引用**字符串**，不是对象引用——与 `Skill.uses` 同一个理由：
  字符串走不进去，所以这里够不到森林，森林也够不回来；
- `core/model` 不知道有「人」这个概念，正如它不知道有 ref、有 JSON Schema、有 mcp。

## 一条命名上的历史

`core` 里曾经有一个也叫 `Resource` 的类，它是**模型平面**的节点，与本目录的
`Resource` 不是同一个概念。那个类已删除，理由见 ADR 009；此后 `Resource` 这个名字
在本仓库只有一个意思，就是 MCP 的那个原语。
