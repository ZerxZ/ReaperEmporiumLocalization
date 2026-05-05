# Reaper Emporium Localization

[![Author](https://img.shields.io/badge/Author-Circle%20Meimitei-brown)][author]
[![Game](https://img.shields.io/badge/Game-RJ01007980-red)][game-dlsite]
[![GitHub release](https://img.shields.io/github/v/release/ZerxZ/ReaperEmporiumLocalization)][releases-latest]
[![GitHub downloads](https://img.shields.io/github/downloads/ZerxZ/ReaperEmporiumLocalization/total)][releases-latest]
[![GitHub stars](https://img.shields.io/github/stars/ZerxZ/ReaperEmporiumLocalization)][repo]
[![GitHub issues](https://img.shields.io/github/issues-raw/ZerxZ/ReaperEmporiumLocalization)][issues]
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

作者官方 Discord（日语交流）：

[![](https://dcbadge.limes.pink/api/server/jUG6dBdhBT)][discord]

---

## 请先阅读

本仓库提供《死神商館RExEX (RJ01007980)》的 BepInEx 动态本地化插件源码、构建配置和翻译维护工具。

- 游戏标题：死神商館RExEX
- 作品 ID：RJ01007980
- 游戏作者：サークル冥魅亭 (Circle Meimitei)
- 作者主页：[Ci-en 创作者页面][author]
- 游戏本体：[DLsite 作品页][game-dlsite]
- 官方 Discord：[Discord][discord]（作者官方服务器，交流以日语为主）
- 开发说明：本项目代码全程由 ChatGPT（OpenAI）和 Gemini（Google）生成与维护，0 手工编写

- 不包含游戏本体、商业素材或原始受版权保护文本
- 请在合法拥有游戏的前提下使用
- 建议优先使用本仓库 [Releases][releases-latest] 发布的构建产物

---

## 目录

- [简介](#简介)
- [核心特性](#核心特性)
- [当前运行状态](#当前运行状态)
- [安装与目录结构](#安装与目录结构)
- [翻译文件格式](#翻译文件格式)
- [DLL 硬编码文本](#dll-硬编码文本)
- [数据库 TSV 文本](#数据库-tsv-文本)
- [场景文本](#场景文本)
- [字体替换](#字体替换)
- [配置文件](#配置文件)
- [翻译工具与差异构建](#翻译工具与差异构建)
- [源代码结构](#源代码结构)
- [构建](#构建)
- [发布与反馈](#发布与反馈)
- [排错建议](#排错建议)
- [免责声明](#免责声明)
- [参考与致谢](#参考与致谢)
- [License](#license)

---

## 简介

本项目的目标是在**不修改游戏原始资源**的前提下，把翻译文本、场景文本和字体替换能力以外置文件形式注入运行中的游戏。

项目当前主要包含三部分：

1. `ReaperEmporiumLocalization.Preload`
   - 在 `Assembly-CSharp.dll` 加载前处理 DLL 硬编码字符串
2. `ReaperEmporiumLocalization`
   - 主插件，负责数据库翻译、场景文本、字体替换、热重载
3. `ReaperEmporiumLocalization.Tools`
   - 翻译维护工具，用于统计、同步和差异构建

---

## 核心特性

- 基于原文匹配的运行时翻译加载
- DLL `ldstr` 硬编码字符串预加载替换
- `TextAsset` / TSV 数据库文本运行时替换
- `UguiNovelText.Awake` 场景文本按需回写
- 数据驱动字体替换
- `F5` 热重载翻译与字体规则
- 本地化目录骨架自动创建
- 旧版字体规则自动迁移到新格式并生成 `.bak` 备份
- 可选字体调试日志与临时字号偏移

---

## 当前运行状态

和仓库早期版本相比，当前行为已经更新为：

- `HotReloadKey` 已实现，默认可用，按 `F5` 会重载：
  - `localization/database`
  - `localization/dll_strings/dll_strings.json`
  - 字体规则
  - 场景文本翻译缓存
- 当以下任一功能启用时，会自动挂载 `UguiNovelText.Awake` 补丁与场景工作流：
  - `EnableFontReplacement`
  - `EnableSceneDump`
  - `EnableSceneTranslation`
  - `EnableFontUsageDump`
- 当前推荐并已验证的字体替换工作流为 `bundle_asset`
- 已修复字体热重载时“已替换文本无法按原字体重新命中规则”的问题

---

## 安装与目录结构

首次启动后，游戏根目录下会自动生成 `localization` 目录骨架：

```text
游戏根目录/
  localization/
    database/
    dll_strings/
      dll_strings.json
    fonts/
    scene/
    dump/
      database/
      scene/
```

常见使用流程：

1. 将数据库翻译 JSON 放入 `localization/database/`
2. 将 DLL 硬编码翻译放入 `localization/dll_strings/dll_strings.json`
3. 如需字体替换，将字体资源与规则文件放入 `localization/fonts/`
4. 启动游戏验证效果
5. 运行中修改后可按 `F5` 热重载

---

## 翻译文件格式

数据库翻译与 DLL 字符串翻译都使用 Paratranz 风格 JSON：

```json
[
  {
    "key": "example_key",
    "original": "日本語原文",
    "translation": "中文译文",
    "stage": 1,
    "context": ""
  }
]
```

字段说明：

- `key`：条目 ID。运行时主要仍以 `original` 匹配
- `original`：必须和游戏中的原文一致
- `translation`：译文
- `stage`：仅 `stage >= 1` 会被加载
- `context`：可选备注

换行请写成 `\n`。

---

## DLL 硬编码文本

放置路径：

```text
游戏根目录/localization/dll_strings/dll_strings.json
```

Preloader 会在 `Assembly-CSharp.dll` 加载前扫描包含日文的 `ldstr` 字符串；当 `dll_strings.json` 中存在相同 `original` 时，会把它替换为对应 `translation`。

如果要导出 DLL 文本：

```ini
[Developer]
EnableDllDump = true
```

导出结果：

```text
游戏根目录/localization/dump/dll_strings.json
```

---

## 数据库 TSV 文本

放置路径：

```text
游戏根目录/localization/database/
```

主插件会递归读取该目录下所有 `.json` 文件，并把其中 `stage >= 1` 的译文加载到全局字典。游戏运行时读取 `TextAsset` 后，插件会扫描 TSV 单元格；如果原文命中翻译字典，就返回替换后的 `TextAsset`。

如果翻译未生效，优先检查：

- 文件是否为 UTF-8
- `stage` 是否大于等于 `1`
- `translation` 是否为空
- `original` 是否与游戏原文完全一致

---

## 场景文本

场景文本相关能力分为两类：

1. 场景转储
   - 开启 `EnableSceneDump`
   - 导出当前场景中的 `Text` / `UguiNovelText`
2. 场景回写
   - 开启 `EnableSceneTranslation`
   - 读取 `localization/scene/{SceneName}.json`
   - 在 `UguiNovelText.Awake` 时按需回写

当前场景翻译缓存支持热重载；按 `F5` 后，下次命中 `Awake` 会重新读取对应场景文件。

维护翻译时，运行时导出的 scene JSON 可以放入工具侧标准包结构 `data/0-DumpData/MainGame/scene/` 或 `data/0-DumpData/DLCGame/scene/`。`reaper-tools 构建差异` 会把 MainGame scene 完整复制，并按 `original` 只输出 DLCGame scene 的新增或变化词条；最终打包会合并到运行时目录 `localization/scene/`。

---

## 字体替换

字体规则目录：

```text
游戏根目录/localization/fonts/
```

当前 README 仅说明 `bundle_asset` 工作流。

### 规则格式

当前显式规则格式如下：

```json
[
  {
    "target_fonts": ["FOT-NewRodinPro-B", "TT_Yuruka-UB"],
    "font_style": "Normal",
    "source_mode": "bundle_asset",
    "source_file": "ChironGoRoundTC-500M.bundle",
    "source_font": "ChironGoRoundTC-500M"
  }
]
```

字段说明：

- `target_fonts`
  - 需要被替换的原字体名列表
  - 这是当前主格式
- `font_style`
  - 目标 `UnityEngine.FontStyle`
- `source_mode`
  - `bundle_asset`
- `source_file`
  - 相对 `localization/fonts/` 的文件名
  - `bundle_asset` 使用
- `source_font`
  - bundle 内具体 `Font` 资源名
  - `bundle_asset` 使用

### `bundle_asset` 示例

```json
[
  {
    "target_fonts": ["FOT-NewRodinPro-B"],
    "font_style": "Normal",
    "source_mode": "bundle_asset",
    "source_file": "ChironGoRoundTC-500M.bundle",
    "source_font": "ChironGoRoundTC-500M"
  }
]
```

### 运行时行为

- `bundle_asset`
  - 从 AssetBundle 中读取 `Font`

### 重要说明

- `target_font` 仍支持作为**旧格式兼容输入**
- 新规则与自动生成规则会优先写出 `target_fonts`
- 旧版字体规则在加载时会：
  - 自动迁移为显式格式
  - 原文件同目录生成 `*.json.bak`

### 自动生成规则

当：

```ini
[Feature]
EnableAutoGenerateFontJson = true
```

插件会为 `localization/fonts/` 中缺少同名规则的字体来源自动生成默认模板。

### 热重载

修改字体规则或字体文件后：

1. 运行游戏
2. 按 `F5`
3. 插件会重载字体规则并刷新当前场景文本

### 字体调试

为方便排查“字体改了但画面看起来没变”，新增了两个调试选项：

```ini
[Developer]
EnableFontDebugLogging = true
FontDebugSizeOffset = 4
```

- `EnableFontDebugLogging`
  - 打印命中文本的字体、字号、Best Fit、Rect 等信息
- `FontDebugSizeOffset`
  - 仅调试用
  - 在应用替换时临时给当前 `Text.fontSize` 增加偏移
  - `0` 表示关闭

日志中可以重点关注：

- `bundle_asset 加载成功`
- `FontDebug`

---

## 配置文件

配置文件路径：

```text
游戏根目录/BepInEx/config/ReaperEmporiumLocalization.cfg
```

主要配置项：

```ini
[Developer]
EnableDllDump = false
EnableDatabaseDump = false
EnableSceneDump = false
EnableFontUsageDump = false
EnableFontDebugLogging = false
FontDebugSizeOffset = 0

[Feature]
EnableFontReplacement = true
EnableAutoGenerateFontJson = false
EnableSceneTranslation = false

[HotReload]
HotReloadKey = F5
```

说明：

- `EnableFontReplacement`
  - 启用字体规则加载、字体替换和场景刷新
- `EnableSceneDump`
  - 导出当前场景文本
- `EnableSceneTranslation`
  - 启用场景回写
- `EnableFontUsageDump`
  - 记录本体字体使用情况
- `HotReloadKey`
  - 运行时热重载按键

数据库转储可以额外使用外部过滤配置，只按清理后的 `assetName` 判断，不读取也不匹配 `bundleName`。配置文件不存在时会自动生成默认模板，默认会排除图片资源索引、声音资源使用表、语音角色表等不需要翻译维护的数据库：

```text
游戏根目录/localization/config/database_dump_filter.json
```

```json
{
  "excluded_asset_names": [
    "db_Direct",
    "db_VoiceChara",
    "db_ResourceSoundBgmUse",
    "db_ResourceSoundSeUse"
  ],
  "excluded_asset_name_regex": [
    "^db_Image"
  ]
}
```

`excluded_asset_names` 是大小写敏感的精确匹配，`excluded_asset_name_regex` 是作用于 `assetName` 的 .NET 正则。无效正则只会记录 warning 并忽略该条规则。

---

## 翻译工具与差异构建

`ReaperEmporiumLocalization.Tools` 是翻译维护用工具目录，详细说明见：

- [`ReaperEmporiumLocalization.Tools/README.md`](ReaperEmporiumLocalization.Tools/README.md)

常见入口：

```powershell
cd ReaperEmporiumLocalization.Tools
.\.venv\Scripts\python.exe main.py 构建差异
```

更新游戏文本并同步 ParaTranz 原文修正时，常用流程是：

```powershell
cd ReaperEmporiumLocalization.Tools
reaper-tools 下载对比 --scope dlc --local-root data\0-DumpData --progress
reaper-tools 上传对比变化 --scope dlc --execute --progress
```

`上传对比变化` 会读取 `下载对比` 产出的 `delta/` 下各类 JSON，并逐条调用 ParaTranz string API：原文修正和整体变化会保留原有译文并把 `stage` 写回 `0`，新增词条会按远端 DLC key、远端 MainGame key、从 `0` 开始的顺序分配 key 后创建 string；远端残留仍只导出供人工检查，不会自动删除。

如果需要把已经进入 ParaTranz 的过滤数据库文件一起清理，可以先预览再执行：

```powershell
cd ReaperEmporiumLocalization.Tools
reaper-tools 删除过滤文件 --progress
reaper-tools 删除过滤文件 --execute --progress
```

`删除过滤文件` 使用同一份 `database_dump_filter.json` 的 `assetName` 规则，仅匹配 `database/**/*.json`，默认只 dry-run，确认列表无误后才加 `--execute` 删除 ParaTranz 远端文件。

---

## 源代码结构

```text
ReaperEmporiumLocalization.Shared/
  Models/
    FontConfig.cs
    ParatranzData.cs
    StageEnum.cs
  LocalizationConfig.cs
  TranslationManager.cs

ReaperEmporiumLocalization.Preload/
  Patcher.cs

ReaperEmporiumLocalization/
  ReaperEmporiumLocalizationPlugin.cs
  Core/
    AssetCache.cs
    DatabaseDumper.cs
    FontManager.cs
    SceneTextDumper.cs
    SceneTextSupport.cs
    SceneTextTranslator.cs
    TranslationProvider.cs
    TsvTranslator.cs
  Patchers/
    DatabaseHook.cs
    FontHook.cs

IgnoreSpecificLog/
  IgnoreSpecificLogPlugin.cs
```

---

## 构建

环境要求：

- Windows
- 已安装游戏本体
- 已为游戏安装 BepInEx；当前参考版本为 `v5.4.23.5`，可在 [BepInEx Releases][bepinex-releases] 查看
- .NET SDK 6.0 或更高版本

项目默认假设仓库位于：

```text
游戏根目录/Dev/ReaperEmporiumLocalization
```

`GameFolder.props` 默认内容：

```xml
<Project>
    <PropertyGroup>
        <GameFolder>..\..\..\</GameFolder>
    </PropertyGroup>
</Project>
```

如目录结构不同，请先修改 `GameFolder.props`。

构建命令：

```powershell
dotnet build ReaperEmporiumLocalization.sln -c Release
```

构建完成后，PostBuild 会自动复制输出到：

- `BepInEx/plugins/ReaperEmporiumLocalization`
- `BepInEx/patchers/ReaperEmporiumLocalization`

---

## 发布与反馈

GitHub Actions 使用 `.github/workflows/runner.yml` 生成最终发布包。该 workflow 会在手动触发、每周定时和 `v*` tag push 时运行：

1. 校验 `ReaperEmporiumLocalization.Tools`
2. 用 `GameFolder.github.props` 覆盖 CI 环境里的 `GameFolder.props`
3. 执行 `dotnet build ReaperEmporiumLocalization.sln -c Release`
4. 下载 ParaTranz 导出并执行 `reaper-tools 最终打包`
5. 以 `ReaperEmporium.GameRoot` 为基础组合整合 zip
6. 上传 artifact，并在 release job 中发布

`GameFolder.props` 只用于本地开发；CI 专用配置是 `GameFolder.github.props`，其 `GameFolder` 指向仓库内的 `ReaperEmporium.GameRoot`。这个目录是发布用游戏根目录壳，需要包含 BepInEx、Doorstop 文件和编译引用所需的 `死神商館RExEX_Data/Managed`。其中 `死神商館RExEX_Data` 主要用于构建 DLL 引用，不保证是最新游戏版本数据，也不会进入最终 zip。

当前发布壳里的 BepInEx 参考版本为 `v5.4.23.5`；如需更新或核对版本，请查看 [BepInEx Releases][bepinex-releases]。

发布包里的 `BepInEx/plugins` 和 `BepInEx/patchers` 只保留运行所需的 `.dll` 文件；Release 构建产生的 `.pdb`、`.deps.json` 等调试或构建辅助文件会在组合发布包时移除。

最终发布的 zip 设计为直接解压到游戏根目录，根目录应包含：

- `BepInEx/`
- `localization/database/`
- `localization/dll_strings/`
- `localization/fonts/`
- `localization/scene/`
- `.doorstop_version`
- `doorstop_config.ini`
- `winhttp.dll`
- `changelog.txt`
- `DISCLAIMER.txt`

最终发布 zip 会排除：

- `死神商館RExEX_Data/`
- `BepInEx/cache/`
- `BepInEx/LogOutput.log`
- 其他 `*.log`

ParaTranz 下载需要在仓库 secrets 中配置：

- `PARATRANZ_TOKEN`
- `PARATRANZ_PROJECT_ID`

如果遇到中文补丁问题，请优先使用 GitHub issue，并按 bug report 模板附上游戏版本、补丁版本、截图和 `BepInEx/LogOutput.log`。作者官方 Discord 主要适合日语交流，中文问题请优先在本仓库提交。

---

## 排错建议

### 修改翻译后无效

- 确认 `stage >= 1`
- 确认 `original` 与游戏原文完全一致
- 按 `F5` 热重载，或重启游戏

### 修改字体规则后画面没变

- 看日志是否真的命中了新的 `source_mode`
- 打开 `EnableFontDebugLogging`
- 必要时把 `FontDebugSizeOffset` 设为 `4` 或 `6` 做可视验证

### 构建时报复制失败

通常是游戏进程或 BepInEx 正占用输出 DLL。关闭游戏后重新构建即可。

---

## 免责声明

1. 本仓库仅提供本地化插件源码、构建产物与相关说明，不提供游戏本体、商业资源或原始受版权保护文本。
2. 请先通过 [DLsite 作品页][game-dlsite] 合法获取游戏本体。
3. 请支持正版游戏；如果你喜欢本作品，请通过 [DLsite 作品页][game-dlsite] 等官方渠道购买正版。
4. 本项目仅供学习、交流和本地化研究使用。
5. 任何学习、研究或测试用途的文件都不应长期保留；如果你通过非官方渠道获得了包含游戏本体或商业资源的内容，请在 24 小时内删除，并购买正版。
6. 游戏作品相关权利、官方说明和最终解释权归游戏作者 サークル冥魅亭 (Circle Meimitei) 所有，请以 [Ci-en 创作者页面][author] 为准。
7. 第三方整合包、转载包、修改版带来的风险由使用者自行承担。

发布包根目录会附带 `DISCLAIMER.txt`，内容与本节一致，方便使用者在离线分发包中直接查看。

---

## 参考与致谢

- [MagicalAstrogy/ReaperEmporiumTrans](https://github.com/MagicalAstrogy/ReaperEmporiumTrans)
- [PoP 中文本地化发布库][github-pop]
- BepInEx
- Harmony
- Mono.Cecil
- Newtonsoft.Json

---

## License

MIT

[author]: https://ci-en.dlsite.com/creator/65
[game-dlsite]: https://www.dlsite.com/maniax/work/=/product_id/RJ01007980.html
[discord]: https://discord.gg/jUG6dBdhBT
[repo]: https://github.com/ZerxZ/ReaperEmporiumLocalization
[releases-latest]: https://github.com/ZerxZ/ReaperEmporiumLocalization/releases/latest
[issues]: https://github.com/ZerxZ/ReaperEmporiumLocalization/issues
[github-pop]: https://github.com/CKRainbow/PoPLocalization
[bepinex-releases]: https://github.com/BepInEx/BepInEx/releases
