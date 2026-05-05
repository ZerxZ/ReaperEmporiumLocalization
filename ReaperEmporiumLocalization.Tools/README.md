# 死神商馆汉化工具

这是 `ReaperEmporiumLocalization` 项目里的 Python 辅助工具，用于处理 ParaTranz 翻译包下载、本地翻译安装、翻译包统计，以及从游戏转储数据构建可上传到 ParaTranz 的差异包。

现在推荐直接使用 `reaper-tools ...`。根目录的 `python main.py ...` 仍然可用，但它已经只是转发到新的 Click CLI 入口。

## 命令速查

中文命令是主入口；旧的英文命令仍作为别名保留，方便已有脚本继续使用。

```powershell
reaper-tools 查看统计 data
reaper-tools 安装包 data
reaper-tools 下载包 --progress
reaper-tools 拉取安装 --progress
reaper-tools 构建差异
reaper-tools 迁移翻译 --progress
reaper-tools 迁移术语 --source-project-id 旧项目ID --progress
reaper-tools 上传翻译 --project-id 新项目ID --progress
reaper-tools 最终打包 --progress
```

| 中文命令 | 英文别名 | 用途 |
| --- | --- | --- |
| `下载包` | `download` | 从 ParaTranz 下载并解压最新导出包。 |
| `安装包` | `install` | 将本地翻译 JSON 包安装到游戏目录。 |
| `拉取安装` | `pull` | 先下载 ParaTranz 导出包，再安装到游戏目录。 |
| `查看统计` | `stats` | 统计本地翻译包中的数据库和 DLL 词条数量。 |
| `构建差异` | `build-dump` | 根据 MainGame/DLCGame 转储数据构建差异输出。 |
| `迁移翻译` | `migrate-translations` | 把旧 ParaTranz 译文迁移到新 `build/dump` 结构。 |
| `迁移术语` | `migrate-terms` | 把旧 ParaTranz 项目的术语迁移到新 ParaTranz 项目。 |
| `上传翻译` | `upload-translations` | 把人工检查后的 `build/migrated` 上传到目标 ParaTranz 项目，并把冲突候选逐次写入文件修订历史后再恢复最终译文。 |
| `最终打包` | `package-final` | 合并 `MainGame`/`DLCGame`，生成游戏运行时 `localization` 目录和发布 zip。 |

常用参数仍保留英文名称：

- `--progress`：显示进度条。
- `--force`：忽略本地缓存，强制重新下载 ParaTranz 导出包。
- `--game-root`：指定游戏根目录。
- `--no-clear`：安装前不清理已有汉化 JSON。
- `--dry-run`：只预览迁移统计，不写入迁移结果。
- `--execute`：对远端 ParaTranz 命令真正执行写入；未传时只预览计划。

## 配置

需要访问游戏目录或 ParaTranz 时，在 `.env` 中设置：

```dotenv
PATH_GAME_ROOT=..\..\..
PARATRANZ_PROJECT_ID=
PARATRANZ_TOKEN=
```

`PATH_GAME_ROOT` 指向游戏根目录；工具会把运行时翻译文件写入：

```text
<游戏根目录>/localization/
  database/{bundleName}/*.json
  dll_strings/dll_strings.json
```

`PARATRANZ_PROJECT_ID` 和 `PARATRANZ_TOKEN` 用于下载 ParaTranz 导出包。`PARATRANZ_TOKEN` 可以填写纯 token，也可以填写带 `Bearer ` 前缀的完整授权值。

## 安装本地翻译包

`安装包` 会扫描输入目录中的翻译包，例如 `data/本体解包`、`data/DLC解包`，然后：

- 合并 `database/**/*.json`，保留 `database` 下的 bundle 相对目录，同一路径内按词条质量保留最优翻译。
- 合并 `dll_strings.json`，按原文去重并保留最优翻译。
- 写入游戏运行时需要的 `localization/database` 和 `localization/dll_strings`。

```powershell
reaper-tools 安装包 data --progress
```

## 拉取 ParaTranz 并安装

`拉取安装` 会先下载 ParaTranz 的最新导出包，解压后直接安装到游戏目录：

```powershell
reaper-tools 拉取安装 --force --progress
```

如果本地已有缓存，默认会复用 `data/cache/paratranz_export.zip`；加上 `--force` 可强制重新下载。

## 构建转储差异

`构建差异` 读取：

```text
data/0-DumpData/
  MainGame/
    database/{bundleName}/*.json
    dll_strings.json
  DLCGame/
    database/{bundleName}/*.json
    dll_strings.json
```

然后写入：

```text
build/dump/
  MainGame/
    database/{bundleName}/*.json
    dll_strings.json
  DLCGame/
    database/{bundleName}/*.json
    dll_strings.json
  diff/
    database/{bundleName}/*.json.diff
    dll_strings.json.diff
```

处理规则：

- 每次执行 `构建差异` 前都会删除并重建整个 `build` 目录，避免旧产物混入新结果。
- `MainGame` 会完整复制。
- `DLCGame` 的数据库文件会先判断 JSON 数组数量是否对等；数据库词条差异以 `original` 为主，等长数组用索引辅助，原文轻微变化用 `thefuzz` 只在尚未匹配过的 MainGame 词条里搜索，避免重复复用同一条原文。
- 已匹配到 MainGame 的 DLC 数据库词条会改用 MainGame 的 `key`；完全新增的 DLC 词条会按当前 MainGame 文件的 key 顺序，从文件顺序最后一个数字 `key` 后继续编号，再由 `diff-match-patch` 判断规范化单条 JSON 是否变化。
- `diff` 会额外保存可读行级差异文件，数据库 diff 基于同一套差异匹配结果，只展示需要同步的词条；差异计算仍使用 `diff-match-patch`，中文会按 UTF-8 原文写出。
- `.diff` 文件头使用相对路径，例如 `--- MainGame/database/bundle/foo.json` 和 `+++ DLCGame/database/bundle/foo.json`，不会写入本机绝对路径。
- `diff/database/bundle/foo.json.diff` 对应原始 `database/bundle/foo.json`，`diff/dll_strings.json.diff` 对应 DLL 字符串文件。
- DLC 的 `dll_strings.json` 会按 `{类名}.{方法名}_{索引}` key 和词条内容精确比较，不再兼容旧的 `_IL_` key 迁移规则。
- 空的 DLC 差异文件会跳过。

```powershell
reaper-tools 构建差异 --progress
```

## 迁移旧 ParaTranz 译文

`迁移翻译` 会读取旧 ParaTranz 导出或旧项目译文，把译文套到当前 `build/dump` 的新提取结构中，并写入：

```text
build/migrated/
  MainGame/
  DLCGame/
  migration_report.json
```

默认读取 `data/paratranz` 和 `build/dump`：

```powershell
reaper-tools 迁移翻译 --progress
```

这个命令只生成本地文件，不会自动上传、创建、更新或删除 ParaTranz 远端文件。旧 `asset_XX_text_DLC` 目录会按当前新 dump 的 DLC 目录映射到 `DLCGame/database/asset_XX_text`；旧 `DLL/` 文件夹会对应当前的 `dll_strings.json`，其中纯数字旧 key 会按 `original` 精确迁移。重复旧文件会按词条合并择优，质量相同但译文不同的候选会写入 `migration_report.json` 的 `conflicts`。

## 迁移旧项目术语

`迁移术语` 用于把旧 ParaTranz 项目的术语迁移到新项目。这个命令只处理术语，不会同步文件、译文或删除目标项目内容。为了安全，默认只预览迁移计划，不直接写入远端：

```powershell
reaper-tools 迁移术语 --source-project-id 旧项目ID
```

确认页数和术语数量无误后，再显式执行：

```powershell
reaper-tools 迁移术语 --source-project-id 旧项目ID --target-project-id 新项目ID --execute --progress
```

如果不传 `--target-project-id`，默认使用 `.env` 里的 `PARATRANZ_PROJECT_ID` 作为新项目 ID。迁移时会按页读取旧项目术语，并调用 ParaTranz 的术语导入接口写入目标项目。

## 上传迁移结果

`上传翻译` 用于把已经人工检查过的 `build/migrated` 上传到新 ParaTranz 项目。这个命令不会去读取词条列表，也不会给冲突发评论；它会：

1. 先把 `build/migrated` 整体同步到目标项目。
2. 读取 `migration_report.json` 里的 `conflicts`，对每条冲突候选逐次生成临时文件并上传，让 ParaTranz 文件修订历史里留下记录。
3. 最后再把 `build/migrated` 的最终译文整包上传一次，以当前迁移结果为准。

默认只预览计划，不直接写入远端：

```powershell
reaper-tools 上传翻译 --project-id 新项目ID
```

确认计划无误后，再显式执行：

```powershell
reaper-tools 上传翻译 --project-id 新项目ID --execute --progress
```

如果不传 `--project-id`，默认使用 `.env` 里的 `PARATRANZ_PROJECT_ID`。如果不传 `--report-path`，默认读取 `build/migrated/migration_report.json`。冲突记录阶段会串行执行，继续沿用工具内保守的限速策略，避免对 ParaTranz 发送过于密集的写请求。

## 最终打包

`最终打包` 默认读取 `build/migrated`，把 `MainGame` 与 `DLCGame` 合并为游戏插件运行时需要的 `localization` 结构，并同时生成 zip：

```text
build/package/
  localization/
    database/{bundleName}/*.json
    dll_strings/dll_strings.json
  ReaperEmporiumLocalization-localization.zip
```

推荐流程是先执行 `构建差异`，需要套用旧 ParaTranz 译文时再执行 `迁移翻译`，最后执行：

```powershell
reaper-tools 最终打包 --progress
```

合并时，同一路径数据库 JSON 会按 `original` 去重：先放入 `MainGame` 词条，`DLCGame` 同原文词条覆盖本体译文，DLC 新原文追加。DLL 会合并成单个 `localization/dll_strings/dll_strings.json`，同原文优先使用 DLC，再按 `stage/translation` 质量择优。zip 内只包含 `localization/` 目录，可直接解压到游戏根目录。

如果想跳过迁移，直接使用当前差异构建产物，也可以指定：

```powershell
reaper-tools 最终打包 --source-root build/dump --progress
```
## 内部结构

这一节面向维护者，说明当前项目里哪些部分属于稳定 CLI 契约，哪些只是内部实现。

- 稳定入口
  - `reaper-tools`
  - `python main.py`
  - 两者都会转发到 `reaper_tools.cli.main:main`
- 稳定 CLI 契约
  - 中文命令名
  - 英文别名
  - 现有参数名与 `--help` 口径
- 非契约内容
  - 旧的 `src.*` Python import 路径
  - service / workflow / CLI 内部模块拆分方式

当前代码布局：

- `reaper_tools/cli/registry.py`
  - 命令元数据单一真源，统一维护中文命令名、英文别名、帮助文案和交互 prompt
- `reaper_tools/cli/commands/`
  - Click 命令定义，只负责参数绑定和调用 workflow
- `reaper_tools/app_context.py`
  - 统一运行时依赖容器，集中提供 `settings / paths / logger / progress`
- `reaper_tools/services/paratranz_api.py`
  - 低层 ParaTranz HTTP API client
- `reaper_tools/services/artifacts.py`
  - 导出包下载、缓存、解压
- `reaper_tools/services/sync.py`
  - 远端文件同步、批量字符串操作
- `reaper_tools/services/migration.py`
  - 项目迁移、本地译文迁移、术语迁移、迁移结果上传
- `reaper_tools/localization/paratranz.py`
  - 兼容层 facade，对外继续提供 `Paratranz`，内部委托给拆分后的 services
- `reaper_tools/localization/installer.py`
  - 本地翻译包安装与最终运行时 localization 打包
- `reaper_tools/localization/dump_builder.py`
  - MainGame / DLCGame dump 差异构建

测试原则：

- `tests/test_paratranz_api.py`
  - 继续覆盖 ParaTranz API、dry-run / execute 边界、迁移逻辑
- `tests/test_installer.py` / `tests/test_dump_builder.py`
  - 覆盖本地 workflow 行为
- `tests/test_cli.py`
  - 覆盖入口转发、命令注册表与 alias
- `tests/test_config_paths.py` / `tests/test_services.py`
  - 覆盖配置、路径安全和拆分后的 service 边界
