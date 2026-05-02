# 死神商馆汉化工具

这是 `ReaperEmporiumLocalization` 项目里的 Python 辅助工具，用于处理 ParaTranz 翻译包下载、本地翻译安装、翻译包统计，以及从游戏转储数据构建可上传到 ParaTranz 的差异包。

## 命令速查

中文命令是主入口；旧的英文命令仍作为别名保留，方便已有脚本继续使用。

```powershell
python main.py 查看统计 data
python main.py 安装包 data
python main.py 下载包 --progress
python main.py 拉取安装 --progress
python main.py 构建差异
```

| 中文命令 | 英文别名 | 用途 |
| --- | --- | --- |
| `下载包` | `download` | 从 ParaTranz 下载并解压最新导出包。 |
| `安装包` | `install` | 将本地翻译 JSON 包安装到游戏目录。 |
| `拉取安装` | `pull` | 先下载 ParaTranz 导出包，再安装到游戏目录。 |
| `查看统计` | `stats` | 统计本地翻译包中的数据库和 DLL 词条数量。 |
| `构建差异` | `build-dump` | 根据 MainGame/DLCGame 转储数据构建差异输出。 |

常用参数仍保留英文名称：

- `--progress`：显示进度条。
- `--force`：忽略本地缓存，强制重新下载 ParaTranz 导出包。
- `--game-root`：指定游戏根目录。
- `--no-clear`：安装前不清理已有汉化 JSON。

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
  database/*.json
  dll_strings/dll_strings.json
```

`PARATRANZ_PROJECT_ID` 和 `PARATRANZ_TOKEN` 用于下载 ParaTranz 导出包。`PARATRANZ_TOKEN` 可以填写纯 token，也可以填写带 `Bearer ` 前缀的完整授权值。

## 安装本地翻译包

`安装包` 会扫描输入目录中的翻译包，例如 `data/本体解包`、`data/DLC解包`，然后：

- 合并 `database/*.json`，同类数据库文件按词条质量保留最优翻译。
- 合并 `dll_strings.json`，按原文去重并保留最优翻译。
- 写入游戏运行时需要的 `localization/database` 和 `localization/dll_strings`。

```powershell
python main.py 安装包 data --progress
```

## 拉取 ParaTranz 并安装

`拉取安装` 会先下载 ParaTranz 的最新导出包，解压后直接安装到游戏目录：

```powershell
python main.py 拉取安装 --force --progress
```

如果本地已有缓存，默认会复用 `data/cache/paratranz_export.zip`；加上 `--force` 可强制重新下载。

## 构建转储差异

`构建差异` 读取：

```text
data/0-DumpData/
  MainGame/
    database/*.json
    dll_strings.json
  DLCGame/
    database/*.json
    dll_strings.json
```

然后写入：

```text
build/dump/
  MainGame/
    database/*.json
    dll_strings.json
  DLCGame/
    database/*.json
    dll_strings.json
  diff/
    database/*.json.diff
    dll_strings.json.diff
```

处理规则：

- 每次执行 `构建差异` 前都会删除并重建整个 `build` 目录，避免旧产物混入新结果。
- `MainGame` 会完整复制。
- `DLCGame` 的数据库文件会先判断 JSON 数组数量是否对等；数据库词条差异以 `original` 为主，等长数组用索引辅助，原文轻微变化用 `thefuzz` 只在尚未匹配过的 MainGame 词条里搜索，避免重复复用同一条原文。
- 已匹配到 MainGame 的 DLC 数据库词条会改用 MainGame 的 `key`；完全新增的 DLC 词条会按当前 MainGame 文件的 key 顺序，从文件顺序最后一个数字 `key` 后继续编号，再由 `diff-match-patch` 判断规范化单条 JSON 是否变化。
- `diff` 会额外保存可读行级差异文件，数据库 diff 基于同一套差异匹配结果，只展示需要同步的词条；差异计算仍使用 `diff-match-patch`，中文会按 UTF-8 原文写出。
- `diff/database/foo.json.diff` 对应原始 `database/foo.json`，`diff/dll_strings.json.diff` 对应 DLL 字符串文件。
- DLC 的 `dll_strings.json` 会按 `{类名}.{方法名}_{索引}` key 和词条内容精确比较，不再兼容旧的 `_IL_` key 迁移规则。
- 空的 DLC 差异文件会跳过。

```powershell
python main.py 构建差异 --progress
```
