# Albert水印工坊 v1.2.1

本次更新主要带来 **Apple Silicon（M 系列芯片）原生版本**，并修复了自动打包流程。

## 🚀 新增

- **Apple Silicon (arm64) 原生支持**：新增 Apple 芯片（M 全系列，含 M1/M2/M3/M4/M5 及后续型号）原生 `.app` 包，无需 Rosetta 转译，性能更佳、启动更快。
- **双平台自动化构建**：接入 GitHub Actions，推送版本 tag 后自动打包并发布 macOS **Apple Silicon (arm64)** 与 **Intel (x86_64)** 两个版本。

## 🐛 修复

- 修复 CI 打包流程中 macOS runner 标签失效问题（`macos-14` / `macos-13` 已由 GitHub 官方退役，改用 `macos-15` / `macos-15-intel`）。

## 📦 下载

请根据你的 Mac 芯片选择对应安装包：

| 芯片 | 下载文件 | 说明 |
|------|----------|------|
| **Apple 芯片（M 全系列，M1/M2/M3/M4/M5 及后续）** | `Albert水印工坊-macOS-AppleSilicon.zip` | arm64 原生版，推荐 |
| **Intel**（x86_64） | `Albert水印工坊-macOS-Intel.zip` | Intel 版 |

> 💡 不确定芯片？点击左上角  苹果菜单 →「关于本机」→ 查看「芯片」一栏：显示 **Apple M 系列** 选 Apple Silicon 版，显示 **Intel** 选 Intel 版。

## ⚠️ 首次打开提示

由于未做 Apple 开发者签名，首次打开可能出现「无法验证开发者」提示：

1. 右键点击 App → 选择「**打开**」
2. 在弹出的对话框中再次点击「**打开**」

即可正常使用。

---

**校验方式**（可选）：下载后在终端运行 `file "Albert水印工坊.app/Contents/MacOS/..."`，Apple Silicon 版应显示 `arm64`，Intel 版应显示 `x86_64`。
