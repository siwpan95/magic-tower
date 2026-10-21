# Changelog

本项目所有值得注意的变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 完整重写 `README.md`：项目简介、特性、快速开始（含打包）、操作说明、玩法系统、项目结构、数据表结构、测试与路线图。
- `README.en.md` 由 Gitee 模板占位文本替换为真实英文说明（与中文版内容对齐）。

### Fixed

- 打包章节不再引用仓库内不存在的 `*.spec`（该文件含本机绝对路径，从未入库且被 `.gitignore` 忽略），
  改为给出等价的 `pyinstaller` 命令行与 `pyi-makespec` 生成方式。

## [1.0.0] - 2026-08-27

### Added

- 首个发行版：Windows 可执行程序（PyInstaller，Python 3.14）。
- 发布面：gitee [siwpan/magic-tower](https://gitee.com/siwpan/magic-tower) release `v1.0.0`（魔塔 v1.0.0）。