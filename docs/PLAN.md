# 2026-11-06 · 照片水印软件（个人自用）

## 项目状态

- 位置：`/Users/mac/WorkBuddy/2026-11-06-20-04-07/watermark-app/`
- 需求（已与用户确认）：macOS 桌面 · 中文清爽界面 · 文字+图片水印 · 先裁剪再加水印 · 无内购无上架
- 技术栈：Python 3.13.12 + Pillow 12.3.0（已装）+ PySide6（未装，S2 阶段装）

## 已完成

### S0 完成（2026-11-06）
- 建好目录骨架：`src/watermarker/{core,ui/widgets}/`、`assets/{fonts,icons}/`、`tests/`、`fixtures/`、`build/`、`docs/`
- 写核心模块 `src/watermarker/core/watermark.py`：
  - `TextWatermark` / `ImageWatermark` dataclass + 九宫格位置 + 千分比缩放参数
  - `add_text_watermark` / `add_image_watermark` / `add_tiled_watermark`
  - 关键点：RGBA 独立层 + alpha_composite；textbbox 量字；EXIF exif_transpose；旋转用独立小图层
- 命令行入口 `wm.py`，`python wm.py 输入.jpg` 即可加水印
- 验证通过：生成 fixtures/sample.jpg → sample_wm.jpg，水印半透明、黑描边、右下角、中文正常

## 环境坑（重要，勿踩）

- **这台 Mac 没有 `/System/Library/Fonts/PingFang.ttc`**（新 macOS 命名变了），会导致 `ImageFont.truetype` 报 `OSError: cannot open resource`。
- 可用中文字体（已验证可加载）：`/System/Library/Fonts/Hiragino Sans GB.ttc`（冬青黑，当前默认）、`STHeiti Light/Medium.ttc`、`/System/Library/Fonts/Supplemental/Songti.ttc`、`Arial Unicode.ttf`。
- **Pillow 13.0.0 移除了 `Image.stride` 属性**（12 还有）。PIL→QImage 转换不能再用 `img.stride`，要显式算 `width * channels`。已修进 `pil_to_qpixmap`。
- PySide6 下载用官方源极慢（36 kB/s），换清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 后 22 MB/s。

## 依赖安装（已完成）

- 虚拟环境 `.venv`（Python 3.13.12）已建好
- PySide6 6.12.0（用户自行用清华镜像装）
- Pillow 13.0.0（清华镜像装）
- `requirements.txt`、`.gitignore`、`run.py` 已就位

## S4 完成（2026-11-06）

- `core/crop.py`：`crop_to_ratio`/`apply_crop`/`CropSpec`，居中裁剪保持比例不变形，支持 1:1/4:5/3:4/9:16/16:9；7 个用例全过
- `core/config.py`：参数 JSON 序列化；修复 JSON 把 tuple 转 list 导致 `color+(alpha,)` 报错的坑（from_dict 转回 tuple）
- `ui/main_window.py`：拖拽导入（dragEnterEvent/dropEvent + `_add_files` 去重）；比例裁剪下拉框；预设保存/加载按钮；导出按钮加 objectName
- `core/batch.py` + `ui/worker.py`：加 `crop_ratio` 参数，导出时先裁剪再加水印
- `ui/theme.qss` + `app.py`：清爽简洁主题（navy #1C3A6B 主色，QSS 皮肤加载）
- 验证通过：裁剪 1:1 三张不同尺寸图全变方形；预设 round-trip 相等；QSS 加载正常
- 注意：离屏测试里 QMessageBox 阻塞导致 SIGTERM，属测试环境问题，真实 GUI 正常

## 计划（6 阶段）

S0 命令行水印 ✅ → S1 参数化+九宫格+批量+图片水印 ✅ → S2 首个 GUI ✅ → S3 批量线程+进度条 ✅ → S4 拖拽+预设+裁剪+皮肤 ✅ → S5 打包 .app

## 功能完善（S4.5，2026-11-06）

在 S5 之前补充的 6 项功能，全部验证通过：

1. **平铺水印**：`add_tiled_watermark` 接进 UI（`tiled_enabled` 开关 + 间距滑块），支持颜色/描边参数；core 加了 `color`/`stroke_width`/`stroke_color` 参数
2. **水印高级参数**：旋转角度（-90°~90°）、边距（0~200）、描边粗细（0~10）三个控件接入 `TextWatermark`
3. **文字颜色自定义**：白/黑/灰下拉 → `QColorDialog` 取色器 + 色块按钮 + hex 标签，任意 RGB
4. **文件列表管理**：移除选中 / 上移 / 下移 / 清空按钮（`_remove_selected`/`_move_selected`）
5. **导出格式与质量**：原格式/JPG/PNG 切换 + 质量滑块（1~100）+ EXIF 保留开关
6. **预览缩放 + 九宫格可视化**：预览缩放（+/−/适应窗口）；九宫格下拉 → 3x3 可点击按钮组

### 关键坑（EXIF 保留）

- `img.info["exif"]` 经过 `alpha_composite`/`convert("RGB")` 会丢，仅靠 `out.info["exif"]=bytes` 写回无效。
- 正确做法：在 `save_image` 加 `exif` 参数，保存时显式 `img.save(..., exif=bytes)`（仅 JPEG/TIFF 支持）。
- 默认不保留 EXIF（避免泄露 GPS 隐私），`keep_exif` 勾选才写回。

### 相关文件改动

- `core/watermark.py`：`add_tiled_watermark` 加 color/stroke 参数
- `core/image_io.py`：`save_image` 加 `fmt`/`exif` 参数（fmt 强制输出格式，exif 显式写回）
- `core/batch.py`：`process_batch` 加 `tiled`/`output_format`/`keep_exif` 参数，顺序改为「裁剪→文字→平铺→图片」
- `ui/worker.py`：`ExportWorker` 加 `tiled`/`output_format`/`keep_exif` 参数传递
- `ui/main_window.py`：重写参数面板（九宫格按钮组/取色器/旋转/边距/描边粗细/平铺/格式质量/缩放），预设字段同步扩展
- `ui/theme.qss`：加九宫格按钮（checkable）、QSpinBox 样式

## 待办（下一步 S5 打包）

- S5：PyInstaller 打包 .app（`pyinstaller --windowed --add-data` 带资源 + 图标 + `sys._MEIPASS` 处理资源路径）；验证无 Python 环境也能跑
