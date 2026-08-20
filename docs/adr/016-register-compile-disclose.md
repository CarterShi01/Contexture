# ADR 016 — 注册、编译、披露

**Status:** proposed
**Date:** 2026-08-21

**取代 [ADR 015](015-the-server-is-an-object.md) 的第 1–3 节所选的实现形态。**
ADR 015 的判断是对的——`server` 该是一组各管一件事的对象——它落地出来的
`Assembly` / `Dispatch` / `projection/` 三件东西也确实比 `app.py + binding.py`
清楚。但那次划分是**按对象长在哪里**切的，不是按**每件功能发生的频率**切的，
所以留下了两个跨接缝的对象。这份 ADR 重切一次。

**前提，不动：** ADR 009（协议平面不是对象模型）、ADR 010（目录就是架构）、
ADR 013（构造函数即声明）、ADR 014（导航属于内核）。

---

## Context

四个症状，全部能在代码里指出来。

### 1. `ContextTree` 是一个壳，而且持的是活引用

`ContextTree` 是冻结的 dataclass，但它一行数据都不存：

```python
tree.find(ref)    → manager.find(segments)      # tree.py:327
tree.ref_of(node) → manager.address_of(node)    # tree.py:163
tree.roots        → manager.roots
```

生产代码里，`ControllerManager` 的 `find` / `walk` / `of_kind` / `address_of`
**只有 `ContextTree` 在调**。那一整套查询接口存在的唯一目的，就是给树转发。

于是"tree 和 manager 是什么关系"这个问题会被每一个新读者问一遍，而答案是
"同一批数据的两个相位"——**相位不是职责**，两个对象只差一个相位，读者每次都
得先判断此刻该调哪个。

更实的一条：树持的是**活引用**，不是快照。封树之后再往 manager 里注册一个根，
正在服务的树的 `roots` 会跟着变，而封树时跑的两个全森林校验
（`_reject_unresolvable_uses`、`_reject_ambiguous_names`，都在 `__post_init__`）
**不会重跑**。今天不出事靠的是"没人这么写"这条约定。协议要求服务期的表面不
变，这件事应该是结构保证的。

### 2. `Dispatch` 跨了三个不同的发生频率

把这套系统必须做的事按发生频率排一次：

```
进程一次      具现 · 定址 · 供给 · 开门 · 承载
每工具一次    派生（invoke 的类型 → 输入 schema）
每请求一次    描述 · 定界 · 解析 · 准入 · 校验 · 调用
```

中间那一行只有一件事，而且**没有对象拥有它**。它今天被做成了一个全局单例加
一张以 `id()` 为键的字典（`dispatch.py` 的 `_derived`），所以需要一整段注释解
释"`id()` 只在活对象之间唯一、这个缓存为什么必须同时持有 tool 引用"。那段注
释不是在解释一个设计，是在补偿一个错位：**每工具一份的东西被实现成了一张全
局表**。

而"校验"用的是同一次派生的结果。`Dispatch` 因此同时是描述侧和执行侧的东西，
于是它必须**同时交给两个所有者**：

```python
dispatch = Dispatch()
tree     = manager.sealed(schema_of=dispatch.schema)     # 一半给树
assembly = Assembly.of(tree, execute=dispatch.execute)   # 另一半给内核
```

一个对象必须交给两个不同的所有者，通常说明它放错了地方。

### 3. `Assembly` 抱着四样东西，独有的只有两样

`Assembly` 的字段是 `tree` / `api` / `prompts` / `resources`。其中"什么被服务"
树已经回答过一次，`api` 本来就是围着树转的。它**真正独有的只有那两份菜单**。

而那两份菜单是以一个混装列表进来的：

```python
PUBLISHED = (CrashLoopRunbookDocument, RollbackPolicyDocument, RollBackARelease)
```

`Assembly.of` 收到之后用 `isinstance` 分拣成两堆。**运行时分拣，是"本来就该分
开写"的信号**——写的人明明知道那是命令还是文档，是袋子把这个信息丢掉了，然后
运行时再猜回来。

这一条还违反了 `ControllerManager` 那边**自己写过的论证**：

> 三个方法，一个 kind 一个。在调用处点明是哪一种，等于把"这底下能挂什么"说在
> 读者正在看的地方，而不是让他从参数类型去推。这也是另外两种语言唯一能共享的
> 形状：Go 那边是一个 kind 一个 typed slice，而不是一个 `[]any`。

`published: Sequence[Any]` 正好是这段话反对的那个 `[]any`。

### 4. 职责错位散落在四处

- **全森林校验有两个家。** manager 的 `_absorb` 查"实例挂两处 / 绕成环"，
  tree 的 `__post_init__` 查"`uses` 指的能力存不存在 / 名字有没有歧义"。四个
  检查，两个地方，性质完全相同——都是"看全森林才能做"。

- **树上有五个跟披露无关的遍历。** `matching_refs`（命令补全）、`signpost`
  （命令抬头的路标）、`roles_by_level`（instructions 名册与 inspection）、
  `roles_with_refs`（`contexture list`）、`crossings`（inspection）。它们服务四
  个不同的外部消费者，堆在树上只因为树是唯一一个能只读地拿到整片森林的对象。
  `tree.py` 有 470 行，胖在这里。

- **宿主那扇门绕开了内核。** `projection/resources.py` 的 `_reader` 直接
  `tree.tool(ref).invoke()`，不经过 `SystemAPI`、不经过 `execute` seam。后果是
  这条路径没有参数校验、没有调用者身份、失败也不经 `translated()`。三扇门里两
  扇走内核，一扇是私接线。

- **`instructions` 是第四个安装器，却不在 `projection/` 里。** 它同样是"把树投
  到协议上的一段东西"，位置却在 `ContextureServer._surface()` 里顺手调。

- **节点身上的 `path` 是第二份地址。** `manager._absorb` 写 `node.path = path`，
  同一时刻 manager 自己的表里也记了一份。正式路径读 manager 那份；`node.path`
  全仓库只被 `_Alone.ref_of` 读一次，也就是"这个节点没进任何森林"时的兜底。

### 5. 命名对不齐

```
core/mcp_interface/     tool.py      prompt.py     resource.py
server/projection/      gateway.py   prompts.py    resources.py
                        ^^^^^^^^^^ 唯一一个只在一侧存在的名字
```

以及一个真冲突：`core/mcp_interface/tool.py` 里的 `PUBLISHED` 是那四个固定入口
的名字（业务永远改不了的），`demo/server.py` 里的 `PUBLISHED` 是业务自己写的发
布清单。同名，意思正好相反。

---

## 借鉴：检索系统的三分法

读/写不是职责划分，是相位划分。检索系统里那三个角色回答的问题是不重叠的，这才
是可用的划分方法：

| 检索系统 | 回答什么 | 拥有什么 |
| --- | --- | --- |
| **DataManager / Store** | 存在什么、归谁、怎么开关 | **数据** |
| **Index** | 这个 id 是谁；按前缀、按类型、按层怎么找 | **算出来的事实** |
| **Retriever** | 这一次给几条、怎么排、呈现成什么样 | **策略** |

搬过来：

| 这里 | 回答什么 | 拥有什么 |
| --- | --- | --- |
| **ControllerManager** | 存在什么、能碰到外面什么、什么时候开关 | 业务交来的实体 |
| **Index** | 这个门牌号是谁；前缀匹配、按层遍历、往上走；每个工具的 schema 和跑法 | 框架算出来的事实 |
| **Disclosure** | 这一次给几层、给卡片还是给全文 | 披露策略 |

**Retriever 不拥有数据，它拥有"给多少"的策略；Store 不拥有策略；Index 是中间
那层"算出来的事实"。**

这一刀不是从原则推出来的——`tree.py` 里那五个遍历方法**全部**是"在地址空间里找
东西"，一个都不是披露；剩下的 `skeleton` / `open` / `card_of` / `card_for` 才是。
代码已经按这条缝长好了，只是没人把它切开。

**顺带一个对得上的类比：工具的 schema 就是它的 embedding。** 由一个外部模型算
（模型不属于 store）、每个条目在**建索引时**算一次、存在**索引里**而不是条目身
上、检索时用一次展示时再用一次。工具的 schema 一模一样：由外部规则算（SDK，且
三种语言各写各的）、建索引时每个工具算一次、存在索引里、`open` 贴卡片用一次、
`invoke` 校验参数再用一次。**所以绑定表属于 Index。**

---

## Decision

### 1. 三个对象，三个不重叠的问题

```
ControllerManager   存在什么、能碰到什么、什么时候开关
Index               关于地址和实体的事实
Disclosure          这一次给多少、给成什么样
```

`ControllerManager` 保留原名（它确实是 controller 的持有者），但**瘦身**：只留
持有、查重、发 channels、`provisioned` 生命周期。它今天那一整套查询接口
（`find` / `walk` / `of_kind` / `address_of` / `parent_of` / `children_of`）搬去
`Index`。

### 2. `Index` 不持有 `ControllerManager`

```python
index = Index.of(manager, bind=TypeHintBinding())
```

读一遍 manager，产出表，**之后不再持有它**。表里存节点对象的引用，所以查到 ref
就直接拿到实体，不需要回头问 manager。

这条是这次重构的关键：**"服务期表面不变"从约定变成结构。** 索引建完，manager
再怎么变都与这个索引无关。

### 3. 建索引是一次编译

这个心智模型比 "seal" 说得清，而且它一口气解释了为什么所有检查都挤在这一刻：

```
源       声明的森林
编译期   建符号表（地址）· 类型检查（全森林校验）· 代码生成（派生绑定）
目标     不可变的 Index
```

**今天分散在两处的四个全森林校验，全部收到这一刻。** `ControllerManager` 注册
期只需要一个"这实例见过没有"的集合来防重复，不需要地址表。

`manager.sealed()` 这个方法去掉。`Index.of(manager, ...)` 在视觉上就说明了"从它
建出来，不归它管"——这正是这次要拆掉的错觉。

### 4. `Binding` 取代 `Dispatch`，两个 seam 并成一个

每个工具在编译时拿到一份绑定，两个成员：

```python
class Binding(Protocol):
    @property
    def schema(self) -> JsonObject: ...                    # 每工具算一次
    async def call(self, arguments, context) -> Any: ...   # 每请求
```

- `core` 定义这个 Protocol 和一份 `PlainBinding` 默认（空 schema、直接调），
  给没有 SDK 在场的测试和 `contexture list` 用。
- `server` 提供 `TypeHintBinding`：SDK 派生 + 去 `title` + `bound(principal)`。

由此：

- `Dispatch` 整个删除，`id()` 缓存和那段注释一起消失——**索引的键是门牌号**，
  本来就稳定、本来就唯一。
- `ContextTree.schema_source` 和 `SystemAPI.execute` 两个 seam 并成一个 `bind`。
- 今天两处默认（`_no_schema` 和 `_plain_invoke`）合成一处 `PlainBinding`。
- **宿主那扇门自动归队**：它拿的也是索引里那份绑定，所以校验和身份绑定天然覆
  盖第三条路径，不用专门去修。

**跨语言：** `bind` 是一个 Strategy。Python 读签名、Go 反射参数结构体加 tag、
TS 用 schema 对象反推类型。三种做法不同，产出的 JSON 必须相同——这是 README
"钉住到达线上的那份 JSON、不钉怎么派生出来的"那条的具体兑现。名字按做法起：
`TypeHintBinding` / `StructTagBinding` / `SchemaObjectBinding`，三个并排一眼看
出差别在哪。

### 5. `Disclosure` 消费 `Index`，不转发

`ContextTree` 改名 `Disclosure`，只剩披露：`skeleton` / `open` / `card_of` /
`card_for` / `schema_of`。

判据，写死成一条测试：

> **转发就是壳，消费才是协作。`Disclosure` 的公开方法里不许出现纯转发。**

外部要遍历地址空间——补全、路标、名册、inspection——**直接找 `Index`**，不经过
`Disclosure`。

`node.py` 里那个 Protocol `Disclosure` 改名 `View`：节点 `compile(level, view=…)`
的参数本来就叫 view，这个名字不是发明的。

`node.path` 那个戳去掉，`_Alone` 兜底改用节点自己的名字。**节点身上从此只剩
`channels` 一样框架填的东西**——判据是：

> 节点自己要用的，放节点身上；别人问起它才需要的，放索引里。

`channels` 是节点在自己 `invoke` 里要拨的电话，留下。门牌号和 schema 只在"别人
渲染它、别人调它"时才需要，进索引。

### 6. `Surface` 取代 `Assembly`：三扇门，各自完整

`Assembly` 那个数据袋删除。三扇门各自拥有**它的条目、它的规则、它的安装**：

```
server/surface/__init__.py   Surface（组合：三扇门都建好了才动手安装）
server/surface/tools.py      Tools       四个固定入口 + 开场规矩
server/surface/prompts.py    Prompts     命名命令 + goto + 补全
server/surface/resources.py  Resources   公开地址
```

- `projection/` 改名 `surface/`——包名该命名概念，概念是"这台服务器的表面"。
- `gateway.py` → `tools.py`，类 `Gateway` → `Tools`，**唯一一个只在一侧存在的
  名字消失**。
- `instructions` 并入 `surface/tools.py`——它是模型那扇门的说明书，不该在容器
  里顺手调。第四个安装器归队。
- `goto` 和它的补全明确写在 `surface/prompts.py` 里，不再是安装时偷偷多开的一
  扇门。
- `Surface` 负责三件事：**先全部构造、再全部安装**（今天靠 `build()` 的约定做
  到，为的是报错时 SDK 上还没写进任何东西）；把"人占了哪些 ref"交给内核；整体
  交给容器。

**三扇门运行时只跟内核说话**，不直接碰索引。构造期的校验需要看索引里的事实
（比如宿主那扇要确认它指的工具只读且无参），由内核多暴露一个只读查询给启动期
用——多一个方法，换一条干净的依赖线。

### 7. 三个平面在签名里并排；能不能改，由能不能继承决定

今天这件事已经是类型层面的事实，只是没被说出来：

```
core/mcp_interface/prompt.py     导出 Prompt      可继承 → 你能加
core/mcp_interface/resource.py   导出 Resource    可继承 → 你能加
core/mcp_interface/tool.py       一个类都不导出    没得继承 → 你加不了
```

把它显式化。`tool.py` 里那个裸元组 `PUBLISHED` 升级成一个**不可继承**的类型加
唯一实例：

```python
@final
class ToolPlane:
    """这个平面上的四个入口。只有这一个值，你造不出第二个。"""
    names = (DISCOVER_TOOL, OPEN_TOOL, INVOKE_READ_ONLY_TOOL, INVOKE_TOOL)

    def __init_subclass__(cls, **kw):
        raise TypeError(
            "tool 平面不可扩展：业务能力通过 payload 到达 agent，不通过注册。"
        )

TOOLS = ToolPlane()
```

于是服务器签名三个平面并排：

```python
class ContextureServer:
    def __init__(
        self,
        index: Index,
        *,
        name: str = "contexture",
        tools: ToolPlane = TOOLS,              # 不可继承 → 唯一值 → 改不了
        prompts: Sequence[Prompt] = (),        # 可继承 → 能加
        resources: Sequence[Resource] = (),    # 可继承 → 能加
    ) -> None: ...
```

**这三行的类型就是 README 里那张表。** 读签名的人不用翻目录也不用读文档，看类型
就知道哪个平面开放、哪个封死。

`tools=` 在运行时不做任何选择——这一点要说在明处。它的价值全在"签名即规则表"，
而 Go 和 TS 那两个实现将来的构造函数签名，会是移植者第一眼看的东西。

### 8. 命名对齐 MCP 原语，"谁决定"留在文件头

一套词汇，两侧并排：

```
core/mcp_interface/   tool.py     prompt.py    resource.py     ← 这个平面业务能写什么
server/surface/       tools.py    prompts.py   resources.py    ← 这个平面怎么焊上去
```

`ls` 两个目录，一一对应，没有例外。

**明确撤回**：讨论中曾提议把 `Prompt` → `Command`、`Resource` → `Document`，理
由是"它们不是 MCP 原语，是只揣着一个 ref 的指针"。撤回，因为那件事一句 docstring
就说清了，不值得让**声明侧、投影侧、`spec/`、协议本身**分成两套词汇。这个框架要
在三种语言里成立、要靠 golden 文件对齐，一套词汇比多一层解释重要。

同理撤回 `AgentDoor` / `PersonDoor` / `HostDoor`。"谁决定"这个洞见不丢——它留在
每个文件的第一行，`mcp_interface/__init__.py` 今天已经这么写了：

> 这三个是按**谁决定何时使用**分的——这是协议自己的轴，不是本项目的。

---

## 目标形状

### 目录

```
core/model/
    manager.py      ControllerManager   持有 · 查重 · 发 channels · 生命周期
    index.py        Index               地址表 · 绑定表 · 遍历 · 全森林校验   ← 新
    binding.py      Binding · PlainBinding                                   ← 新
    disclosure.py   Disclosure          skeleton · open · card                ← 原 tree.py
    system_api.py   SystemAPI           四个调用 · 准入 · 话术
    node.py role.py skill.py tool.py channels.py                             ← 不动

core/mcp_interface/
    tool.py         ToolPlane · TOOLS   ← 原 PUBLISHED
    prompt.py resource.py               ← 不动

server/
    binding.py      TypeHintBinding                                          ← 新
    server.py       ContextureServer
    options.py identity.py messages.py launch.py                             ← 不动
    surface/
        __init__.py Surface
        tools.py    Tools      四个入口 + instructions                        ← 原 gateway.py
        prompts.py  Prompts    命令 + goto + 补全
        resources.py Resources 公开地址
```

删除：`server/dispatch.py`、`server/assembly.py`、`server/instructions.py`
（并入 `surface/tools.py`）。

### 对象关系

```
ControllerManager ──读一遍──► Index ◄──── Disclosure
  持有实体 · 发电话线            地址表      给几层 · 渲染成什么样
  开合生命周期                   绑定表
  （建完即断，不被持有）            ▲            ▲
                                  └── SystemAPI ┘
                                     四个调用 · 准入 · 话术
                                          ▲
                              ┌───────────┼───────────┐
                            Tools      Prompts    Resources
                              └────── Surface ─────┘
                                          ▲
                                  ContextureServer ──► MCPServer (SDK)
```

`Index` 被 `Disclosure` 和 `SystemAPI` 同时持有，这不是问题：**不可变快照被共享
是正常的，可变对象被共享才是问题**——今天的麻烦恰恰是 manager 可变却被树持着。

### `main`

```python
def main() -> None:
    manager = ControllerManager(channels=ClusterChannels(...))
    manager.register_role(KubernetesPlatform)

    index = Index.of(manager, bind=TypeHintBinding())

    ContextureServer(
        index,
        name="contexture-demo",
        tools=TOOLS,
        prompts=[RollBackARelease],
        resources=[CrashLoopRunbook, RollbackPolicy],
    ).start(ContextureOptions(transport="stdio"))
```

一行一个阶段：**注册 → 编译 → 开哪几扇门 → 跑**。没有一行是接线。

对比今天：

```python
manager  = ControllerManager()
manager.register_role(KubernetesPlatform)
dispatch = Dispatch()                                            # 接线
tree     = manager.sealed(schema_of=dispatch.schema)             # 接线
assembly = Assembly.of(tree, execute=dispatch.execute, published=PUBLISHED)
ContextureServer(assembly, name="contexture-demo").start(...)
```

`main` 里露出来的对象，判据是**业务对它有真实输入**：注册表（根、电话线）、索引
（用哪条绑定规则）、服务器（名字、三个平面）、选项（怎么跑）。`Disclosure`、
`SystemAPI`、`Surface` 不出现——不是被藏起来，是它们没有可被决定的东西。

### 命名对照

| 今天 | 之后 | 理由 |
| --- | --- | --- |
| `ContextTree` | `Disclosure` | 剩下的只有披露策略，它不再持有树 |
| `Disclosure`（node.py 的 Protocol） | `View` | `compile(level, view=…)` 的参数本来就叫 view |
| — | `Index`（新） | 地址表 + 绑定表 + 遍历 + 全森林校验 |
| `Dispatch` | `Binding` / `TypeHintBinding` | 每工具一份，不是全局服务 |
| `manager.sealed(schema_of=…)` | `Index.of(manager, bind=…)` | 它做的是建索引，不是封 |
| `Assembly` | 删除 | 拆进三扇门 |
| `server/projection/` | `server/surface/` | 包名该命名概念 |
| `gateway.py` / `Gateway` | `tools.py` / `Tools` | 两侧对齐 MCP 原语 |
| `mcp_interface` 的 `PUBLISHED` | `ToolPlane` / `TOOLS` | 不可继承的类型；同时解掉与 demo 的重名 |
| demo 的 `PUBLISHED` | `prompts=` / `resources=` 两张清单 | 消掉运行时分拣 |
| `server/instructions.py` | 并入 `surface/tools.py` | 第四个安装器归队 |

---

## 执行计划

七步。**每一步单独一个 commit，单独跑得过全量测试**，任何一步都能停下来发布。

### 步骤 0 — 先立护栏（不改产品代码）

README 里说好的 `spec/golden/` 还不存在。这次重构的安全网就是它，所以先建第一版。

- 把 demo 在 stdio 下的这几样录成 golden 文件：`tools/list`、`prompts/list`、
  `resources/list`、`initialize` 返回的 instructions 全文、`contexture_discover`
  的完整 payload、对每个 role 各一次 `contexture_open` 的完整 payload、五种查找
  失败和两种走错门的完整句子。
- 加一个测试：跑一遍 demo，逐字节比对。

**验收：** 现有 7047 行测试全绿 + golden 建立。此后每一步的验收都包含"golden 逐
字节不变"。

### 步骤 1 — `Binding`：拆掉 `Dispatch`

- 新增 `core/model/binding.py`：`Binding` Protocol + `PlainBinding`。
- 新增 `server/binding.py`：`TypeHintBinding`（SDK 派生 + 去 title + 绑 principal）。
- `ContextTree` 暂时接受 `bind=`，在 `__post_init__` 里建绑定表；`schema_of` 从表
  取，`SystemAPI.execute` 改为从表取绑定。
- `resources.py` 的 `_reader` 改走绑定——**宿主那扇门归队**。
- 删除 `server/dispatch.py`。

**验收：** `test_projection` / `test_system_api` / `test_server` 全绿；golden 不变。
新增两条测试：宿主读一个带参数的工具会被拒（今天不会）；宿主路径上
`current_principal()` 能读到调用者（今天读不到）。

> 这一步会**改变一处外部可见行为**：宿主读资源现在会做参数校验、会绑身份。这是
> 修 bug，不是重构——在 CHANGELOG 里单独写一行。

### 步骤 2 — `Index`：从 tree 和 manager 里抠出来

- 新建 `core/model/index.py`。搬入：
  - 从 `manager`：`_by_path` / `_address_of` / `_parent_of` / `_by_kind` 四张表，
    `find` / `walk` / `of_kind` / `address_of` / `parent_of` / `children_of`。
  - 从 `tree`：`matching_refs` / `signpost` / `roles_by_level` / `roles_with_refs`
    / `nodes_with_refs` / `crossings`，以及绑定表。
  - 四个全森林校验合并到 `Index.of` 里：实例挂两处、绕成环、`uses` 不可解析、
    名字有歧义。
- `ControllerManager` 瘦身到：三个 `register_*`、`roots` / `roles` / `skills` /
  `tools`、`rebind_channels`、`provisioned`、注册期防重复用的 id 集合。
- **断开 tree → manager 的引用。**
- 改四个消费者：`server/instructions.py`、`server/projection/prompts.py`（补全与
  路标）、`cli/main.py`、`inspection.py`。

**验收：** `test_manager` / `test_tree` / `test_inspection` 全绿；golden 不变。新
增一条：编译之后再往 manager 注册，已建好的索引不受影响。

### 步骤 3 — `Disclosure`：改名并瘦身

- `core/model/tree.py` → `core/model/disclosure.py`；`ContextTree` → `Disclosure`。
  剩下 `skeleton` / `open` / `card_of` / `card_for` / `schema_of` / `find` /
  `tool`。
- `node.py` 的 Protocol `Disclosure` → `View`；`_Alone` 改用节点名，`node.path`
  字段删除。
- `tests/test_tree.py`（803 行）拆成 `test_index.py` 和 `test_disclosure.py`。
- 加护栏测试：`Disclosure` 的公开方法不得是对 `Index` 的纯转发。

**验收：** 拆开后的两个测试文件全绿；golden 不变。

### 步骤 4 — `Surface`：拆掉 `Assembly`

- `server/projection/` → `server/surface/`；`gateway.py` → `tools.py`，
  `Gateway` → `Tools`。
- 三扇门各自收自己的条目、各自校验、各自安装；`Assembly` 删除。
- 新建 `Surface` 组合类：先全部构造再全部安装、产出 `reserved`、整体交给容器。
- `server/instructions.py` 并入 `surface/tools.py`。
- `goto` 与补全明确归 `surface/prompts.py`。
- 内核多一个只读查询，供三扇门在构造期校验。

**验收：** `test_projection` → `test_surface`；`test_layering` 全绿（它上次就抓
出过 `Assembly` 放错层）；golden 不变。

### 步骤 5 — 签名与命名

- `mcp_interface/tool.py`：`PUBLISHED` → `ToolPlane` + `TOOLS`，加
  `__init_subclass__` 拒绝。
- `ContextureServer.__init__(index, *, name, tools, prompts, resources)`；
  `manager.sealed()` 删除。
- demo 的 `PUBLISHED` 拆成两张清单；`_published()` 归一化与 `isinstance` 分拣
  一并删除。
- 加一条测试：继承 `ToolPlane` 会抛错。

**验收：** golden 不变；`contexture demo` 手跑一次；`test_scaffold` 全绿（脚手架
模板里的 `main` 要跟着改）。

### 步骤 6 — 文档跟上

- **README**：`ContextureApp` 那句（"你把根交给 `ContextureApp`"）今天就已经过
  时了，一并修；"Three planes, one verb" 那张表加上"能不能继承"这一列。
- `docs/atlas`、`docs/02-framework-layers.md`、ADR 索引。
- `HANDOFF.md`：A 节那个"一个初学者能装进脑子的心智模型"是这次重构服务的目标，
  写清楚这次给了什么答案。
- 本 ADR 状态改 accepted。

**验收：** `docs/atlas` 的 check 跑通。

### 步骤 7 — 回归收尾

- 全量测试；`contexture demo` 手跑；Claude Code 与 Codex 各连一次，实跑
  discover → open → invoke → 一次命令 → 一次资源读。
- HTTP 传输下再跑一遍（`test_http_server` 覆盖不到握手之外的东西）。

---

## 不做的事

- **不动 agent 看得见的任何一个字。** 四个入口的名字、描述、`readOnlyHint`、五
  种查找失败的句子、两种走错门的句子、路标、名册截断行——这些是三种语言必须逐
  字一致的部分，这次重构一个字都不改。golden 文件就是这条的执行者。
- **不动节点自渲染。** `compile` 那套多态是 ADR 014 的成果，不动。
- **不合并 `system_api.GATEWAY` 与 `mcp_interface` 的 `ToolPlane`。** ADR 009 规
  定这两个包是互不依赖的兄弟：一个说"这个平面上是哪四个"，一个说"它们各自怎么
  描述、怎么执行"。两份表示是有意的，名字都从 `constants.py` 这块共同地基来，
  所以漂移不了。合并会把两个兄弟包接成上下级。
- **不引入装饰器注册、middleware 链、tag filtering。** ADR 013 和 ADR 015 分别
  否过，理由不变。
- **不把 `Prompt` / `Resource` 改名。** 见 Decision 第 8 节。

---

## 代价

1. **对象从二变三。** 今天 `manager` + `tree`，之后 `manager` + `index` +
   `disclosure`。多的那个是实打实有活干的——它接手了两边各一半，两边都变薄——
   但"从二到三"本身需要这份 ADR 给出理由，否则下一个人会想合并回去。

2. **`ContextTree` 是公开名字，改名的文档面很宽。** README、`docs/02`、
   `docs/atlas`、多份 ADR 的正文都提到它。ADR 里的历史叙述**不改**（那是记录），
   靠这份 ADR 的"取代"关系交代。这是本次最大的一笔成本，而且是纯文档的。

3. **`Index` 会是新的胖子风险。** 地址表、绑定表、六个遍历、四个校验都在它身
   上。边界必须先钉死：**`Index` 只回答"关于地址和实体的事实"，任何带"给多少、
   给成什么样"的问题都不归它。** 这条要跟 `test_layering` 一起变成可执行的检查。

4. **`tools=` 参数在运行时不做选择。** 它只有一个值，传或不传结果一样。价值全
   在"签名即规则表"。接受这一点，才应该保留它。

5. **步骤 1 会改变一处外部可见行为**（宿主读资源现在校验参数、绑身份）。是修
   bug，但仍然是行为变化，要单独交代。
