# Albert水印工坊

一款 macOS 桌面照片水印工具，用中文清爽界面给照片批量添加**文字水印、图片水印（Logo）和摄影信息条**，支持先裁剪后加水印。基于 Python + PySide6 + Pillow 开发，完全本地运行、离线免费、无内购无上架。

## 功能特性

- **三种水印方式**
  - 文字水印：自定义文字、字体、字号、透明度、颜色、描边、旋转角度、九宫格位置
  - 图片水印：叠加 Logo（PNG/JPG/WebP），支持缩放与位置
  - 信息条（摄影排版）：相机型号、光圈、快门、ISO、焦距、拍摄时间、地点、署名等 EXIF 信息合成底部信息条，内置多种布局与品牌配色
- **批量处理**：一次导入多张图，每张可独立设置不同模版
- **模版画廊**：内置布局骨架与品牌配色模版，一键套用
- **先裁剪后水印**：支持常见宽高比裁剪
- **EXIF 保留**：导出时可选择保留原图 EXIF（含 GPS）元数据
- **预设系统**：参数可保存为预设，一键恢复默认

## 安装

### 环境要求

- macOS（Apple Silicon 或 Intel 均可）
- Python 3.11+

> 💡 **下载现成 App**：无需安装 Python，直接到 [Releases](../../releases) 页面，按你的芯片选择对应安装包：
> - **Apple 芯片（M1/M2/M3/M4/M5 及后续 M 系列）** → `macOS-AppleSilicon` 版（arm64 原生）
> - **Intel 芯片** → `macOS-Intel` 版（x86_64）

### 安装依赖

```bash
# 建议使用虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖（PySide6 官方源较慢，可换清华镜像）
pip install -r requirements.txt
# 或
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 运行

```bash
python run.py
```

## 打包为 macOS App

```bash
pip install pyinstaller
pyinstaller --noconfirm build_watermark.spec
# 产物位于 dist/Albert水印工坊.app
```

## 命令行入口（可选）

项目根目录附带两个无 GUI 的命令行脚本，用于快速验证核心算法：

```bash
# 单张图加文字水印
python wm.py 输入图.jpg [输出图.jpg]

# 批量加水印（文字 + 图片，九宫格位置）
python batch_wm.py 输入文件夹 [输出文件夹]
```

## 项目结构

```
watermark-app/
├── src/watermarker/
│   ├── core/          # 核心算法：水印、裁剪、信息条、EXIF、批量、配置
│   ├── ui/            # GUI 界面、主题样式、后台渲染 worker
│   ├── assets/        # 品牌图标、开源字体
│   └── app.py         # 应用启动入口
├── run.py             # 开发期启动器
├── wm_app_entry.py    # PyInstaller 打包入口
├── build_watermark.spec  # 打包配置
├── tests/             # 单元测试
└── requirements.txt   # 依赖清单
```

## 字体与图标授权说明

本项目使用以下开源字体，遵循各自授权协议：

- **思源宋体（Source Han Serif）**：SIL Open Font License 1.1，Adobe 与 Google 联合开发，可免费商用、自由修改与分发。
- **MiSans**：小米官方字体，遵循《MiSans 字体知识产权许可协议》，允许免费使用（含商用），使用时需注明字体来源，且不得对字体文件本身进行改编或单独分发。

`assets/icons/` 中的相机品牌 Logo（Sony、Canon、Nikon、Leica 等）为对应品牌商标，仅作界面品牌选项展示用途，相关权利归各品牌所有。

## 许可证

MIT License（见 [LICENSE](LICENSE)）。

> 注：字体与品牌图标资源保留其各自的原授权，不随 MIT 许可证一并授权。
