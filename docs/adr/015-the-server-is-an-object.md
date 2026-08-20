# ADR 015 — server 是一个对象

**Status:** proposed
**Date:** 2026-08-21

**不取代任何既有 ADR。** ADR 014 把导航收进内核之后,`core` 已经是一个干净的对象
模型;这份提案只动 `server`,把它从一组互相传参的自由函数,变成一组各管一件事的
对象。ADR 013 的"构造函数即声明"和 ADR 009 的"协议平面不是对象模型"都是这份提案
的前提,不是它要改的东西。

## Context

`server` 现在是 1078 行(`app.py` 511 + `binding.py` 567),对外只有两个类和三个
自由函数。四个症状,都能在代码里指出来,不是从原则推出来的。

### 1. 三个时刻被压进一个构造函数

`ContextureApp.__post_init__` 做四件事:建 `Dispatch`、normalise `publish`、建
registry、seal 出 `ContextTree`,然后把 `self.roots` 就地改写成 `tree.roots`。

后果是**构造即封树**。`demo/server.py` 在模块级写 `app = ContextureApp(roots=…)`,
所以 `import contexture.demo.server` 这一句就把整片 KubernetesPlatform 森林建了
出来。ADR 013 说过:

> **import 不构造任何东西**——类是一个零参工厂,`ControllerManager` 调它那一次,
> 是全包唯一一个节点诞生的时刻。

那句话现在对 `core` 成立,对 `server` 不成立。不是 `ControllerManager` 违反了它,
是 `ContextureApp` 让一次 import 顺手触发了那一次调用。

### 2. `binding.py` 里传的是参数,不是对象

`project(server, *, tree, dispatch, publish)` 是一个只有副作用的函数:它往传进来的
`server` 上写。同一批上下文在下游被手工透传一遍又一遍——

```
project(server, tree, dispatch, publish)
  └─ _project_published(server, tree=, dispatch=, publish=, api=)
       ├─ _resolve(tree, ref, kind)
       ├─ _require_content_tool(tree, dispatch, entry)
       ├─ _reader(tree, ref)
       └─ _command(api, ref)
```

五个签名,四份同样的上下文。一个对象被拆开在函数之间传递,是它本该是对象的信号。

### 3. 三个原语的规则完全不同,却挤在一个 if/else 里

| 平面 | 业务能写吗 | 启动时要检查什么 | 额外挂什么 |
| --- | --- | --- | --- |
| tool | 不能 | 无 | — |
| prompt | 能 | 重名、`opens` 可解析 | `goto` + `completion/complete` |
| resource | 能 | 重名、URI 重复、`opens` 可解析、必须 read-only、必须无参 | — |

这三套规则今天在 `_project_published` 一个 for 循环的两个分支里,加一个同时管两种
kind 的 `_reject_ambiguous_names`。而 `core/mcp_interface/` 早就是一个原语一个模块。
**投影这一侧没有跟上声明那一侧的形状。**

### 4. `channels` 没有类型,于是生命周期只能靠运行时 refusal 表达

`channels: Any`,框架"从不检视"。这是刻意的,代价却落在别处:`provision` 必须是
"返回 async context manager 的工厂,而不是 context manager 本身",这条约束没有类型
能表达,只能写成 `ControllerManager.__post_init__` 里的 `hasattr(self.provision,
"__aenter__")` 加一段解释,以及 `provisioned()` 里的第二段。合计约 45 行,全部在说
一件本可以由一个基类说清楚的事。

## 参考:brpc 与 fastmcp,各自能借什么

### brpc

brpc 的 main 之所以一眼能读,是因为三个时刻各有各的语法形态:

```cpp
EchoServiceImpl svc;                       // 业务实体
brpc::Server server;                       // 空容器
server.AddService(&svc, ...);              // 注册,additive
brpc::ServerOptions options;               // 怎么跑
server.Start(port, &options);              // 启动
```

对得上的映射:

| brpc | Contexture 今天 | 本提案 |
| --- | --- | --- |
| `Service` | Role / Skill / Tool | 不动 |
| `Server` | `ContextureApp` + `project()` | `ContextureServer` |
| `Server::AddService` | 构造参数 `roots=` | `add_role/add_skill/add_tool` |
| `ServerOptions` | `ContextureOptions` | 不动,搬进 `options.py` |
| `Start` / `RunUntilAskedToQuit` | `run()` | `start()` / `start_async()` |
| `Channel`(出站) | `channels: Any` | `Channels` 抽象基类 |

### fastmcp

**能借的三条:**

1. **一个原语一个 manager。** fastmcp 有 `ToolManager` / `ResourceManager` /
   `PromptManager`,各管一个平面的注册、发现与执行。方向和这里相反——它管"注册进来
   的组件",这里要管"投影出去的表面",因为 Contexture 的业务能力**根本不上表面**。
   但"一个平面一个对象"这条形状是对的。
2. **Provider 抽象。** fastmcp 新近把"组件从哪来"抽成了 `LocalProvider` /
   `AggregateProvider` / `OpenAPIProvider`。Contexture 的对应物是"根从哪来":今天
   `cli/project.py` 的 `pkg.mod:RoleClass` 解析只有 CLI 能用。
3. **`run` 与 `run_async` 分层。** Contexture 今天只有同步 `run()`,内部直接
   `server.run(transport, …)`。想把一台 Contexture 嵌进别人已经在跑的 asyncio 进程
   里,没有入口。这是现存缺口。

**不能借的三条,借了会拆掉已有结论:**

1. **装饰器注册(`@mcp.tool`)。** ADR 013 拒绝过:类体扫描和从类名/docstring 推导
   在 Go 和 TypeScript 里都做不到,而这个对象模型要在三种语言里成立。
2. **middleware 链。** fastmcp 用它拦截每一条 MCP 消息。这里的表面固定是四个入口,
   消息种类少到不需要一条通用链;真要横切(审计、限流),位置是 `SystemAPI` 的
   `execute` seam——那里已经有 `bound(principal)` 这一个横切了。
3. **tag filtering / 动态组件。** 协议禁止 server 按连接变表面,`stateless_http`
   已经被钉成 `True`,理由写在 `_reject_owned_overrides` 里。

## Decision

### 1. `ContextureServer`:三个时刻,三种语法

`ContextureApp` 改名并拆开。构造只给身份,注册是方法,启动是另一个方法。**构造函数
不再建树。**

```python
class ContextureServer:
    def __init__(self, *, name="contexture", version=PACKAGE_VERSION,
                 instructions=None, channels=None): ...

    # 注册,additive,委托给 ControllerManager —— brpc 的 AddService
    def add_role(self, controller) -> Role: ...
    def add_skill(self, controller) -> Skill: ...
    def add_tool(self, controller) -> Tool: ...
    def add_source(self, source: Source) -> None: ...   # 见第 5 节
    def publish(self, *entries: Prompt | Resource) -> None: ...

    # 装配 —— 同步,不进 lifespan,测试直接调它
    def build(self, *, auth: Auth | None = None) -> MCPServer: ...

    # 启动
    def start(self, options: ContextureOptions | None = None, *, transport=None) -> None: ...
    async def start_async(self, options=None, *, transport=None) -> None: ...
```

`roots=` / `publish=` 作为构造糖保留(一行建一台 server 是常用写法),但它们只是
把参数记下来,**seal 推迟到 `build()`**。这一条同时修掉 Context 第 1 节。

`build()` 的全身:

```python
def build(self, *, auth=None) -> MCPServer:
    assembly = self._seal()                    # tree + dispatch + api,一次密封
    surface = self._sdk_server(auth)           # MCPServer(name, version, instructions, …)
    for projector in self._projectors:
        projector.check(assembly)              # 声明错误,在 way up,一次报全
    for projector in self._projectors:
        projector.project(surface, assembly)
    return surface
```

六行,每行一个名词。这就是"main 流程清晰"真正的来处——不是 main 短,是 main 里每
一行都能对应到一个有名字的东西。

`build()` 保持**同步**、且生命周期包住的是 *serving* 而不是 *construction*,这条
`app.py` 已经论证过,不改。

### 2. `Assembly`:密封的产物

`(tree, dispatch, api)` 是一次装配的产物,今天散在 `ContextureApp` 的两个字段和
`binding.system_api()` 这个自由函数里。打包成一个只读对象,它就是每个 projector 的
唯一入参——Context 第 2 节的四份透传上下文收敛成一个。

```python
@dataclass(slots=True, frozen=True)
class Assembly:
    tree: ContextTree
    dispatch: Dispatch
    api: SystemAPI

    @classmethod
    def seal(cls, registry: ControllerManager, *, reserved: frozenset[str]) -> Assembly: ...
```

`execute` seam(那段 `with bound(principal_of(get_access_token()))`)在 `seal` 里
绑定,和今天 `binding.system_api()` 做的事一样,只是有了归属。

命名备选:`Serving`。取 `Assembly` 是因为它确实是三样东西装配的产物,而不是一个
动作。

### 3. 三个 Projector,一个平面一个

```python
class Projector(ABC):
    """把一个 MCP 原语上该有的东西,挂到 SDK server 上。"""

    def check(self, assembly: Assembly) -> None:
        """启动时的声明检查。默认什么都不查。"""

    @abstractmethod
    def project(self, surface: MCPServer, assembly: Assembly) -> None: ...
```

| 实现 | 持有 | `check` | `project` |
| --- | --- | --- | --- |
| `GatewayProjector` | 无状态 | — | 四个入口,从 `GATEWAY` 一条元组里注册 |
| `PromptProjector` | `prompts: tuple[Prompt, ...]` | 重名、`opens` 可解析 | 每条命令 + `goto` + `completion` |
| `ResourceProjector` | `resources: tuple[Resource, ...]` | 重名、URI 重复、read-only、无参 | 每份文档 |

`check` 和 `project` 分成两趟不是形式主义:今天一条声明错误会在投影进行到一半时抛
出,SDK server 上已经挂了半份东西;分开之后 `project` 是纯写入,而且一次能把所有
声明错误报全,而不是让人改一条重启一次。**这批 refusal 文案是这个包最值钱的东西
之一,拆的时候一个字都不改。**

`_open_by_name` / `_command` 归 `PromptProjector`,`_reader` / `_require_content_tool`
归 `ResourceProjector`,`_translated` 是两者共用的协议边界翻译,放
`projection/__init__.py`。`_without_titles` 只被 `Dispatch` 用,跟着它走。

### 4. `publish` 不再是混合列表

今天 `publish: Sequence[Prompt | Resource]`,`_project_published` 靠 `isinstance`
分流,`_reject_ambiguous_names` 靠 `(entry.kind, name)` 当 key 同时管两种。
分成两个具名字段,分流发生在入口一次,下游不再问"这是哪种"。

这是 ADR 014 第 3 节那条论据的复用:

> 三个具名字段翻译得到 Go 和 TypeScript;一张开放的 kind map 不能。

### 5. 根从哪来,是一个可换的东西

`cli/project.py` 里的 `pkg.mod:RoleClass` 解析(`importlib.import_module` +
`getattr` + `_require_declared_here`)是这个包里唯一的反射,而且形态是对的。问题只
是它今天锁在 CLI 里,`ContextureServer` 用不上。

```python
class Source(Protocol):
    """一批根从哪来。"""
    def roots(self) -> Iterable[Any]: ...
```

一个 `TargetSource(("pkg.mod:RoleClass", …))` 就把 CLI 那段解析变成谁都能用的东西,
`contexture serve` 从此和一个业务自己的 `main()` 走同一条路。

**明确不做:** 装饰器注册表、元类自动发现、扫描包目录找 Role 子类。理由是 ADR 013,
不是口味——那三种在 Go 里都写不出来。反射的正确剂量是"把一个字符串变成一个类",
到此为止;把类变成节点的仍然只有 `ControllerManager._build` 那一行零参调用。

### 6. `Channels`:给业务方一个虚基类

```python
# core/model/channels.py
class Channels(ABC):
    """一个能力在这个进程之外够得到的东西。

    框架不检视它持有什么。它只认识两件事:什么时候打开,什么时候关。
    """

    async def open(self) -> None:
        """在第一个请求之前。默认什么都不做。"""

    async def close(self) -> None:
        """在最后一个请求之后。默认什么都不做。"""
```

`ControllerManager.provisioned()` 认这个类型:是 `Channels` 就 await 它的
`open`/`close`,是别的就照旧原样交出去。

**`provision=` 随之退役。** 它的全部价值是生命周期,而生命周期现在有类型了;
"必须传工厂而不是 context manager"这条约束连同它那两段共约 45 行的运行时 refusal
一起消失——一个 `Channels` 实例天生可以被 open 两次,不存在"被 enter 一次就用光"
的问题。要组合多个句柄的,在自己的 `open()` 里组合,那本来就是应用自己的事。

### 7. 目录

```
contexture/server/
├── __init__.py      facade,懒解析(不动)
├── server.py        ContextureServer —— 容器、注册、生命周期
├── options.py       ContextureOptions、Transport、DEFAULT_*、LOOPBACK、configure_logging
├── assembly.py      Assembly —— 密封的产物
├── dispatch.py      Dispatch(+ _without_titles)
├── projection/
│   ├── __init__.py  Projector、translated()
│   ├── gateway.py   GatewayProjector
│   ├── prompts.py   PromptProjector
│   └── resources.py ResourceProjector
├── identity.py      不动
├── instructions.py  不动
├── messages.py      不动
└── launch.py        不动
```

`projection/` 和 `core/mcp_interface/` 一一对应:后者声明"这个原语上放什么",前者
做"把它放上去"。这个对称是这个子目录的全部理由——ADR 010 说目录就是架构,一个目录
要么表达一条分界,要么不该存在。

## main 前后

**现在**(`contexture/demo/server.py`):

```python
app = ContextureApp(              # ← 模块级。import 到这里,整片森林已经建好并封死
    roots=KubernetesPlatform,
    publish=PUBLISHED,
    name="contexture-demo",
)

def main() -> None:
    app.run(transport="stdio")
```

**之后**:

```python
def main() -> None:
    server = ContextureServer(name="contexture-demo")
    server.add_role(KubernetesPlatform)
    server.publish(*PUBLISHED)
    server.start(transport="stdio")
```

四行,四个时刻:身份、注册、发布、启动。import 这个模块不再构造任何东西。

需要嵌进别人的进程时:

```python
await server.start_async(ContextureOptions(transport="streamable-http", port=8080))
```

## 迁移

**第 0 步是前置条件,不是可选项。** 当前 `run_tests.py` 有 60 个 error,全部是
ADR 013 的迁移没做完:`test_binding.py` 34、`test_inspection.py` 22、
`channels_fixture.py` 让 `test_channels` 整个 ImportError,`test_http_server.py` 2。
`test_binding.py` 正是 server 层的主测试(1028 行),它跑不起来的时候,下面每一步都
没有安全网。HANDOFF 0d 只点到 `channels_fixture.py` 一个文件——实际范围是三个文件。

| # | 步骤 | 破坏性 | 说明 |
| --- | --- | --- | --- |
| 0 | 修完 ADR 013 的迁移遗漏 | 无 | 前置。60 个 error 归零 |
| 1 | `options.py` 独立 | 无 | 纯搬运,零行为变化 |
| 2 | `dispatch.py` 独立 | 无 | 纯搬运,零行为变化 |
| 3 | `Assembly` | 无 | `system_api()` 变成 `Assembly.seal()` |
| 4 | 三个 Projector | 无(对外) | 最大的一步,`project()` 拆成三个类 |
| 5 | `ContextureServer` | **是** | 三阶段 API;改 demo / cli / tests 调用点 |
| 6 | `Channels` ABC,`provision` 退役 | **是** | 删掉约 45 行运行时 refusal |
| 7 | `start_async()` | 无 | 补嵌入能力 |

1–3 机械且零风险,可以先落地把 `binding.py` 和 `app.py` 压下去一半。4 是结构收益的
主体。5 是 main 清晰度的来处。6、7 互相独立,也独立于前面。

5 和 6 都是破坏性的,合并进一个 v0.7.0,HANDOFF 按 0c 的样子给一张迁移表。这将是
连续第三个破坏性版本(013、014、这个),值得在 HANDOFF 里说清楚这三个是同一件事的
三步:模型、导航、服务。

## 不做什么

- **不给 `ContextureServer` 加 middleware 链。** 横切点是 `SystemAPI.execute`。
- **不做装饰器 / 元类注册。** ADR 013。
- **不让 `ContextureServer` 继承 `MCPServer`。** `app.py` 已经论证过:运行时拥有角色
  与披露,SDK 拥有线;两个对象组合,是 SDK 升级伸不进对象模型的原因。
- **不动 `messages` / `instructions` / `identity` / `launch`。** 它们各自的分界是对
  的,这份提案没有一条论据碰得到它们。
