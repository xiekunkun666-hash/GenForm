# GenForm

[中文](README.md) | [English](README.en.md)

GenForm 由**泛化智能科技公司**设计。

GenForm 是面向人和 AI 协作的参数化三维建模软件。用户可以在图形界面中绘制草图、创建特征、修改尺寸；AI 或脚本可以通过 MCP 和本地接口执行建模命令、查询模型、保存文档和导出几何。

项目使用 **Python + PySide6 + QML + OpenGL** 构建桌面界面，使用 **OpenCascade（cadquery-ocp）** 进行几何计算。模型由有顺序的特征历史生成，修改上游参数后重新计算后续特征。

当前项目处于开发阶段，桌面窗口使用 Win32 原生窗口行为，建议在 **Windows** 上运行。模型长度单位为 **毫米（mm）**，世界坐标系 **Z 轴向上**。

## 目录

- [主要功能](#主要功能)
- [环境与安装](#环境与安装)
- [启动与配置](#启动与配置)
- [第一个零件](#第一个零件)
- [鼠标与快捷键](#鼠标与快捷键)
- [文档与导出](#文档与导出)
- [AI 与脚本接入](#ai-与脚本接入)
- [工程结构与开发](#工程结构与开发)
- [测试](#测试)
- [当前限制](#当前限制)
- [常见问题](#常见问题)

## 主要功能

| 类别 | 当前能力 |
| --- | --- |
| 二维草图 | 直线、中心线、矩形、多边形、圆、圆弧、椭圆、直槽口、圆弧槽口、样条、方程式曲线、点与文本 |
| 草图编辑 | 捕捉、框选、拖动、剪裁、延伸、圆角、等距、镜向、移动、线性与圆周阵列、尺寸编辑、草图修复 |
| 实体建模 | 拉伸、旋转、扫描、放样、边界凸台，以及对应的加料和切除操作 |
| 特征修饰 | 圆角、倒角、孔、高级孔、螺柱、真实螺纹、筋、拔模、抽壳、包裹与分割线 |
| 阵列与镜像 | 线性、圆周、曲线驱动、草图驱动、表格驱动、填充、变量阵列与镜像 |
| 曲线与参考几何 | 螺旋线、坐标曲线、投影曲线、组合曲线、基准面、基准轴、坐标系、参考点、质心与边界框 |
| 特征历史 | 参数修改、重命名、删除、抑制与恢复、回滚、撤销与重做 |
| 三维视图 | 面与边拾取、标准视角、平移旋转缩放、显示样式、剖切、透视、外观和材质 |
| 文件与自动化 | `.gform` 文档、STEP/STL 导出、视图截图、本地 TCP 接口和 MCP 工具调用 |

部分功能采用简化实现，例如草图几何关系目前不持续求解、边界凸台目前只处理一个方向的轮廓。使用前请阅读[当前限制](#当前限制)。

## 环境与安装

### 环境要求

- Windows 桌面环境；当前 GUI 包含 Win32 专用代码。
- Python：本地开发环境为 **3.13.0**，建议使用 Python 3.13。
- 支持 **OpenGL 3.3 Core Profile** 的显卡和驱动。应用使用 OpenGL 渲染 QML 场景和三维视图。
- Git：用于获取源码和同步修改。

项目目前没有安装包，也没有 `requirements.txt` 或 `pyproject.toml`。以下安装命令按源码直接使用的依赖编写；依赖表列出本地开发环境的实际版本，并不代表已验证所有版本组合。

| 依赖 | 用途 | 本地开发环境版本 |
| --- | --- | --- |
| PySide6 | Qt 窗口、QML 与界面控制 | 6.9.1 |
| numpy | 相机、拾取和几何数据计算 | 2.5.3 |
| PyOpenGL | OpenGL 渲染 | 3.1.10 |
| cadquery-ocp | OpenCascade Python 绑定，提供 `OCP` 模块 | 8.0.1.0.0 |

### 获取源码并安装依赖

在 PowerShell 中执行：

```powershell
git clone git@github.com:xiekunkun666-hash/GenForm.git
cd GenForm
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install PySide6 numpy PyOpenGL cadquery-ocp
```

SSH 克隆需要提前配置 GitHub SSH 认证，也可以使用 HTTPS：

```powershell
git clone https://github.com/xiekunkun666-hash/GenForm.git
```

下文统一直接调用虚拟环境中的 Python，无需激活虚拟环境。请在工程根目录运行命令。

## 启动与配置

### 打开桌面窗口

```powershell
.\.venv\Scripts\python.exe main.py
```

启动时默认同时开启本地 AI 接口 `127.0.0.1:9631`。GUI 的几何内核运行在独立进程中，重算结果再交给界面显示。

可以在启动时打开已有文档：

```powershell
.\.venv\Scripts\python.exe main.py "C:\models\part.gform"
```

### 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `GENFORM_PORT` | `9631` | 桌面本地接口端口；设为 `0` 时关闭接口。连接窗口的 MCP 服务也读取此变量 |
| `GENFORM_SETTINGS` | `%APPDATA%\GenForm\settings.json` | 自定义设置文件位置，适合隔离测试配置 |

例如，更换本地接口端口：

```powershell
$env:GENFORM_PORT = "9632"
.\.venv\Scripts\python.exe main.py
```

关闭接口时使用 `$env:GENFORM_PORT = "0"`。这些 PowerShell 赋值只影响当前终端及其启动的进程；恢复默认端口可执行 `Remove-Item Env:GENFORM_PORT`。连接窗口的 MCP 进程需要使用与窗口一致的端口。

快捷键和右键手势轮可以在设置窗口中修改。用户设置独立于零件文档保存。

## 第一个零件

下面以“矩形底座 + 圆形通孔”为例：

1. 启动 GenForm，在左侧设计树或三维视图中选择**上视基准面（XY）**。
2. 点击“草图绘制”，或直接选择矩形工具进入草图编辑。
3. 绘制矩形，使用“智能尺寸”设置所需宽高，例如 `60 × 40 mm`。
4. 点击“完成草图”，再选择“拉伸凸台/基体”，输入 `12 mm` 并确认。也可以在草图编辑中直接选择拉伸，软件会先保存草图再打开参数面板。
5. 再次在 XY 基准面创建草图，绘制半径 `8 mm` 的圆，完成草图。
6. 选择“拉伸切除”，沿进入实体的方向切除 `12 mm`。XY 默认法向为 +Z，底面草图沿 +Z 切除即可贯穿这个底座。
7. 选择需要修饰的边，添加圆角或倒角。
8. 保存为 `.gform`，需要交给其他 CAD 或切片软件时导出 STEP 或 STL。

双击已有草图特征可以重新编辑草图。修改特征参数后，模型按历史顺序重新计算；出错的特征会在设计树中标红并显示原因，可以修改参数或撤销。

草图中只有**封闭轮廓**参与拉伸。内层封闭轮廓作为孔处理；未闭合的线和构造线可以保留作参考，但不生成拉伸实体。“放弃草图”不会把本次编辑写入文档历史。

## 鼠标与快捷键

### 鼠标操作

| 操作 | 功能 |
| --- | --- |
| 左键 | 选择对象；草图编辑时绘制或选择图形 |
| Ctrl + 左键 | 加选对象 |
| 草图空白处拖动 | 框选图形 |
| 中键拖动 | 旋转视图 |
| Ctrl / Shift + 中键拖动 | 平移视图 |
| 滚轮 | 朝光标位置缩放 |
| 右键拖动 | 打开八方向手势轮，朝对应方向执行动作 |

建模与草图编辑各有一套手势轮，支持在设置中自定义。手势回到中心后松开可以取消。

### 常用默认快捷键

| 快捷键 | 功能 | 快捷键 | 功能 |
| --- | --- | --- | --- |
| Ctrl + N | 新建零件 | Ctrl + O | 打开文档 |
| Ctrl + S | 保存文档 | Ctrl + , | 打开设置 |
| Ctrl + Z | 撤销 | Ctrl + Y | 重做 |
| Delete | 删除选中对象 | S | 进入草图 |
| L / R / C / A | 直线 / 矩形 / 圆 / 圆弧 | D | 智能尺寸 |
| T / O / M | 剪裁 / 等距 / 移动 | E / F | 拉伸 / 圆角 |
| Z | 适应全图 | Ctrl + 7 | 等轴测视图 |
| Ctrl + 1 / 2 | 前视 / 后视 | Ctrl + 3 / 4 | 左视 / 右视 |
| Ctrl + 5 / 6 | 上视 / 下视 | Ctrl + 8 | 正视于 |

草图编辑中的撤销操作处理草图图形快照；文档级撤销处理已提交的特征历史。

## 文档与导出

| 格式 | 用途 | 保留内容 |
| --- | --- | --- |
| `.gform` | GenForm 可编辑文档 | JSON 格式的特征历史、参数和零件属性；打开后重新计算几何 |
| `.step` / `.stp` | 与其他 CAD 交换模型 | 精确几何 |
| `.stl` | 交给切片等网格工作流 | 三角网格 |
| `.gasm` | GenForm 装配体（“新建 → 装配体”，或仿真页“装配检查”里保存） | JSON：零件文件的相对路径、各自的位置和转角、装配顺序；零件几何仍在各自的文件里 |
| `.gdrw` | GenForm 工程图（“新建 → 工程图”） | JSON：零件文件的相对路径、图纸、比例、视图位置、手标的尺寸、标题栏；可导出 PDF / DXF / SVG / PNG |
| `.png` | 记录或检查视图 | 通过截图命令保存三维视图画面 |

需要继续修改尺寸时应保存 `.gform`。STEP/STL 导出不会保留 GenForm 的参数化特征历史。

可把多个 `.step` / `.stp` / `.stl` / `.gform` 文件一起拖入窗口，也可在“打开”对话框中按 Ctrl / Shift 多选：多个文件自动组成装配体；已有装配体时批量追加。每个文件是独立零部件，可选中、移动、旋转、隐藏、孤立和删除，并保留源文件的坐标，不自动排开或融合。当前零件有实体时会保留为装配体的第一个零件。装配体的“插入零件”也支持多选。加载失败的文件会显示错误，其余文件继续显示。

单个 STEP 仍导入成可继续建模的新零件；单个 STL 以装配体网格组件打开。STL 支持 ASCII 和二进制格式，按毫米读取，用于显示和摆放，不支持精确实体测量、干涉检查、布尔建模或 STEP 导出。包含 STL 的装配体可保存成 `.gasm`，它引用源文件路径；移动工程时需一起带上源文件。

## AI 与脚本接入

GUI 和 AI 通过同一套命令修改文档。修改命令等待几何重算后再返回，结果包含特征状态和模型尺寸；查询命令可以读取特征、边、面和用户当前选择。

### MCP：连接正在运行的窗口

先启动 GenForm，再由支持 MCP stdio 的客户端启动：

```powershell
.\.venv\Scripts\python.exe -m genform.api.mcp_server
```

仓库中的 `.mcp.json` 已包含配置，但其中的 Python 路径和工程目录是开发机绝对路径。其他机器需要按实际位置修改，例如：

```json
{
  "mcpServers": {
    "genform": {
      "command": "C:\\projects\\GenForm\\.venv\\Scripts\\python.exe",
      "args": ["-B", "-m", "genform.api.mcp_server"],
      "cwd": "C:\\projects\\GenForm"
    }
  }
}
```

不想管工作目录的话，用根目录下的启动器 `genform_mcp.py`，配置里只写两个绝对路径即可（它和 `-m genform.api.mcp_server` 等价，同样接受 `--headless`）：

```json
{
  "mcpServers": {
    "genform": {
      "command": "C:\\projects\\GenForm\\.venv\\Scripts\\python.exe",
      "args": ["C:\\projects\\GenForm\\genform_mcp.py"]
    }
  }
}
```

Claude Code 里一条命令就能接上：

```powershell
claude mcp add genform -- "C:\projects\GenForm\.venv\Scripts\python.exe" "C:\projects\GenForm\genform_mcp.py"
```

软件里点标题栏右边的齿轮 → “AI 接口”，可以直接复制按本机路径填好的这几段。

这种模式操作当前窗口中的文档，用户可以看到模型变化。建议先让 AI 用 `get_model` 检查当前内容，再执行修改。

### MCP：无界面建模

```powershell
.\.venv\Scripts\python.exe -m genform.api.mcp_server --headless
```

无界面模式在 MCP 进程内持有独立文档，不需要启动桌面窗口，适合生成模型和导出文件。`screenshot`、`set_view` 等依赖窗口的命令不可用。无界面标志属于 MCP 模块，不是 `main.py` 的启动参数。

MCP 适配使用标准输入输出传输 JSON-RPC，声明的协议版本为 `2024-11-05`，提供初始化、工具枚举和工具调用。日志写到标准错误；直接在终端启动后等待输入是正常状态。

### 取消、超时与断连

- MCP 在执行工具时仍接收输入。客户端停止请求时，应发送 `notifications/cancelled`，参数为 `{"requestId": 原请求ID}`；关闭 MCP 标准输入也会取消未完成的请求。仅在 WebUI 上改变按钮状态，而不发送取消或关闭连接，GenForm 无法得知用户按了停止。
- 窗口模式会断开该请求的等待连接，并通知 GUI 停止**属于这个请求**的内核任务；必要时终止并重新创建独立内核进程，不关闭主窗口，不清空文档，不取消其他连接的任务。
- TCP 请求可附带唯一字符串 `request_id` 和 `timeout_s`（大于 0、不超过 300 秒）。另开连接发送 `{"cmd":"cancel_request","request_id":"原请求ID"}` 可取消；请求连接断开也会触发取消。未提供时，接口生成请求 ID 并使用 300 秒总时限。
- MCP 窗口模式向 TCP 传递 285 秒总时限，MCP 请求自身上限为 290 秒；内核另有单步 120 秒与整项任务 300 秒看门狗。进度消息只重置单步计时，不延长总时限。
- 取消或超时**不是事务回滚**。特征可能已经写入文档；使用 `get_model` 查看 `busy`、`model_stale`、`progress`、`query_progress`，再决定修改参数或撤销。断连后不会自动重发修改命令，避免重复添加特征。
- 无界面模式仍使用进程内同步内核：取消会结束协议层的等待并丢弃迟到回复，但不能保证中断正在执行的 OpenCascade 原生调用。需要可强制停止且保留窗口文档的自动化时，使用窗口模式；本修复也不替代宿主 WebUI 自己的停止请求转发。

### 本地 TCP 接口

桌面接口监听 `127.0.0.1:9631`，使用 UTF-8 编码，**每行一个 JSON 请求、每行一个 JSON 应答**。这是原始 TCP 协议，不能作为 HTTP 地址在浏览器中访问。

```json
{"cmd": "tools"}
{"cmd": "get_model", "args": {}}
{"cmd": "sketch", "args": {"plane": "XY", "shapes": [{"type": "rect", "cx": 0, "cy": 0, "w": 60, "h": 40}]}}
{"cmd": "extrude", "args": {"distance": 12}}
```

以下 Python 示例连接已启动的窗口，创建一个底座、给竖边倒圆角，并保存文档和 STEP。示例会向当前文档添加特征，建议在空白文档中执行。

```python
import json
import os
import socket
from pathlib import Path


def call(command, **args):
    port = int(os.environ.get("GENFORM_PORT", "9631"))
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.settimeout(320)
        with connection.makefile("rwb") as stream:
            request = {"cmd": command, "args": args}
            stream.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            stream.flush()
            result = json.loads(stream.readline().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "GenForm 命令失败"))
    return result


sketch = call("sketch", plane="XY", shapes=[
    {"type": "rect", "cx": 0, "cy": 0, "w": 60, "h": 40}
])
call("extrude", sketch=sketch["id"], distance=12)
call("fillet", edges="|Z", radius=3)
print(json.dumps(call("get_model"), ensure_ascii=False, indent=2))

output = Path("build/example").resolve()
output.mkdir(parents=True, exist_ok=True)
call("save_document", path=str(output / "base.gform"))
call("export", path=str(output / "base.step"))
```

### 设计检查与视图操作

- 设计检查由用户手动触发：完成建模后点击“评估 → 设计检查”。打开装配、插入或移动零件不会自动检查；状态栏“日志”只展开已有结果。
- 日志右上角“清除日志”会清空报错、警告、计数及场景红叉/标红；正在返回的旧结果不会重新出现。清除不修改几何，也不表示问题已修好，再次点击“设计检查”才重新检查。
- 模型修改后，已有检查结果标为过期，并移除旧的场景错误标记；不会后台重新计算。
- 零件和装配体进入孤立模式后，视图顶部均显示“退出孤立”按钮，退出后恢复原来的隐藏状态。
- 左键从左往右框选完整落在框内的对象，从右往左框选与矩形相交的对象；装配支持同时选择多个组件，按 Ctrl 累加。隐藏组件不参与框选，属性编辑仍针对主选组件。
- 鼠标旋转、平移或缩放时保持所选显示样式，带边线上色不会在移动时暂时变为纯上色。

### 常用命令

| 用途 | 命令 |
| --- | --- |
| 获取工具与参数格式 | TCP 请求 `tools`；MCP 请求 `tools/list` |
| 创建特征 | `sketch`、`extrude`、`fillet`、`chamfer` 及特征表登记的其他命令 |
| 编辑历史 | `edit_feature`、`delete_feature`、`rename_feature`、`suppress_feature`、`rollback`、`undo`、`redo` |
| 查询模型 | `get_model`、`list_edges`、`list_faces`、`get_selection` |
| 文档与导出 | `new_document`、`open_document`、`save_document`、`export` |
| 外观与视图 | `set_material`、`set_appearance`、`set_view`、`screenshot` |

参数以工具清单中的 JSON Schema 为准。长度使用毫米，草图角度使用度；草图坐标位于所选平面的二维坐标系中。XY 法向为 +Z，XZ 法向为 -Y，YZ 法向为 +X。

边可以使用 `"all"`、`"|Z"`、`">Z"`、`"<Z"` 等选择器，也可以先调用 `list_edges` 获取中点，再传入 `[{"point": [x, y, z]}]`。修改特征示例：

```json
{"cmd": "edit_feature", "args": {"id": "f2", "params": {"distance": 20}}}
```

返回 `ok: false` 时应检查 `error` 和模型状态。几何失败的特征通常仍留在历史中，需要修改参数或 `undo`；不能把失败应答理解为这一步从未写入文档。`new_document` 会清空文档，调用前应保存需要保留的内容。

## 工程结构与开发

```text
GenForm/
├── main.py                 # 轻量入口，处理多进程启动
├── ARCHITECTURE.md         # 分层、线程、特征引用与实现细节
├── .mcp.json               # MCP 客户端配置，路径需按本机调整
├── genform/
│   ├── bootstrap.py        # 装配窗口、会话、内核和本地接口
│   ├── app.py              # 界面控制器
│   ├── actions.py          # 动作、默认快捷键和手势轮
│   ├── forms.py            # 参数面板数据
│   ├── commands.py         # 命令注册与参数格式
│   ├── features.py         # 特征定义与参考几何计算
│   ├── document.py         # 特征历史、撤销重做与文档读写
│   ├── session.py          # 命令执行、重算与结果通知
│   ├── sketcher.py         # 草图编辑器
│   ├── sketchgeom.py       # 二维图形与算法
│   ├── api/                # TCP 服务、MCP 适配和 JSON 编码
│   ├── kernel/             # OpenCascade 几何计算与工作进程
│   └── view/               # 相机、拾取与 OpenGL 绘制
├── qml/                    # 窗口、工具栏、设计树、参数面板与主题
└── tests/                  # 单元测试与桌面冒烟测试
```

主要数据流：

```text
界面操作 / MCP / TCP
        ↓
commands → session → document
               ↓
        几何内核重算
               ↓
        模型状态 / 三维显示 / 命令应答
```

文档保存特征数据，实体由特征重新计算生成。GUI 使用独立内核进程；测试和无界面 MCP 使用同步内核。三维视图按需重绘，避免空闲时持续刷新。

新增特征通常需要在 `genform/features.py` 的 `SPECS` 中登记参数，在 `genform/kernel/features.py` 中实现并注册计算函数，再补充对应几何测试。更多实现规则见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 测试

### 单元测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -t .
```

测试覆盖几何内核、特征、命令会话、草图编辑与部分视图数学。单元测试不启动桌面主窗口，但内核测试需要安装 OpenCascade 依赖。

### 桌面冒烟测试

```powershell
.\.venv\Scripts\python.exe tests\smoke_gui.py
.\.venv\Scripts\python.exe tests\smoke_ui.py
.\.venv\Scripts\python.exe tests\smoke_features.py
.\.venv\Scripts\python.exe tests\smoke_sketch.py
.\.venv\Scripts\python.exe tests\smoke_sketch2.py
.\.venv\Scripts\python.exe tests\smoke_quit.py
```

- `smoke_gui.py`：通过本地接口验证建模、错误处理、撤销、尺寸修改、截图、导出和保存。
- `smoke_ui.py`：模拟鼠标操作并抓取实际窗口画面。
- `smoke_features.py`：特征页和参考几何的交互检查。
- `smoke_sketch.py` / `smoke_sketch2.py`：草图工具与编辑操作的交互检查。
- `smoke_quit.py`：检查建模后是否正常退出。

这些脚本会启动真实窗口；涉及鼠标和屏幕抓图的脚本需要可交互桌面，运行时避免遮挡测试窗口或同时操作鼠标。默认输出位于 `build/smoke/`，包含截图、日志和导出文件；`smoke_gui.py` 也接受自定义输出目录。`build/` 已在 Git 中忽略。

## 当前限制

- **草图没有持续约束求解。** “添加几何关系”只按关系调整一次图形；智能尺寸修改图形参数，不保留驱动尺寸标注。等距、镜向、阵列和转换引用生成的是当时的拷贝。
- **当前按单实体建模。** 尚无多实体管理；装配只有仿真页里的“装配检查”（摆放零件、查干涉、查装配顺序），没有配合关系。`op: common` 是与当前实体取交集。
- **面上草图。** 选中零件上的一个平面点“草图绘制”即可；正对坐标轴的面用对应基准面加偏移，斜面会自动先建一个基准面特征。
- **仿真是估算。** 静力分析把零件切成小方块求解（应力约 ±20%，尖角处偏低）；风阻只按迎风面积和阻力系数算，不是流场计算；装配顺序只试 ±X ±Y ±Z 六个方向的直线装入。尚无模态、热、疲劳分析。
- **拓扑引用是简化实现。** 边、面坐标引用依靠附近几何匹配；上游尺寸大幅变化后可能需要重新选择引用。
- **部分特征有范围限制。** 边界凸台目前使用放样算法；包裹仅支持圆柱面；筋只支持平行于草图的延伸；拔模为中性面拔模。
- **阵列与镜像有对象限制。** 复制指定特征时需要该特征生成的工具体，如拉伸、旋转、扫描、放样、孔和螺柱；圆角、抽壳等修改特征不能按同样方式复制。
- **三维草图目前通过坐标输入。** `sketch3d` 和曲面曲线并非在三维视图里直接用鼠标绘制。
- **螺纹生成真实几何。** 计算可能较慢，尚无装饰螺纹线。
- STL 作为网格参考加载，不转换为可编辑的精确实体；尚未实现视角方块和安装包。

## 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| `ModuleNotFoundError` | 确认使用安装了依赖的同一个 Python；`OCP` 模块由 `cadquery-ocp` 提供 |
| 窗口启动失败或三维视图异常 | 查看终端中的 Qt/OpenGL 日志，检查显卡驱动和 OpenGL 3.3 支持；远程桌面或虚拟显卡环境需单独验证 |
| MCP 连不上 GenForm | 先启动窗口，确认窗口与 MCP 的 `GENFORM_PORT` 一致；独立建模可使用 `--headless` |
| 本地 AI 接口未开启 | 检查端口是否被占用、`GENFORM_PORT` 是否为 `0`；窗口可启动但接口绑定失败时不会提供 TCP 服务 |
| 拉伸没有生成实体 | 检查轮廓是否闭合、是否全部为构造线，以及特征错误信息 |
| 圆角或倒角失败 | 尝试较小尺寸并检查选中的边；用 `edit_feature` 修正参数或撤销失败特征 |
| 无界面模式不能截图 | 截图和视角命令依赖 GUI，应使用连接窗口的 MCP 模式 |
| 导出文件无法继续参数化编辑 | 同时保存 `.gform` 文档；STEP/STL 用于交换几何，不保留本项目的特征历史 |