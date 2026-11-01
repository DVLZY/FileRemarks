# FileRemarks — 资源管理器“备注”属性工具

给**任意格式**的文件在 Windows 资源管理器里加一个“备注”属性（就像文件名、类型、大小那样），
用来记录这个文件是干什么的，方便以后回忆。**exe / png / jpg / doc / docx / py / md …** 都支持。

- **查看备注**：资源管理器里加一列“备注”（安装后**默认就已经打开**），或右键 → 属性 → 详细信息
- **新增 / 修改 / 删除备注**：右键文件 → **编辑备注**（菜单项前面带本软件的图标）
- 弹窗里**没有按钮**：输入完直接关窗口、或切到别的窗口，都会自动保存
- 每次只处理一个文件，没有批量、没有导入导出，纯本机使用

---

## 它怎么工作的

备注文本存在两个地方，各管一件事：

| 存放位置 | 作用 |
| --- | --- |
| 文件自己的 NTFS 备用数据流，流名 `:remark`（UTF-8） | **真正的备份**。跟着文件走（同分区改名/移动不丢），任何文件类型都能写 |
| Windows 内置的 `System.Comment` 属性（资源管理器里就叫“备注”） | 让**系统自带属性的文件类型**（doc/docx/xls/xlsx/ppt、图片、视频）那一列有内容 |

为什么需要两处：一个文件类型的“属性列”由系统里的**属性处理器**（Property Handler）决定，
而每类文件只能有一个。Windows 对很多类型已经自带了，我们不能直接顶掉——顶掉会让这些文件
丢掉自带的“详细信息”（比如图片的尺寸、Word 的页数）。所以：

- **系统没自带处理器的类型**（`py / md / txt / json / cpp / zip / 7z / pdf / 各种源码和配置文件`…）
  → 安装我们自己的处理器，从 `:remark` 读，列直接显示。
  除了逐个列出的常见类型，还注册了一条\*通配兜底，所以**没被列出、甚至你自己发明的扩展名也照样有这一列**
  （`tools/test_wildcard_safety.py` 逐个核对了本机 247 个原生类型，确认兜底不会抢走任何原生列）。
- **系统自带处理器但可以被我们“包一层”的类型**（`exe / dll / sys / png / jpg / gif / ico / mp3 / mp4 / wav / mkv`…）
  → 我们把自己的处理器套在原处理器外面：**原生属性一个不少地转发**，只额外加上“备注”。
  这个已经用真实文件验证过（`tools/test_wrap_ctypes.py`）。
- **系统自带且不能包的类型**（`doc / docx / xls / xlsx / ppt / pptx` 等 Office 文档）
  → 不碰它的处理器，改为把备注**写进文件自己的 `System.Comment`**。Office 的元数据处理器
  支持写这个属性（`tools/test_native_comment_ctypes.py` 在真实 .docx/.xlsx 上验证过），
  所以资源管理器里的“备注”列照样有值。这些文件的“编辑备注”也依然可用。
  为了让\*通配兜底不会误伤它们，安装时会把它们**钉回**系统原本的处理器（写的值就是原来那个
  CLSID，对用户没有任何改变），卸载时再撤掉。

---

## 安装（不需要管理员权限）

**只有一个文件：`dist/releases/FileRemarks_Setup_v1.13.exe`**

> `dist/releases/` 里按版本号归档，**每次迭代都保留之前的安装包**，文件名带版本后缀，
> 所以想回到旧版随时双击对应的那个即可（例如 `FileRemarks_Setup_v1.7.exe`）。

1. 双击它。**不会弹 UAC，也不会有 SmartScreen 的“发行者未知”警告**——见下面的说明。
2. 弹出安装窗口（Win11 风格，左上角是软件图标）。窗口里先用两栏把版本摆清楚：

   | 当前已安装版本 | 要安装的版本 |
   | --- | --- |
   | 例如 `v1.11`，或 `旧版本（未记录版本号）`，没装过则显示 `未安装` | `v1.13（本安装包）` |

   下面两个按钮：**安装 / 重新安装**（蓝底，回车等同）、**卸载**。没有“取消”按钮——
   不想操作就**直接关窗口或按 `Esc`**。
   已经装过时主按钮变成“重新安装”；没装过时“卸载”会被忽略（不会误删）。
3. 看到“安装完成”后，**重启资源管理器**（任务管理器 → 选中“Windows 资源管理器” → 右下角“重新启动”）。

装完在任意文件上右键就有“编辑备注”。卸载用同一个 exe（也在“设置 → 应用”里有
`FileRemarks` 这一项）。

> ### 为什么以前会弹“Windows 已保护你的电脑 / 发行者未知”
>
> 那不是病毒告警，是 SmartScreen 对**正在申请管理员权限的未签名程序**做的信誉检查。
> v1.8 及更早的安装器会 `runas` 自提权（往 `C:\Program Files` 装、写 `HKLM`），
> 而没有商业代码签名证书，于是 Windows 判定“发行者未知”。
>
> **v1.9 起安装器完全不申请提权**：装到当前用户自己的目录
> `%LOCALAPPDATA%\FileRemarks`，所有登记项写进 `HKCU`（`HKCU\Software\Classes` 会并入
> `HKCR`，资源管理器照样认）。没有提权请求 ⇒ 没有 UAC ⇒ **没有这个提示**，
> 也不需要买证书。
>
> 如果你从网络盘/共享目录直接双击（本机有 `X:` `Y:` `Z:` 三个映射），Windows 仍可能
> 按“Internet 区域文件”给一个安全警告——那不是本程序的问题，把 exe 复制到本机硬盘再双击即可。
> 安装器是**原生 Unicode 程序**（不是 .bat），中文 Windows 上没有代码页乱码问题；
> 组件已嵌在 exe 尾部，双击后自己解压、自己注册。出问题时的诊断日志在 `%TEMP%\FileRemarks_log.txt`。

### 从 v1.8 及更早版本升级

第一次装 v1.9 时会**同时存在两份**：新的在 `%LOCALAPPDATA%\FileRemarks`（生效），
旧的 `C:\Program Files\FileRemarks` 只是残留。点“安装”后结束提示里会说明，
想彻底清掉旧目录需要管理员权限手动删除——留着也不影响使用。

### 覆盖安装时提示“文件正被使用”

旧版 DLL 通常已经被资源管理器加载，Windows 不允许直接覆盖。安装器会自动：把占用的旧文件
**改名**成 `*.old`（加载中的 DLL 允许改名）→ 写入新文件 → 旧的 `*.old` 排到下次重启删除。
所以覆盖安装**不需要先关资源管理器**。

### 备用：手动安装

1. 把 `dist/` 里的 3 个文件复制到 `%LOCALAPPDATA%\FileRemarks\`：
   `FileRemarksPropHandler.dll`、`FileRemarksShellExt.dll`、`FileRemarksEditor.exe`
2. 用**当前用户**的命令提示符执行（不需要管理员）：
   ```bat
   regsvr32 "%LOCALAPPDATA%\FileRemarks\FileRemarksPropHandler.dll"
   regsvr32 "%LOCALAPPDATA%\FileRemarks\FileRemarksShellExt.dll"
   ```
3. 重启资源管理器。

卸载：`regsvr32 /u` 两个 DLL，再删目录。

---

## 使用

1. 文件上**右键 → 编辑备注**（菜单项前面带本例的蓝色图标）。
2. 弹窗里直接输入备注（支持多行中文）。
3. **没有按钮**：把窗口关掉、或者切到别的窗口，内容就自动保存了；状态栏会显示“已自动保存。”。
   想清掉备注：把文字全删掉，然后关窗口（或切走）——同样自动保存为空。
4. 列**安装时就已经打开了**，不用手动加。保存后列里的值会**立刻**变，不需要按 F5：
   编辑器保存成功后会主动通知 Shell（`SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_FLUSH, ...)`
   加上父目录的 `SHCNE_UPDATEDIR`），资源管理器收到就重读这一个文件。
   `tools/test_no_delay.py` 就是守这一条的。

> 弹窗里的文件名是只读的，防止改错文件。
> 窗口内快捷键：`Ctrl+A` 全选、`Ctrl+Backspace` 删一个词、`Esc` 或 `Ctrl+Enter` 直接关窗口
> （都会自动保存）。

5. 也可以在资源管理器里**先选中一个文件，按 `Ctrl+Alt+E`**，直接弹出它的备注窗口。
   这个组合键由一个常驻小程序 `FileRemarksHotkey.exe` 注册（安装时自动启动，写在
   `HKCU\...\Run\FileRemarksHotkey`，卸载时自动退出并删除）。它只监听这一个组合键，
   不做键盘钩子，所以不会影响 F8 之类的单键；没有选中文件时按下不会做任何事。

### 关于“备注”列的默认显示

安装时会给资源管理器的几种文件夹类型（通用文件夹、文档、图片、下载、音乐、视频）的默认视图
末尾追加 `System.Comment` 这一列——也就是 Windows 早就叫“备注”的那一列。原始列定义会在改动前
备份到 `HKCU\SOFTWARE\FileRemarks\ColumnList\<folder-type-guid>`，卸载时原样还原
（只覆盖当前用户自己的列定义，机器级的那份原封不动）。
已经单独调整过列顺序的文件夹不受影响（我们只改“默认视图”，不动你自己存过的视图）。

> 如果你之前手动调过某个文件夹的列，那个文件夹会保留你调过的样子；把列恢复默认即可看到“备注”。

---

## 验证情况

十五个测试脚本 + 五个回归探针全部通过，都是**真实调用编出来的二进制**（真实 NTFS 卷、真实 GUI 窗口、真实 COM 对象、真实注册表读取）：

| 测试 | 覆盖什么 | 结果 |
| --- | --- | --- |
| `tools/test_prophandler_ctypes.py` | 属性处理器端到端：创建 COM 对象 → 初始化真实文件 → `GetCount`/`GetAt` → `SetValue`+`Commit` 写流 → `GetValue` 读回中文 → 清空删流 | **PASS**（`GetAt(0)` 返回 `System.Comment`，pid 6） |
| `tools/test_wrap_ctypes.py` | 包一层不丢原生属性：`.exe`（12 个属性、11 个原生全部可读）、`.jpg`（9 个属性，`160 x 90` 图片尺寸经我们转发读得到），且 `System.Comment` 只出现一次 | **PASS** |
| `tools/test_native_comment_ctypes.py` | 写 `System.Comment`：真实 `.docx`/`.xlsx`/`.jpg`/`.png` 写入-读回-清空全部成功；`.exe` 被干净拒绝且文件未损坏；相对路径也能写；`HandlerIsOurs()` 与真实注册表一致 | **PASS** |
| `tools/test_columns_ctypes.py` | 默认列：`BuildColumnList()` 追加字面量、保持原有顺序、幂等、清理结尾分号、对空串/纯空白拒绝；并对着真实 `Generic` 列定义核对每个条目都合法 | **PASS** |
| `tools/test_installfile_ctypes.py` | 覆盖安装“文件被占用”：用与加载器相同的共享模式锁住目标 DLL，复现 `ERROR_SHARING_VIOLATION`；确认 `InstallFile` 能改名腾位、写入新内容、旧副本留成 `.old`；连续两次覆盖（目标与 `.old` 双锁）也通过 | **PASS** |
| `tools/test_shellext_ctypes.py` | 右键菜单：真实 `IDataObject`（CF_HDROP）+ `QueryContextMenu` → 菜单里出现 **“编辑备注”**、未禁用、提示文字正确；读到菜单项的 `hbmpItem` 并核对是 **16×16 32bpp、中心蓝色、角上透明**；`InvokeCommand` 真的把编辑器启动起来 | **PASS** |
| `tools/test_editor_gui.py` | 真窗口全流程（**无按钮版**）：确认 104/105/2 三个按钮已不存在 → 输入中文后关窗口，`:remark` 内容一致 → 重开能读回 → 改完只切走焦点也自动保存且状态变“已自动保存。” → 切走焦点后窗口仍在（不关窗） → 空的切换不写文件 → 删光文字再关窗口，流被删除；窗口标题是“备注”、窗口图标 `WM_GETICON` 非空；卡片白、页面 `(243,243,243)`（采样点按实时客户区取，不再是写死坐标） | **PASS** |
| `tools/test_editor_layout.py` | 窗口按内容自适应大小：短路径客户区 `464x296`；163 字符的长路径**不会把窗口撑宽**（宽度仍是 464），而是把路径折成 4 行、窗口长高到 `464x326`；**路径控件自己报的行数（`EM_GETLINECOUNT`）必须 ≤ 它能显示的行数**——这才是“文件名不再被截断”的直接证据；两个尺寸下“文件路径/备注框/状态行”三个控件都完整落在客户区内；路径控件贴在图标的右侧顶部（`x=64, y=24`，证明“文件”标签行已消失）；状态行以下只剩 10px 余量 | **PASS** |
| `tools/test_placeholder.py` | 空备注框真的显示提示语：空的时候框里有 170 个非白像素（提示语 `在这输入备注...` 画在上面）→ 输入自己的文字后提示语消失、且框里的值只有输入的内容（提示语**不会**被存进去）→ 再清空，提示语又回来（170 像素）；**真按键**（`WM_CHAR`）敲一个字后，除该字符所在的 20px 列以外所有列都必须干净，再用退格删空后提示语必须重新出现（170 像素）——用 `WM_SETTEXT` 测不出“提示语和文字叠在一起”，因为它会重绘整个控件 | **PASS** |
| `tools/test_no_delay.py` | **没有延迟**：先确认新文件读不到备注 → 用真编辑器写入中文备注并关窗 → 立刻新建一个属性存储读 `System.Comment`，必须已经是最新文字；再读一次仍然一致（不是缓存碰巧）→ 清空后再读必须为空 | **PASS** |
| `tools/test_columns_autoenable.py` | **“备注”列自动打开**：先核字面量 `;0System.Comment`、追加只加一次且不动原有顺序、对已含该列的列定义是幂等的、结尾分号会被清掉；再问真实注册表“现在到底有几种文件夹类型显示着备注”（`FrTestCountEnabled`），跑一遍启用路径后再问一次，要求只增不减，并且“报告改了 0 个”真的对应数量没变（不允许出现“函数说改了、注册表没动静”）。本机沙箱里注册表写被拒，所以这里表现出来是 `2 / 6` 且 `0 changed` —— 这恰好证明它读的是真实状态，而不是照抄一句“成功” | **PASS** |
| `tools/test_installer_ui.py` | 安装窗口：已装版本/目标版本两者都对且互不相同（`旧版本（未记录版本号）` vs `v1.13（本安装包）`）；真窗口标题 `FileRemarks`、客户区宽 520 且高度随内容自适应、**只有两个按钮**（重新安装/安装 + 卸载，无“取消”）、两个按钮都完整落在客户区内（不裁切）、焦点在主按钮上、页面像素 `(243,243,243)`、卡片白、主按钮填充是纯蓝 `(0,95,184)`（证明按钮文字没有白底块）；关窗/`Esc` 返回 0、未安装时 `卸载` 点击无效、`Enter` 返回 1 | **PASS** |
| `tools/test_registry_plan.py` | 注册计划不变量：从源码解析出三张扩展名表，对着真实注册表重放注册决策，断言三张表互不重叠、无重复、候选类型从不指向我们、Office 永不落到我们头上、卸载能撤销注册写下的每一处 | **PASS** |
| `tools/test_wildcard_safety.py` | 通配注册的安全性：枚举本机 **247** 个有原生处理器的类型，逐个分类为「我们包一层(33)」/「钉回原生 CLSID(22)」/「安装时枚举后钉住(192)」，确认没有任何类型会因为 `*` 通配而丢掉原生列 | **PASS** |
| `tools/probe_stale_text.py` | **删掉的字必须真的从屏幕上消失**：9 种删法（退格删掉一整行、全选后删除、先滚动到底再全选删除、从中间删掉一行、选中尾部退格、全选后打一个字覆盖、长文缩成一行、词中间删掉一个字母、滚动后连着退格）三重判据都要过：① 控件里的值必须是剩下的文字；② 画面墨点数要和“新建窗口、只填最终文字”的干净画面一致；③ **强制整块重绘后墨点数不许减少**（少了就说明那些墨点是残留——控件早就忘了，屏幕还留着）。v1.10 之前“从中间删掉一行”残留 `468` 个墨点 vs 干净画面 `108`，整块重绘后掉到 `112`，即 `356` 个像素是假的；现在 9 种全部通过 | **PASS** |
| `tools/probe_button_flicker.py` | **安装窗口按钮不再闪**：载入真实的 `build/selftest_installer_ui.dll` 起出真窗口，确认父窗口带 `WS_CLIPCHILDREN`；连发 60 条 `WM_MOUSEMOVE` 后父窗口的 `GetUpdateRect` 必须一直为空（修复前每次移动都会让父窗口重绘、把页面底色刷到按钮上）；扫过按钮采样 240 个像素点，丢失 `0` 个；40 次完全相同的移动只触发 `80` 次按钮重绘（进入/离开各一次，且不再随消息数增长） | **PASS** |
| `tools/test_hotkey.py` | **常驻快捷键进程**：两个产物都在；`PackedCombo()` 必须等于 `0x00030045`（`Ctrl+Alt` + `E`）；进程起来后窗口类 `FileRemarksHotkeyWnd` 存在（证明组合键真的注册上了）；`%TEMP%\FileRemarks_hotkey.log` 里出现 `helper started`；向运行中的进程发 `WM_QUERY_COMBO` 也回同一个值；第二次启动立即退出且不影响第一个实例；`FrTestLaunchIn` 能起出 `FileRemarksEditorWnd` 窗口；选中的解析在拿不到 shell 视图时返回空串（不瞎猜）；`WM_CLOSE` 后窗口消失、进程退出码 0 | **PASS** |
| `tools/probe_stream_init.py` | **属性处理器能不能“只给流”地初始化**：不走注册表，直接把 DLL 载入，`DllGetClassObject` → 要 `IInitializeWithStream` → 建一个指向测试文件的流 → `Initialize(stream)` → `QI IPropertyStore` → `GetCount` 必须 ≥ 1。同一个脚本指向 v1.12 的 DLL 会红在“没有这个接口”（正是“备注列一直是空”的根因），指向 v1.13 全过 | **PASS** |
| `tools/probe_select_all.py` | **能全选、能一次删光**：起真编辑器、填三行中文，然后按 Ctrl+A —— 修复前 `EM_GETSEL` 拿到的是 `0..0`（一个普通 `EDIT` 控件从来没实现过 Ctrl+A，记事本的“全选”来自它自己的加速键表），所以既选不中也删不掉；现在断言全选范围是 `0..19`、按 Delete 后控件值为空、Ctrl+Backspace 删掉光标前一个词、全选后直接打字会整体替换。同一个脚本指向 Program Files 里那个已安装的旧编辑器时会 4 条全红，正好把“旧版本没这个功能”和“新版本坏了”区分开 | **PASS** |
| `build/selftest_extract.dll` + `FrSelfTest` | 从最终的 `dist/releases/FileRemarks_Setup_v1.13.exe` 真解压出 **4** 个文件，与 `dist/` 逐个 **sha256 完全一致** | **PASS** |

另外单独验证了旧版 Office 格式的 `System.Comment` 写入：真实 `.doc` / `.xls` / `.ppt` 都能写入、读回、清空；
`.rtf` 被拒绝（和 `.mp3` 一样属于“少数类型只写 ADS”的情况）。

**这台机器上唯一无法验证的**是“注册表写入 → 资源管理器真的把列显示出来”这一段：
本环境所有进程（含以更高权限重试）写注册表都返回 `0x80000005`（拒绝访问），
所以注册后的实际显示效果需要在你自己的机器上确认一次。默认列也一样：`tools/test_columns_autoenable.py` 能证明
“读到的是真实注册表状态”，但“写进去之后资源管理器真的多出一列”只能在你机器上看。

> 顺带一个在这台机器上查出来的事实，解释了旧版本为什么只成功了一半：六种文件夹类型的默认视图键
> 里，只有 **Music / Videos** 给 `Administrators` 了 `FullControl`，其余四种（Generic / Documents /
> Pictures / Downloads）只给 `ReadKey`。所以 v1.8 那种“提权后写 HKLM”的做法**天生**只能写进两种，
> 另外四种就算提权也写不进去，而安装器当时还照样说“列已打开”。v1.11 因此改成写当前用户自己的
> 视图副本（见下面更新记录），并从注册表读回来再报告，不再假报成功。

“安装器不再申请提权”这一条则是**真跑出来的**：`tools/probe_no_elevation.py` 直接启动
`dist/releases/FileRemarks_Setup_v1.12.exe`，读进程令牌确认未提权（`elevated=False`）、
安装窗口出自同一个未提权进程、全程没有任何 SmartScreen 窗口。

---

## 自己编译

### 方式 A：MinGW-w64（零安装）

```bash
bash tools/build_mingw.sh
```

脚本优先用 `tools/mingw64/bin/g++.exe`（便携工具链）；如果没有，就用 `PATH` 里的 `g++`
（`CXX=/path/to/g++` 可指定）。**GitHub 上的仓库不含那 900 MB 的便携工具链**，只含源码，
所以从仓库克隆后请先装 MinGW-w64（或直接用下面的 MSVC 方式）。

产物在 `build/` 和 `dist/`（`dist/` 里是可直接分发的成品）。
安装包会以 `dist/releases/FileRemarks_Setup_v<版本号>.exe` 的形式落盘，
**每次构建都保留历史版本**，不会被下一次构建覆盖（脚本只清理 `dist/` 顶层，
从不动 `dist/releases/`）。

### 方式 B：用 MSVC

在 **“x64 Native Tools Command Prompt for VS”** 里：

```bat
tools\build_msvc.bat
```

### 自检

```bash
python tools/check_logo.py                 # 图标几何形状（16/24/32/48/256 逐点断言）
python tools/test_prophandler_ctypes.py    # 属性处理器 COM 端到端
python tools/test_wrap_ctypes.py           # 包一层不丢原生属性
python tools/test_native_comment_ctypes.py # 写 System.Comment（Office/图片）
python tools/test_columns_ctypes.py        # “备注”列默认追加/还原逻辑
python tools/test_no_delay.py              # 保存后列没有延迟
python tools/test_installfile_ctypes.py    # 覆盖安装“文件被占用”恢复
python tools/test_shellext_ctypes.py       # 右键“编辑备注”菜单 + 菜单图标
python tools/test_editor_gui.py            # 真窗口：自动保存/无按钮全流程
python tools/test_editor_layout.py         # 窗口按长路径自适应、控件不越界
python tools/test_placeholder.py           # 空备注框里的提示语“在这输入备注...”
python tools/test_installer_ui.py           # 安装窗口：版本对比 + Win11 外观/按钮行为
python tools/test_registry_plan.py         # 注册计划不变量（只读真实注册表）
python tools/test_wildcard_safety.py       # 通配注册不会抢走原生列
```

想看窗口长什么样（不是断言，只是截图）：

```bash
python tools/shot_editor.py                # 把真实编辑窗口截到 build/_shot/*.png
python tools/show_shot.py build/_shot/short.png   # 用字符画在终端里看这张截图
```

排查提示语用的小探针（也是“真按键”路径，不是断言套件）：

```bash
python tools/probe_placeholder_overlap.py  # 打一个字后，提示语是否还留在右边
python tools/probe_cue_return.py           # 退格删空后，提示语是否回来
```

两个回归探针（v1.10 修的两个 bug，各自都能单独复现）：

```bash
python tools/probe_stale_text.py           # 删掉一部分文字后，被删的字是否还留在屏幕上
python tools/probe_button_flicker.py       # 鼠标在安装窗口里移动时，按钮是否被父窗口刷掉
python tools/probe_select_all.py           # Ctrl+A 能不能全选、能不能一次删光
```

> `probe_stale_text.py` 的判据很直接：把“删完之后的样子”和“新建一个窗口、只填最终文字的样子”两张画面比像素数，多出来的墨点就是残留；再加一条更硬的判据——**强制整块重绘一次，墨点数不许变少**，变少就说明那些墨点只是屏幕上的残影。它还可以把目标指向机器上已装的旧版本，用来分辨“是这个 bug 没修”还是“你跑的还是旧版本”：`python tools/probe_stale_text.py "C:\Program Files\FileRemarks\FileRemarksEditor.exe"`。`probe_button_flicker.py` 则直接问父窗口“你现在有要重绘的区域吗”——修复前每收到一条鼠标移动消息就有，修复后一直是空的。

验证“安装器不再申请提权”的探针（v1.9 的核心结论就靠它）：

```bash
python tools/probe_no_elevation.py         # 安装器进程未提权 + 窗口出自该进程 + 无 SmartScreen
python tools/probe_stream_init.py          # 属性处理器能不能被“只给一个流”地初始化
python tools/probe_hotkey_selection.py     # Ctrl+Alt+E 取选中文件那一步（本沙箱里必然 SKIP）
python tools/test_hotkey.py                # 常驻进程：组合键注册、单实例、关窗退出
python tools/probe_elev_series.py          # 对照实验：会提权的一组 vs 不会提权的一组，各跑 7 次
```

> `probe_elev_series.py` 是当初找出真正原因的实验：同一批未签名程序里，**申请提权**的那组
> 出现过“发行者未知”，**不申请提权**的那组 7 次全无。因为 SmartScreen 是概率性检查，
> 单次为“无”不能说明任何问题，必须跑多轮。

装完之后想确认“注册到底写对没有”，跑这个**只读**体检（不写任何东西、不启动任何进程）：

```bash
python tools/check_install.py
```

它会打印两个 CLSID 的 `InprocServer32` 指向哪个 DLL、那个 DLL 是否真的存在（不存在就是
`0x8007007E`）、抽样类型的关联在 HKCU 还是 HKLM、`*` 通配、两个安装目录的文件与大小、
六个文件夹类型的最终 `ColumnList` 里有没有 `System.Comment`、以及卸载项版本号。

它还会回答一个很容易踩坑的问题：**右键菜单那一刻到底启动了哪个编辑器**。右键菜单会从
“注册在案的那个 DLL 所在的目录”启动 `FileRemarksEditor.exe`，所以机器上如果还留着旧版本，
双击右键菜单用到的就是旧的那个编辑器；`check_install.py` 会把正在使用的编辑器和 `dist/` 里的
放一起比 sha256，直接打印 `OLDER build than dist/ -- reinstall to pick up the fixes`。

验证“HKCU 的登记项资源管理器到底认不认”（v1.9 改成按用户安装后的前提）：

```bash
python tools/probe_hkcu_assoc_prior_art.py # 本机已有的 HKCU-only 关联先例
python tools/probe_hkcr_merge.py           # HKCR 合并视图是否真的把 HKCU 项暴露出来
```

> 这两个探针也是只读的。`probe_hkcr_merge.py` 拿本机现成的
> `HKCU\Software\Classes\*\shellex\ContextMenuHandlers\CloudStation.SyncFolderContextMenu`
> 当证据：它只存在于 HKCU，而 `HKCR` 里能读到 ⇒ 合并视图确实生效；
> 同时它也把 `.txt/.md/.py/.jpg/.exe` 的 `PropertyHandler` 在 HKCR 里的取值打出来，
> 便于装完 v1.9 后对照“是否已经换成 HKCU 那一份”。

定位“备注列到底被谁挡住”用的三个只读探针：

```bash
python tools/probe_folder_types.py       # 六种文件夹类型各自的 ColumnList、长度、有没有 System.Comment
python tools/probe_peruser_views.py      # 两个注册表里各有哪些文件夹类型带着 TopViews 视图
python tools/probe_bag_colinfo_layout.py # 用户自己保存过的文件夹视图（Bags）里有没有列定义
```

> 第一个探针给出的是“现状”，第二、三个是用来排除错误方案的：结果是 HKCU 里
> 一个文件夹类型视图都没有（所以我们的用户级副本是新增的一组键，不覆盖任何东西），
> 而 Bags 里 3686 个视图键中 **0 个**有 `ColInfo` 以外的列定义——也就是说用户自己
> 调过的列布局是二进制块，没有可写的字段名，所以“改每一个已存在的文件夹”这条路走不通，
> 只能改文件夹类型的默认视图。这正是 v1.11 的做法。

---

## 目录结构

```
FileRemarks/
├── src/
│   ├── FileRemarksPropHandler.cpp  # “备注”列属性处理器（Shell 扩展 DLL，含包一层的转发逻辑）
│   ├── FileRemarksShellExt.cpp     # 右键“编辑备注”菜单（Shell 扩展 DLL）
│   ├── FileRemarksEditor.cpp       # 编辑备注的小对话框程序（无按钮，自动保存）
│   ├── selfext.cpp                 # 单文件安装器/卸载器（原生，无 .bat）
│   ├── logo.h                      # 软件图标（运行时画出来，无资源编译器）
│   ├── shell_columns.h             # 安装时默认打开“备注”列 / 卸载时还原
│   ├── remark_io.h                 # 共用：ADS 读写（UTF-8）
│   ├── native_comment.h            # 共用：读写 System.Comment（Office/图片类型用）
│   ├── remark.h                    # 共用：CLSID / 流名
│   ├── selftest_extract.cpp        # 仅测试用：包装真实 ExtractPayload
│   ├── selftest_install.cpp        # 仅测试用：包装真实 InstallFile
│   ├── selftest_native.cpp         # 仅测试用：包装 native_comment.h
│   ├── selftest_columns.cpp        # 仅测试用：包装 shell_columns.h
│   ├── selftest_installer_ui.cpp   # 仅测试用：驱动安装窗口（installer_ui.h）
│   ├── theme.h                     # Win11 外观：配色 / 字体 / 圆角 / DWM 圆角窗口
│   ├── installer_ui.h              # 安装窗口（显示已装版本 vs 目标版本）
│   └── test_prop.cpp               # 存储逻辑自检
├── tools/
│   ├── build_mingw.sh              # MinGW 一键构建（含安装器打包）
│   ├── build_installer.py          # 把组件打包进 selfext 生成 Setup.exe
│   ├── build_msvc.bat              # MSVC 构建脚本
│   ├── check_logo.py               # 图标形状断言
│   ├── preview_logo.py             # 把图标画成 PNG 便于肉眼对比
│   ├── test_*.py                   # 上面那十五个验证脚本 + 五个回归探针
│   ├── fake_dataobject.py          # 仅测试用：手搓 IDataObject(CF_HDROP)
│   ├── test_no_delay.py            # 保存后“备注”列立刻可见
│   └── mingw64/                    # 便携 MinGW 工具链（仅本地构建用，不入库）
├── dist/                           # 可直接分发的成品（当前版本的 3 个文件）
│   └── releases/                   # 按版本归档的安装包，历史版本全部保留
│       ├── FileRemarks_Setup_v1.7.exe
│       ├── FileRemarks_Setup_v1.8.exe
│       ├── FileRemarks_Setup_v1.9.exe
│       ├── FileRemarks_Setup_v1.10.exe
│       ├── FileRemarks_Setup_v1.11.exe
│       ├── FileRemarks_Setup_v1.12.exe
│       └── FileRemarks_Setup_v1.13.exe
└── build/                          # 编译中间产物
```

---

## 更新记录

**v1.13**

- **新增 `Ctrl+Alt+E` 快捷键**：在资源管理器里选中一个文件，按 `Ctrl+Alt+E` 直接弹出备注窗口。
  资源管理器没有“给右键菜单加自定义快捷键”的接口，所以由一个常驻小进程
  `FileRemarksHotkey.exe` 用 `RegisterHotKey` 注册这一个组合键（不是键盘钩子，不抢单键），
  收到 `WM_HOTKEY` 后经 `IShellWindows → IServiceProvider/SID_STopLevelBrowser →
  IShellBrowser::QueryActiveShellView → IFolderView2::GetSelection →
  IShellItem::GetDisplayName(SIGDN_FILESYSPATH)` 拿到“当前前台窗口里选中的那一个文件”，
  再用 `CreateProcessW` 起编辑器。没选中、选中多个（只取第一个，仍然一次只改一个文件）、
  或者选中的是虚拟项，都直接无视。单实例由 `FileRemarksHotkeySingleton` 互斥体保证；
  `WM_CLOSE` 退出，所以卸载时能干净停掉。安装时装成 4 文件、写 `HKCU\...\Run` 自启、立即启动；
  卸载时先停进程再删自启项。
- **修掉一个“看起来能用、其实列一直是空”的核心 bug**：属性处理器原先只实现
  `IInitializeWithItem` / `IInitializeWithFile`。Windows 在创建属性存储时**还会要
  `IInitializeWithStream`**，要不到就让整个 store 创建失败（`0x80004002`
  `E_NOINTERFACE`），于是资源管理器里“备注”列永远是空的——注册表看起来一切正常，
  也没有任何报错。现在补上了这个接口（把流里的名字还原成路径，下游逻辑不变）。
  `tools/probe_stream_init.py` 直接加载 DLL 走一遍这条路；同一脚本对 v1.12 的 DLL
  会红在“没有 `IInitializeWithStream`”，对 v1.13 通过。
- **“备注列到底显示了什么”现在可以端到端验证**：`tools/check_install.py` 末尾会造一个带备注的
  文件，然后用 `Shell.Application` 的 `GetDetailsOf` 去读“备注”这一列——这正是资源管理器读列的
  同一条路。v1.12 的安装上它明确打印“the column is EMPTY”；装 v1.13 后应当是“the column works”。
- **诊断日志**：属性处理器每次进程首次被“流初始化”时，把 Windows 传来的名字写到
  `%TEMP%\FileRemarks_propdiag.log`（`stream init name=… relative=yes/no`）。这条日志决定了
  还能不能找到备注（备注存在 ADS 里，必须知道完整路径），以后不用猜。

**v1.12**

- **备注框支持全选和整段删除**：一个普通 `EDIT` 控件从来没有实现过 Ctrl+A（记事本的“全选”来自它自己的
  加速键表），所以以前按 Ctrl+A 什么都不会发生，想把整段备注清掉只能按住退格。现在在控件的子类里自己处理
  `WM_KEYDOWN` 与 `WM_CHAR` 两条路径（`TranslateMessage` 会把 Ctrl+A 变成字符 1、把 Ctrl+Backspace
  变成字符 127），`Ctrl+A` 走 `EM_SETSEL 0..-1` 全选，`Ctrl+Backspace` 删掉光标前一个词（有选中时
  直接删掉选中的部分）。两条路径都处理是有意的：真实键盘走键盘消息，自动化或某些输入法走字符消息，
  这样哪个入口都不会漏。
- 新增 `tools/probe_select_all.py` 做回归：对着已安装的旧版编辑器 4 条全红，对着新版本全绿。
- **归档修复**：v1.11 的安装包在同一次会话里被 v1.12 的构建覆盖过一次（构建脚本按版本号命名，
  而当时版本号还是 1.11）。已用“回退掉 Ctrl+A 改动”的源码重新构建了一份 v1.11，补回
  `dist/releases/FileRemarks_Setup_v1.11.exe`；行为与首发 v1.11 一致，只是 sha256 与首发那次不同
  （`667ecce3…` vs 首发 `9F5E4D85…`）。v1.12 及以后每次构建都会写成独立文件名的归档，不会再互相覆盖。

**v1.11**

- **“备注”列改成“真的会自动打开”**：之前只有 Music / Videos 两种文件夹类型能加上这一列，
  其余四种（Generic / Documents / Pictures / Downloads）一直加不上，但安装完成时照样提示“列已经
  默认打开”。原因是机器级的视图键只有这两种允许 `Administrators` 写入（其余只有 `ReadKey`），
  提权也写不进去。现在改成写**当前用户自己的视图副本**：把 HKLM 里那份默认视图整份复制到
  `HKCU\...\Explorer\FolderTypes\<类型>\TopViews\{00000000-...}`，再在副本的 `ColumnList`
  末尾追加 `;0System.Comment`。整份复制是必须的——每个用户键不会被逐值合并，只写 `ColumnList`
  会让文件夹丢掉布局模式、排序和图标尺寸；而基准始终取自 HKLM，所以重复安装不会把这一列加两遍。
- **不再假报成功**：安装完成时会调用属性处理器新导出的 `FileRemarksColumnCount()`，把
  “现在到底有几种文件夹类型显示着备注”从注册表里读回来，再按真实数量说三种话
  （全部打开 / 打开了几种、其余可手动添加 / 没能自动打开、请右键列标题手动勾选）。
- 卸载时会整份删掉这个用户级视图（按备份存在与否判断“这份副本是我们建的”），让 Windows
  自己的默认视图重新生效，不留任何钉住的旧值。
- 新增 `tools/test_columns_autoenable.py` 覆盖这套逻辑；`probe_folder_types.py`、
  `probe_peruser_views.py`、`probe_bag_colinfo_layout.py` 是当时用来定位的只读探针。

**v1.10**

- **安装窗口的按钮不再闪**：以前父窗口收到**每一条** `WM_MOUSEMOVE` 都 `InvalidateRect` 自己，而父窗口没有 `WS_CLIPCHILDREN`，于是它每次重绘都会把页面底色整片刷到按钮上，肉眼看就是鼠标一动按钮就闪。现在父窗口不再因为鼠标移动而重绘，按钮只在“进入/离开”真正翻转时重绘自己（悬停状态存在窗口属性里，不占用 `GWLP_USERDATA`）；另外父窗口补上 `WS_CLIPCHILDREN`、`WM_PAINT` 只 blit `ps.rcPaint` 这块。
- **删掉的备注文字不再留在框里**：备注框是多行 `EDIT`，它擦除重绘区域的方式是“用 `WM_CTLCOLOREDIT` 给的 DC 把文字重画一遍”。之前那个 DC 被设成 `TRANSPARENT`，背景压根没填，于是删掉的字虽然已经从值里没了（所以选不中），像素却还留在屏幕上。现在备注框的 DC 改成 `OPAQUE` + 背景色等于卡片白，删掉的字当场被盖掉；状态行仍用 `TRANSPARENT`。
- 新增两个能单独复现这两个 bug 的回归探针：`tools/probe_stale_text.py`、`tools/probe_button_flicker.py`（见上面的“小探针”一节）。

**v1.9**

- **不再申请管理员权限，SmartScreen 的“发行者未知”提示随之消失**：v1.8 及更早的安装器会用
  `runas` 自提权，而 SmartScreen 只在**未签名的可执行文件申请提权**时才做信誉检查、弹那个
  “Windows 已保护你的电脑 / 发行者未知”。实测确认提权就是触发条件（同一批未签名程序，
  申请提权的一组出现过该提示，不提权的一组 7 次里 0 次）。
  现在**一次提权都不申请**：装到 `%LOCALAPPDATA%\FileRemarks`，卸载项、右键菜单、
  属性处理器、默认列全部写 `HKCU`（`HKCU\Software\Classes` 并入 `HKCR`，资源管理器照认），
  于是没有 UAC、没有该提示，也不需要买代码签名证书。
- **卸载会自动收尾**：从 v1.8 及更早版本升级时，旧的 `C:\Program Files\FileRemarks` 只作残留，
  新安装器在卸载时会顺手尝试清理它（无权限就跳过，不影响结果）。
- 安装窗口的说明文字改为“安装在当前用户目录下，不需要管理员权限”。

**v1.8**

- **安装包按版本号归档**：从这一版起安装包叫 `FileRemarks_Setup_v<版本号>.exe`，放在
  `dist/releases/` 下，**构建时只替换同版本文件、从不删除历史版本**，
  所以任何时候都能找回并重装旧版（v1.7 已归档）。
- **提示语输入后真的消失**：空备注框里的 `在这输入备注...` 是画在控件上的，而 EDIT 控件
  插入一个字符时只重绘该字符周围那一小块，于是提示语右半边会留在屏幕上、和刚打的字叠在一起。
  现在只要“空 / 非空”状态发生变化（`WM_CHAR`、`WM_KEYDOWN`、粘贴、剪切、清空、撤销、`WM_SETTEXT`）
  就重绘整个控件，第一个字符落下时提示语即被擦掉，清空后又会长回来。

**v1.7**

- **界面按需求做得更简约**：编辑窗口里不再有“文件”和“备注”这两个标签——
  文件路径直接贴在软件图标右侧（省掉一整行和左侧一列），备注框上面那行“备注”也去掉了。
- **文件名不再被截断**：以前用 `DrawTextW(DT_WORDBREAK)` 估算路径高度，但 `DT_WORDBREAK`
  只在空格处折行、路径里没有空格，于是估算出的行数比实际少，最后一行被切掉。
  现在改成**按字符折行**（`GetTextExtentExPointW` 逐字量）估算；窗口建好后再用
  `EM_GETLINECOUNT` / `EM_GETRECT` 复核一次：装不下就补高度并重排窗口，最多迭代 6 次。
  163 字符的长路径实测 4 行全显示（`needed=4 capacity=4`）。
- **空备注框显示提示语**：框里没字时用灰色画一行 `在这输入备注...`，一输入内容就盖掉；
  提示语只画在控件表面，**不会**写进备注、也不会被保存（输入后如何擦掉见 v1.8）。

**v1.6**

- 编辑窗口**按内容自适应大小**：文件路径先测量换行高度，文件卡片、备注卡片和窗口高度都
  跟着实际文字走。长路径会折行显示完整，不会被固定的两行高度裁掉；窗口底部也不再留一条空白。
- 安装窗口三个 UI 问题修掉：
  - **按钮文字不再有白底块**：自绘按钮的设备上下文默认是 OPAQUE 背景，画文字时会先垫一块白；
    现在统一强制 TRANSPARENT 背景模式，蓝底按钮上的白字干干净净。
  - **去掉“取消”按钮**：只留“安装/重新安装”和“卸载”两个动作；不想操作直接关窗口或按 `Esc`。
  - **提示信息不再被裁切**：说明卡片的高度改为按文字实际换行结果测量（`DT_CALCRECT`），
    窗口高度跟着内容走，任何 DPI、任何文案长度都不会截断最后一行。

**v1.5**

- 界面上**去掉了“文件备注”这几个字**：编辑窗口只留软件图标、窗口标题就叫“备注”，
  安装窗口标题就是 `FileRemarks`，“设置 → 应用”里的名字也简化成 `FileRemarks`。
- 修掉“**界面里更新的内容有延迟**”：
  - 保存后立刻用 `SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_FLUSH, 文件路径)` 通知资源管理器重新读这一项，
    再对所在文件夹补一次 `SHCNE_UPDATEDIR`，不用手动按 F5 才能看到新备注；
  - 保存前先把状态栏刷成“正在保存…”，避免写 Office 元数据时窗口看起来像卡住；
  - 编辑窗口加 `WS_CLIPCHILDREN`，父窗口重绘不再盖住子控件造成闪烁。

**v1.4**

- 安装窗口改成 Win11 风格（圆角窗口、卡片式布局、Segoe UI、蓝底主按钮），
  并且**明确显示“当前已安装版本”和“要安装的版本”**：没装过显示“未安装”，
  从旧版本升上来时如实显示“旧版本（未记录版本号）”（老版本把版本号写成了占位符 `1.0`，不能当真）。
- 编辑窗口重做成 Win11 风格：卡片式输入区、聚焦时描蓝边、顶部软件图标，窗口圆角。
- 明确并加固“**失焦只保存、不关窗**”：切到别的窗口只写盘、窗口原地不动；
  只有 `Esc` / `Ctrl+Enter` / 点关闭按钮才会关窗（关窗前同样先保存）。
- 安装器开始写真实的版本号（`DisplayVersion` / `VersionMajor` / `DisplayIcon`），
  以后升级时“当前已安装版本”就能显示准确值。

**v1.3**

- 右键菜单“编辑备注”前面加了软件图标（`src/logo.h` 运行时绘制，无外部图片文件）。
- 安装后资源管理器**默认就显示“备注”列**，不需要手动勾选；卸载时把默认视图还原成安装前的样子。
- 编辑窗口**去掉“保存 / 清空 / 关闭”三个按钮**：关窗口或切到别的窗口都会自动保存；
  只有内容真的变了才写文件；`Esc` / `Ctrl+Enter` 可直接关闭。

**v1.2**

- 修掉“覆盖安装时文件正被使用”的失败（`错误码 0x32`）：自动把占用的旧 DLL 改名腾位，
  旧副本排到下次重启删除，所以覆盖安装不用先关资源管理器。

---

## 已知限制 / 取舍

- 仅 NTFS 分区（ADS 是 NTFS 特性）；FAT/exFAT/U 盘上备注无法保存。
- 备注不随**跨盘拷贝 / 打包成 zip / 上传下载 / 云同步**迁移（ADS 特性）。同盘改名、移动不受影响。
  - 例外：Office 文档的备注同时写进了文件内部元数据，所以这类文件**复制也会带着备注**。
- 极少数文件类型（如 `.mp3` 的某些编码）写 `System.Comment` 会被拒绝，此时只有 ADS 里有备注；
  “编辑备注”照样能看能改。
- 每次只处理一个文件（按需求，无批量）。
