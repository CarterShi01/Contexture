# `core` — Contexture 自己是什么

`core` 回答「是什么」，`server` 回答「怎么跑起来」。这是包最顶层的一条分界，
其余所有分层都在这条线的两侧展开。

本层是纯声明：没有 I/O，没有线协议，没有 agent 运行时。**整个 `core` 不 import
`mcp` 或 `mcp_types`**——包括名字里带 mcp 的那个子目录。

## 三个子目录，三个不同的问题

```
core/
├── errors.py  types.py  constants.py  principal.py    共享地基
├── model/            一个能力**是什么**
├── disclosure/       它**在哪**，一次露出**多少**
└── mcp_interface/    在 MCP 三个原语上**暴露什么**
```

**`model/`** —— Role / Skill / Tool、披露生命周期，以及 `ControllerManager`。
节点知道自己叫什么，不知道自己挂在哪里：位置是树的答案，不是节点的。

业务写的是一个类，构造函数把身份交给基类、把成员建出来。**import 不构造任何
东西**——类是一个零参工厂，`ControllerManager` 调它那一次，是全包唯一一个节点
诞生的时刻，也是唯一能告诉它挂在哪(`path`)、能够到什么(`channels`)的时刻。
没有类体扫描，没有从类名或 docstring 的推导：后两者在 TypeScript 和 Go 里都
做不到，而这个对象模型要在三种语言里都成立。见 ADR 013。

**`disclosure/`** —— 把声明好的对象接成森林，给每个节点一个地址，并决定一次调用
答复哪些节点。**引用（ref）和层级（level）是在这里发明的，下面任何一层都没有。**
`model` 里的节点会把自己编译成 ROUTE 或 ACTIVE；这一层决定**问谁**——正是后者
让一片一万一千个角色的森林，和一片三个角色的森林一样便宜。

**`mcp_interface/`** —— 协议表面的声明，一个原语一个模块。见该目录的 README，
第一句就是那条禁令。

## 共享地基

`errors.py`、`types.py`、`constants.py`、`principal.py` 直接放在 `core/` 下：三个子目录都可以
站在它上面，它自己不站在任何东西上面。

这不是图省事。若把它们并进 `model/`，`mcp_interface` 为了拿一个异常类就得
import `model`——而那正是它唯一不能有的依赖。共享地基的存在，是三个子目录能
**互不依赖**而又不必各长一套异常体系的原因。

## 分层是被测出来的，不是被写出来的

`tests/test_layering.py` 里 `ALLOWED` 一张表就是上面这些话的可执行版本，
其中两条是承重墙：

```python
"core.__base__":      set()                 # 地基不依赖任何人
"core.mcp_interface": {"core.__base__"}     # 只站在地基上——不含 core.model
```

第二条的承重之处在于它**省略了什么**：`core.model` 不在里面。协议平面可以用
共享地基（异常、类型），但不认识对象模型。

本目录的 facade（`__init__.py`）按名惰性解析导出。急切导出会让这个文件
import 它自己的子层——那正是共享地基不允许有的依赖——也会让一个只想声明
Role 的项目白白加载 `disclosure`。
