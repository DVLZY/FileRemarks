# FileRemarks 实现备注（从 README 移出的技术细节）

本文承接精简后的 `README.md`，保留安装布局、注册表与实现层面的细节，便于排查问题和回溯设计。
完整的旧版 README（含历史版本流水、逐项测试记录、早期调试过程）见
[README-full-backup.md](README-full-backup.md)。

## 组成

安装包解出 4 个组件，全部位于 `C:\Program Files\FileRemarks\app-<版本>\`：

| 文件 | 作用 |
| --- | --- |
| `FileRemarksPropHandler.dll` | 属性处理器：把备注发布为 `System.Comment`，供资源管理器列与详情窗格读取 |
| `FileRemarksShellExt.dll` | 右键菜单“编辑备注” |
| `FileRemarksEditor.exe` | 备注编辑窗口（客户区 464×238，原生标题栏显示文件名） |
| `FileRemarksHotkey.exe` | 常驻热键程序，只注册 `Shift+F2`，不做键盘钩子 |

## 存储

- 普通文件：NTFS 备用数据流 `:remark`，UTF-8 文本。
- 图片、视频、音频等系统已有原生备注处理器的类型：复用原生处理器，读写其 `System.Comment`。
- Word / Excel / PowerPoint（OOXML）：由本工具直接解析 `docProps/core.xml`；备注写入文档元数据，
  因此这类文件复制到其他磁盘也会带着备注。OOXML 的标题、作者等其它原生属性只读
  （重写 Office 可能正打开着的 ZIP 包风险过高）。

## 备注列

- 列是 Windows 自带的 `System.Comment`（显示名即“备注”），无需注册自定义 `.propdesc`。
- 安装时把六种文件夹类型的默认视图复制到当前用户：
  通用、文档、图片、下载、音乐、视频。
  路径：`HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\FolderTypes\<GUID>\TopViews\{00000000-0000-0000-0000-000000000000}`，
  在 `ColumnList` 末尾追加 `;0System.Comment`。
- 必须整份复制视图，不能只写 `ColumnList`，否则 `LogicalViewMode`、`SortByList`、`IconSize` 等会丢失。
- 原始 `ColumnList` 先备份到 `HKCU\SOFTWARE\FileRemarks\ColumnList\<GUID>`，该键同时作为“这是本工具写的覆盖”
  的标记；卸载时据此还原。
- 用户自己保存过的文件夹视图（Bag）优先级高于默认视图，本工具不修改它。
- 资源管理器退出时才重写已打开窗口的列布局，所以安装后需要重启资源管理器，已打开的窗口才会出现新列。

## 安装与卸载

- 安装器是单个 EXE：自解压 4 个文件 → 写入 HKLM 注册项（需要管理员）→ 启动热键程序 → 刷新 Shell。
- 版本目录形如 `app-1.23`；目录被占用时退让为 `app-1.23-2`、`app-1.23-3`。
  被资源管理器加载的 DLL 不能覆盖或改名，只能整目录替换；旧目录在下次安装时清理。
- 卸载项写在 `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\FileRemarks`；实际卸载仍会提权以撤销 HKLM 注册。
- 覆盖安装不需要先卸载，安装器会停止正在运行的热键程序并切换版本目录。

## 编辑窗口行为

- 无按钮：窗口失焦、关窗（X）或 `Ctrl+Enter` 都会保存；`Esc` 是取消，丢弃本次修改。
- 保存失败时窗口保持打开，不会静默丢字。
- 保存成功后主动通知 Shell（`SHCNE_UPDATEITEM` + 父目录 `SHCNE_UPDATEDIR`），列值立即刷新。
- 深浅色跟随系统设置。

## 构建

```bat
tools\build_mingw.sh
python tools\build_installer.py
```

产物为 `dist/releases/FileRemarks_Setup_v<版本>.exe`；`dist/releases/` 按版本归档，历史安装包不会被覆盖。
仓库内 `src/` 为唯一源码，`build/ui-proposals/` 只是未采用的界面提案，不在产品中。
