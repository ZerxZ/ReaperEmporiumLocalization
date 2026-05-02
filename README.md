# Reaper Emporium Localization

---

[![Author](https://img.shields.io/badge/Author-Circle%20Meimitei-brown)][author]
[![Game](https://img.shields.io/badge/Game-RJ01007980-red)][game-dlsite]
[![GitHub release](https://img.shields.io/github/v/release/ZerxZ/ReaperEmporiumLocalization)][releases-latest]
[![GitHub downloads](https://img.shields.io/github/downloads/ZerxZ/ReaperEmporiumLocalization/total)][releases-latest]
[![GitHub stars](https://img.shields.io/github/stars/ZerxZ/ReaperEmporiumLocalization)][repo]
[![GitHub issues](https://img.shields.io/github/issues-raw/ZerxZ/ReaperEmporiumLocalization)][issues]
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

Discord 交流服务器：

[![](https://dcbadge.limes.pink/api/server/jUG6dBdhBT)][discord]

---

<div align="center">

# 请在下载、安装或反馈问题前先阅读本说明文档

</div>

---

## 目录

- [简介](#简介)
  - [写在最前](#写在最前)
  - [关于本仓库](#关于本仓库)
  - [关于游戏本体与下载](#关于游戏本体与下载)
  - [关于交流与反馈](#关于交流与反馈)
- [核心特性](#核心特性)
- [当前状态说明](#当前状态说明)
- [玩家/翻译组使用说明](#玩家翻译组使用说明)
- [翻译文件格式](#翻译文件格式)
- [DLL 硬编码文本](#dll-硬编码文本)
- [数据库/TSV 文本](#数据库tsv-文本)
- [字体替换](#字体替换)
- [配置文件](#配置文件)
- [翻译工具与差异构建](#翻译工具与差异构建)
- [源代码结构](#源代码结构)
- [构建与安装](#构建与安装)
- [免责声明](#免责声明)
- [参考与致谢](#参考与致谢)
- [License](#license)

---

## 简介

《死神商館RExEX》用 BepInEx 动态本地化引擎。

本项目用于在不修改游戏原始资源的前提下，注入翻译文本、辅助导出待翻译文本，并为字体替换、数据库文本处理和 Paratranz 翻译流程提供基础框架。项目主要面向《死神商館RExEX(RJ01007980)》的中文本地化维护。

### 写在最前

- 游戏作者：サークル冥魅亭(Circle Meimitei)
- 作者主页：[Ci-en 创作者页面][author]
- 游戏本体：[DLsite 作品页 RJ01007980][game-dlsite]
- 交流服务器：[Discord][discord]

本仓库不包含游戏本体、商业资源或原始受版权保护文本。请在合法拥有游戏的前提下使用本项目。

### 关于本仓库

本仓库是《死神商館RExEX》的动态本地化插件源码与发布仓库，核心目标是让翻译文本以外置 JSON 的形式加载，而不是直接修改游戏本体资源。

仓库内容主要包括：

- BepInEx 主插件。
- BepInEx Preloader 补丁。
- 翻译 JSON 加载与原文匹配逻辑。
- TSV 数据库文本替换逻辑。
- 字体替换与 Dump 工具的预留框架。

如需下载已构建版本，请优先使用本仓库 [Releases][releases-latest] 页面。来自其他渠道的二次打包版本可能被修改，本仓库无法保证其安全性和可用性。

### 关于游戏本体与下载

请先前往 [DLsite 作品页][game-dlsite] 获取正版游戏本体。本仓库不会提供游戏本体下载，也不会发布原始游戏资源。

本项目面向的游戏：

- 标题：死神商館RExEX
- 作品 ID：RJ01007980
- 作者：サークル冥魅亭(Circle Meimitei)

### 关于交流与反馈

如果在使用插件或汉化文本时遇到问题，建议在本仓库 [Issues][issues] 反馈。反馈时请尽量附上：

- 使用的游戏版本与插件版本。
- 问题截图或复现步骤。
- `BepInEx/LogOutput.log` 中相关报错。
- 使用的翻译 JSON 文件来源或修改说明。

也可以加入 [Discord 交流服务器][discord] 讨论翻译、安装和排错问题。

## 核心特性

- **原文匹配**：运行时以日文原文作为匹配 Key，避免依赖脆弱的坐标、MD5 或资源哈希。只要原文不变，翻译就能继续命中。
- **Paratranz 风格 JSON**：翻译文件使用 `key / original / translation / stage / context` 字段，方便和 Paratranz 或类似翻译平台衔接。
- **DLL 硬编码文本替换**：通过 BepInEx Preloader 和 Mono.Cecil 在 `Assembly-CSharp.dll` 加载前扫描 `ldstr` 字符串，并按翻译 JSON 替换。
- **数据库/TSV 文本替换**：运行时拦截 `AssetBundle.LoadAsset` 读取到的 `TextAsset`，扫描 TSV 单元格并按原文替换译文。
- **无须重命名数据库翻译文件**：主插件会递归读取 `localization/database` 下所有 `.json` 文件，翻译人员可直接放入从翻译平台导出的 JSON。
- **自动创建本地化目录**：首次启动后会自动生成 `localization/dll_strings`、`localization/database`、`localization/fonts` 等目录。
- **开发者 Dump 辅助**：可开启 DLL 字符串导出；数据库 Dump 相关代码已保留，但当前默认 Hook 中未主动调用。
- **字体替换框架**：已包含 `FontManager` 和 `FontHook`，当前主插件默认未启用，需要开发者按需打开。
- **日志过滤插件**：附带 `IgnoreSpecificLog`，用于过滤一条已知 Unity 噪声日志。

## 当前状态说明

下面几项在源码中已经有配置或框架，但默认行为需要特别注意：

- `HotReloadKey` 配置项已存在，默认值为 `F5`，但当前主插件中尚未实现按键监听和热重载流程。
- `FontHook` 和 `FontManager` 已存在，但 `Plugin.Awake()` 中默认没有启用字体 Hook。
- `EnableDatabaseDump` 配置项和 `DatabaseDumper` 已存在，但 `DatabaseHook` 中默认没有主动调用数据库 Dump。
- 项目目标框架是 `netstandard2.1`，构建使用 `.NET SDK`，不是传统 `.NET Framework 4.7.2` 项目。

## 玩家/翻译组使用说明

安装插件并首次启动游戏后，游戏根目录会自动生成 `localization` 文件夹。它是整个汉化补丁的注入区。

```text
游戏根目录/
  localization/
    database/                    表格翻译区
      db_EventInfo.json
      db_SystemMessage.json
      ...
    dll_strings/                 代码硬编码文本翻译区
      dll_strings.json
    fonts/                       字体配置区，当前需要开发者启用 FontHook
    dump/                        文本提取区，仅开启 Dump 后生成
```

翻译人员通常只需要：

1. 从 Paratranz 或其他翻译平台下载 JSON 文件。
2. 将数据库翻译 JSON 放入 `游戏根目录/localization/database/`。
3. 将 DLL 硬编码翻译 JSON 放入 `游戏根目录/localization/dll_strings/dll_strings.json`。
4. 重启游戏查看效果。

当前版本暂未实现运行时 F5 热重载，因此修改 JSON 后需要重启游戏才能稳定验证。

## 翻译文件格式

翻译 JSON 是数组，每条记录格式如下：

```json
[
  {
    "key": "example_key",
    "original": "日文原文",
    "translation": "中文译文",
    "stage": 1,
    "context": ""
  }
]
```

字段说明：

- `key`：条目 ID。运行时实际匹配以 `original` 为准。数据库 Dump 使用当前 JSON 文件内的纯数字索引，如 `0`、`1`、`2`；DLL Dump 使用 `{类名}.{方法名}_{索引}`，如 `Game.Type.Method_0`。
- `original`：日文原文，必须和游戏文本一致。
- `translation`：译文，不能为空。
- `stage`：翻译状态。只有 `stage >= 1` 的条目会被加载。
- `context`：备注或上下文，可留空。

换行可写作 `\n`，加载时会自动转换为真实换行。

## DLL 硬编码文本

将翻译文件放在：

```text
游戏根目录/localization/dll_strings/dll_strings.json
```

Preloader 会在 `Assembly-CSharp.dll` 加载前扫描包含日文的 `ldstr` 字符串。如果能在 `dll_strings.json` 中找到相同 `original`，就会把字符串替换为 `translation`。

如需导出 DLL 中的日文文本，启动游戏后编辑：

```text
游戏根目录/BepInEx/config/ReaperEmporiumLocalization.cfg
```

将：

```ini
[Developer]
EnableDllDump = true
```

再次启动游戏后，导出文件会生成在：

```text
游戏根目录/localization/dump/dll_strings.json
```

DLL Dump 的 `key` 规则为 `{类名}.{方法名}_{索引}`，索引从同一类名和方法名下的第一个日文 `ldstr` 开始按 `0, 1, 2...` 递增。

## 数据库/TSV 文本

将数据库翻译 JSON 放在：

```text
游戏根目录/localization/database/
```

插件会递归读取该目录下所有 `.json` 文件，并把其中 `stage >= 1` 的译文加载到全局字典。游戏运行时加载 `TextAsset` 后，插件会扫描 TSV 单元格；如果某个单元格原文命中翻译字典，就返回替换后的 `TextAsset`。

排查无效翻译时，优先检查：

- JSON 是否为 UTF-8 编码。
- `stage` 是否大于或等于 `1`。
- `translation` 是否为空。
- `original` 是否和游戏里的原文完全一致。
- 原文中的换行是否正确写成 `\n`。

## 字体替换

项目中保留了数据驱动字体替换框架，配置目录为：

```text
游戏根目录/localization/fonts/
```

字体配置 JSON 使用：

```json
[
  {
    "target_font": "原字体名",
    "font_style": "Normal"
  }
]
```

当前 `FontHook` 在主插件中默认未启用。如需启用字体替换，需要在 `Plugin.Awake()` 中启用对应 Harmony Patch，并准备 Unity 可加载的字体 AssetBundle。

## 配置文件

首次运行后，会在 BepInEx 配置目录生成：

```text
游戏根目录/BepInEx/config/ReaperEmporiumLocalization.cfg
```

当前配置项：

```ini
[Developer]

# 是否开启 DLL 硬编码日文文本提取？
EnableDllDump = false

# 是否开启 AssetBundle 数据库日文提取？
# 当前为预留配置，默认 Hook 中未主动调用 DatabaseDumper。
EnableDatabaseDump = false

# 热重载快捷键名称。
# 当前为预留配置，主插件尚未实现按键监听。
HotReloadKey = F5
```

普通玩家请勿开启 Dump 功能。Dump 过程会产生额外磁盘读写，主要用于开发和文本提取。

## 翻译工具与差异构建

`ReaperEmporiumLocalization.Tools` 是翻译维护用的 Python 工具目录，主要用于下载/安装翻译包、统计本地 JSON、构建 MainGame/DLCGame 的差异转储，以及和 ParaTranz API 对接。详细命令说明请看 [`ReaperEmporiumLocalization.Tools/README.md`](ReaperEmporiumLocalization.Tools/README.md)。

常用入口：

```powershell
cd ReaperEmporiumLocalization.Tools
.\.venv\Scripts\python.exe main.py 构建差异
```

差异构建读取：

```text
ReaperEmporiumLocalization.Tools/data/0-DumpData/
  MainGame/
    database/{bundleName}/*.json
    dll_strings.json
  DLCGame/
    database/{bundleName}/*.json
    dll_strings.json
```

输出到：

```text
ReaperEmporiumLocalization.Tools/build/dump/
  MainGame/                 MainGame 完整规范化 JSON
  DLCGame/                  可上传/同步的 DLC 差异 JSON
  diff/                     人类可读的 .diff 差异文件
```

构建规则：

- 每次构建前会删除并重建整个 `build` 目录，避免旧产物混入。
- `MainGame` 输出完整 JSON，作为 DLC 差异判断的基准。
- 数据库 JSON 推荐路径为 `database/{bundleName}/{assetName}.json`；`key` 只是转储文件里的顺序编号，不作为主要身份，匹配优先级以 `original` 为主。
- 数据库差异会先判断 MainGame/DLCGame 数组数量是否对等；等长时用相同索引辅助判断原文是否被修改。
- 原文轻微变化时使用 `thefuzz` 做模糊匹配，但只会在尚未被精确匹配占用的 MainGame 词条里搜索，避免同一条 MainGame 原文被多个 DLC 词条复用。
- 已匹配到 MainGame 的 DLC 数据库词条会改用 MainGame 的 `key`；完全新增的 DLC 词条会按当前 MainGame 文件顺序，从文件顺序里最后一个数字 `key` 后继续编号。
- `diff/database/*.json.diff` 基于同一套匹配结果生成，只展示需要同步的词条，不再直接对完整数组做行级 diff，避免数组删减/重排造成大段误导性差异。
- `.diff` 文件头使用 `MainGame/...` 和 `DLCGame/...` 相对路径，不写入本机绝对路径。
- DLL 字符串使用 `{类名}.{方法名}_{索引}` 作为 `key`，差异判断按 `key + original` 精确匹配，不兼容旧 `_IL_` key 迁移规则。

## 源代码结构

为了避免 Preloader 层错误引用 Unity 运行时类型，本项目采用三层分离结构。

```text
ReaperEmporiumLocalization.Shared/
  Models/
    ParatranzData.cs              Paratranz 风格 JSON 数据模型
    StageEnum.cs                  翻译状态枚举
    FontConfig.cs                 字体配置模型
  LocalizationConfig.cs           BepInEx 配置读取，自动生成 localization 目录骨架
  TranslationManager.cs           JSON 加载与“原文 -> 译文”全局字典

ReaperEmporiumLocalization.Preload/
  Patcher.cs                      Mono.Cecil 前置补丁，替换 Assembly-CSharp.dll 硬编码文本

ReaperEmporiumLocalization/
  ReaperEmporiumLocalizationPlugin.cs
                                  主插件入口，初始化配置、加载数据库翻译、注册 Hook
  Core/
    AssetCache.cs                 TextAsset 原文/译文缓存
    DatabaseDumper.cs             开发者工具，提取 TSV 日文文本为 JSON
    FontManager.cs                字体 AssetBundle 与字体配置加载
    TranslationProvider.cs        按 bundle/asset 路径读取外部 TextAsset 的辅助类
    TsvTranslator.cs              TSV 单元格扫描与原文替换
  Patchers/
    DatabaseHook.cs               拦截 AssetBundle.LoadAsset 并注入翻译
    FontHook.cs                   拦截 UguiNovelText.Awake 以替换字体，默认未启用

IgnoreSpecificLog/
  IgnoreSpecificLogPlugin.cs      可选日志过滤插件
```

## 构建与安装

环境要求：

- Windows
- 已安装《死神商館RExEX》
- 已为游戏安装 BepInEx
- .NET SDK 6.0 或更高版本

构建时需要能访问游戏目录中的：

- `BepInEx/core`
- `死神商館RExEX_Data/Managed`

构建步骤：

1. 确认 `GameFolder.props` 中的 `GameFolder` 指向游戏根目录。

   当前默认值为：

   ```xml
   <GameFolder>..\..\..\</GameFolder>
   ```

   这适用于仓库位于 `游戏根目录/Dev/ReaperEmporiumLocalization` 的布局。如果你的目录不同，请改成实际游戏路径。

2. 使用 Visual Studio、Rider 或命令行构建解决方案：

   ```powershell
   dotnet build ReaperEmporiumLocalization.sln -c Release
   ```

3. 构建完成后，项目的 PostBuild 会自动复制输出：

   - 主插件复制到 `BepInEx/plugins/ReaperEmporiumLocalization`
   - Preloader 补丁复制到 `BepInEx/patchers/ReaperEmporiumLocalization`
   - `IgnoreSpecificLog` 复制到 `BepInEx/plugins/ReaperEmporiumLocalization`

4. 启动一次游戏，生成配置文件和 `localization` 目录骨架。

## 免责声明

1. 本仓库仅提供本地化插件源码、构建产物与相关说明，不提供游戏本体、商业资源或原始受版权保护文本。
2. 请先通过 [DLsite 作品页][game-dlsite] 合法获取游戏本体。未满 18 岁请勿访问、下载或游玩相关内容。
3. 本项目仅供学习、交流和本地化研究使用。使用者因二次打包、公开传播、商业使用或不当修改造成的后果，由使用者自行承担。
4. 本仓库无法保证第三方平台发布的整合包、修改版或转载版本安全可靠。建议仅使用本仓库 [Releases][releases-latest] 页面提供的版本。
5. 反馈问题前请确认游戏本体、BepInEx、插件和翻译文件来源明确，并尽量提供日志与复现步骤。

## 参考与致谢

本项目参考了 [MagicalAstrogy/ReaperEmporiumTrans](https://github.com/MagicalAstrogy/ReaperEmporiumTrans) 对《死神商館RExEX(RJ01007980)》翻译与文本处理方向的公开探索，特此感谢。

README 格式参考了 [PoP 中文本地化发布库][github-pop] 的发布页结构。

同时感谢 BepInEx、Harmony、Mono.Cecil、Newtonsoft.Json 等开源项目提供的基础能力。

## License

MIT

[author]: https://ci-en.dlsite.com/creator/65
[game-dlsite]: https://www.dlsite.com/maniax/work/=/product_id/RJ01007980.html
[discord]: https://discord.gg/jUG6dBdhBT
[repo]: https://github.com/ZerxZ/ReaperEmporiumLocalization
[releases-latest]: https://github.com/ZerxZ/ReaperEmporiumLocalization/releases/latest
[issues]: https://github.com/ZerxZ/ReaperEmporiumLocalization/issues
[github-pop]: https://github.com/CKRainbow/PoPLocalization
