[中文](README.md) | [English](README_EN.md)

# Prototype (2009) Chinese Localization Patch

A Simplified Chinese localization patch for the PC version of **Prototype (2009)**, covering menus, missions, skills, story content, and in-game dialogue subtitles.

**Current version:** v0.2.13 · [Releases](https://github.com/OBLPlife/Prototype-Chinese/releases)

The installer reads the player's local game resources and generates a Chinese localization overlay.

Modern compatibility patch: [Prototype-Modern-Compatibility](https://github.com/OBLPlife/Prototype-Modern-Compatibility)

## Screenshots

<table>
  <tr>
    <td align="center" width="50%"><img src="screenshots/20261122185115_1.jpg" alt="In-game screenshot 1" width="100%"></td>
    <td align="center" width="50%"><img src="screenshots/20261122185132_1.jpg" alt="In-game screenshot 2" width="100%"></td>
  </tr>
  <tr>
    <td align="center" width="50%"><img src="screenshots/20261122185145_1.jpg" alt="In-game screenshot 3" width="100%"></td>
    <td align="center" width="50%"><img src="screenshots/20261122185153_1.jpg" alt="In-game screenshot 4" width="100%"></td>
  </tr>
</table>

## Installation & Restoration

**Install**

1. Exit the game. The English-language game resources are recommended.
2. Download `Prototype_ZH_CN_Setup.exe` from [Releases](https://github.com/OBLPlife/Prototype-Chinese/releases).
3. Place the installer in the game directory, alongside `cementfiles.p3d`.
4. Run the installer and select **安装** (Install).
5. Launch the game normally after installation.

**Restore**

Exit the game, run the same installer in the game directory, and select **还原** (Restore).

The installer backs up affected files and restores their previous contents when requested. Keep the `PrototypeZh` backup directory intact.

Allow approximately **1.2 GiB** of free space on the game drive for the generated localization resources during the first installation. Additional space may be required to back up existing files.

## Localization Features

- **18,402 main text records:** 3,127 UI entries, 957 story subtitle entries, and 14,318 audio-embedded dialogue subtitle entries.
- **Menus and missions:** Settings, controls, objectives, skill names, upgrades, and Web of Intrigue text.
- **Dialogue and subtitles:** Story, combat, and character dialogue, including subtitles embedded in the original audio resources.
- **Chinese fonts:** Full GBK character coverage with separate Noto Sans CJK font weights for titles, menus, and subtitles.
- **Text layout:** Adjustments to upgrade menu labels, Evolution Points display, and selected subtitle layouts.
- **Consistent terminology:** Localized in-universe organizations, abilities, and project names while preserving personal names in credits and real-world company names.
- **Original visuals:** Street signs, advertisements, posters, and other environmental textures remain unchanged.

## Building from Source

This repository includes translation catalogs, a C++ localization runtime, ActionScript UI sources, a C# installer, and Python resource-building utilities. Building requires English-language game resources, external tools, and font files.

Key dependencies include Windows x64, Python 3.13, fontTools, JDK, FFDec 26.4.0, MSVC x86, Windows SDK, the .NET Framework 4.x C# compiler, Noto fonts, and the official Python 3.13.12 embeddable runtime. Font sources and hashes are documented in [catalog/font-sources.json](catalog/font-sources.json).

Build tools are available in [tools/](tools/) and [packaging/](packaging/).

### Repository Layout

| Path | Contents |
| --- | --- |
| `catalog/` | UI, story, audio subtitle, and terminology translations |
| `runtime/` | C++ font, subtitle, and runtime support |
| `src/` | ActionScript UI text sources |
| `tools/` | Resource extraction, font generation, translation merging, and checks |
| `packaging/` | Installer, build, and restoration code |
| `licenses/` | Third-party Noto font licenses |
| `screenshots/` | In-game screenshots |

## Important Notice

**This is a preview release. Unknown issues may still exist.**

