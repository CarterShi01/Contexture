# `core` — Contexture 自己是什么

`core` 回答「是什么」，`server` 回答「怎么跑起来」。这是包最顶层的一条分界，
其余所有分层都在这条线的两侧展开。

本层不认识线协议：**整个 `core` 不 import `mcp` 或 `mcp_types`**——包括名字里带
mcp 的那个子目录。它认识生命周期：句柄在第一个请求之前打开、最后一个请求之后
关闭，因为节点只有在被注册的那一刻能被告知自己挂在哪 (`path`)、能够到什么
(`channels`)，两者同源，拆开就是给同一个事实两个时刻。

## 两个子目录，两个不同的问题

```
core/
├── errors.py  types.py  constants.py  principal.py    共享地基
├── model/            内核：一个能力**是什么**、它**在哪**、agent **能做什么**
└── mcp_interface/    在 MCP 三个原语上**暴露什么**
```

**`model/`** —— Role / Skill / Tool、披露生命周期、`ControllerManager`、
`ContextTree`，以及 `system_api` 里那四个入口。

业务写的是一个类，构造函数把身份交给基类、把成员建出来。**import 不构造任何
东西**——类是一个零参工厂，`ControllerManager` 调它那一次，是全包唯一一个节点
诞生的时刻。没有类体扫描，没有从类名或 docstring 的推导：后两者在 TypeScript
和 Go 里都做不到，而这个对象模型要在三种语言里都成立。见 ADR 013。

节点仍然不知道自己挂在哪——它是被告知的，而且是以 segments 而不是以地址被告知。
**变的只是「谁把 segments 拼起来」**：`ContextTree` 拼引用、决定一次调用答复
哪些节点，而它就住在这里，不再是上面一层。因为「一个节点把自己披露出来」和
「一次调用披露哪些节点」是同一个机制的两半——把它们放在两个目录里，代价是
`tree.py` 里五处 `isinstance` 替节点回答本该节点自己回答的问题。见 ADR 014。

节点向一个 `Disclosure` 视图要两样它算不出来的东西：自己的地址，和自己的
schema。`ContextTree` 是那个视图；`_Alone` 是没人给视图时的兜底，于是 `model`
不需要树、也不需要服务器，自己就能把一份声明逐层披露完。

**`mcp_interface/`** —— 协议表面的声明，一个原语一个模块，也是**开放给业务
扩展的那一面**：

| 原语 | 业务写什么 | 指向 `core` 的什么 |
| --- | --- | --- |
| prompt | `class Command(Prompt)`，`opens=…` | 一个节点，典型是 skill |
| resource | `class Runbook(Resource)`，`opens=…`、`uri=…` | 一个只读无参 Tool |
| tool | **什么都不写** | 被内核那四个入口占满 |

第三行不是缺口，是这个设计的全部要点：tool 平面上多一个条目，就是每个 session
无条件付一份 schema。所以 `tool.py` 只声明四个**名字**，描述和行为都在
`core/model/system_api.py`。

## 共享地基

`errors.py`、`types.py`、`constants.py`、`principal.py` 直接放在 `core/` 下：
两个子目录都可以站在它上面，它自己不站在任何东西上面。

这不是图省事。若把它们并进 `model/`，`mcp_interface` 为了拿一个异常类就得
import `model`——而那正是它唯一不能有的依赖。分隔符和四个入口名字也在这里，
理由同源：三个互不 import 的层都持有 ref 字符串，共享地基是它们能指同一个东西
而不各存一份的唯一办法。

## 分层是被测出来的，不是被写出来的

`tests/test_layering.py` 里 `ALLOWED` 一张表就是上面这些话的可执行版本，
其中两条是承重墙：

```python
"core.__base__":      set()                 # 地基不依赖任何人
"core.mcp_interface": {"core.__base__"}     # 只站在地基上——不含 core.model
```

第二条的承重之处在于它**省略了什么**：`core.model` 不在里面。协议平面可以用
共享地基（异常、类型、名字），但不认识对象模型——它只持有名字和 ref 字符串，
所以里面没有任何东西能伸进森林，森林里也没有任何东西能伸回来。

本目录的 facade（`__init__.py`）按名惰性解析导出。急切导出会让这个文件
import 它自己的子层——那正是共享地基不允许有的依赖。同理，`model/__init__.py`
只导出一份声明写得到的东西：`tree` 和 `system_api` 要按模块路径去拿，一个只想
声明 Role 的项目不该为此加载整片森林和四个入口。
