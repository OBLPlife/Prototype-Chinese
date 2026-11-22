# Prototype 简体中文汉化源码

对应《虐杀原形》（2009）简体中文补丁 0.2.13 差分版。菜单、任务提示、剧情字幕和战斗对白的译文保存在 `source/PrototypeZh/catalog/`。玩家安装用的文件是单独发行的 `Prototype_ZH_CN_Setup.exe`。

| 路径 | 内容 |
| --- | --- |
| `source/PrototypeZh/catalog/` | 按界面、剧情及战斗对白分组的译文，以及制作人员表、字体来源与显示选项 |
| `source/PrototypeZh/runtime/`、`source/PrototypeZh/src/` | C++ 汉化运行库和 ActionScript 字幕、界面源码 |
| `source/PrototypeZh/packaging/` | C# 安装器、Python 差分打包、安装、还原及验证工具 |
| `source/PrototypeZh/tools/` | 原文读取、译文合并、资源构建和字体工具 |
| `source/PrototypeZh/licenses/` | 本项目所用 Noto 字体的许可文本 |

## 核对译文

分类译文按原版行序保存。重复文本复用、按键组合和控制符由 `tools/catalog.py` 处理。要查看某个编号对应的英文，先从自己的英文游戏副本读取原文。在仓库根目录运行下列 PowerShell 命令，把示例路径换成实际游戏目录。

```powershell
$game = 'D:\Games\Prototype'
python .\source\PrototypeZh\tools\read_catalog_sources.py --game $game
python .\source\PrototypeZh\tools\catalog.py ui --start 0 --end 5
python .\source\PrototypeZh\tools\catalog.py subtitles --pending
python .\source\PrototypeZh\tools\catalog.py audio --pending
```

原文写入 `work/PrototypeZh/english-catalog/`。本版对应 3,127 条界面文本、957 条剧情字幕和 14,318 条语音字幕。要修改译文，编辑 `catalog/ui/`、`catalog/subtitles/` 或 `catalog/audio/` 的相应条目。

## 构建 Windows 安装器

构建环境需有 Python 3.13、fontTools、含 `javac` 的 JDK、MSVC x86 编译工具、Windows SDK 和 .NET Framework 4.x 的 64 位 C# 编译器。将以下外部输入放在仓库根目录的 `vendor/` 下。

- `ffdec_26.4.0/`，包含 `ffdec.jar` 和 `lib/`。
- `NotoSansCJKsc-Regular.otf`、`NotoSansCJKsc-Medium.otf`、`NotoSansCJKsc-Bold.otf`、`NotoSans-Regular.ttf` 和 `NotoSansMath-Regular.ttf`。CJK 字体版本为 2.004，使用的字重与校验值见 `source/PrototypeZh/catalog/font-sources.json`。
- `CP936.TXT`，来源和 SHA-256 见 `source/PrototypeZh/tools/font_charset.py`。
- 官方 Windows 嵌入包 `python-3.13.12-embed-amd64.zip`。构建脚本核对该文件的 SHA-256。

执行过上面的原文读取命令后，使用同一份英文原版游戏生成资源。安装器使用英文原版的 `cementfiles.p3d` 作为注册模板。这些操作只读取游戏目录。

```powershell
Copy-Item .\source\PrototypeZh\licenses\*.txt .\vendor\
Copy-Item -LiteralPath (Join-Path $game 'cementfiles.p3d') -Destination .\source\PrototypeZh\packaging\registration.p3d
python .\source\PrototypeZh\tools\inventory_all.py --game $game --out .\work\PrototypeZh\full-inventory
python .\source\PrototypeZh\tools\build.py --game $game --work .\build
python .\source\PrototypeZh\packaging\build_delta.py prepare $game .\build\package .\build\payload.zip
python .\source\PrototypeZh\packaging\build_delta.py installer .\build\payload.zip .\vendor\python-3.13.12-embed-amd64.zip .\dist
```

## 重新打包源码

仅生成 GitHub 源码 ZIP 时，在仓库根目录运行以下命令即可。压缩包从文本源文件直接生成。

```powershell
python .\source\PrototypeZh\packaging\build_delta.py source .\dist\Prototype-Chinese-v0.2.13-delta-source.zip
```
