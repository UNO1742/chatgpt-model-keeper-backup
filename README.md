# ChatGPT 模型锁定器

Windows 上的小型悬浮工具，为 **Chat / 聊天**和 **Work / 工作**分别保存模型与思考程度，并通过 Edge 扩展检测和纠正网页选择。

> 本仓库是备份／接续版（`UNO1742/chatgpt-model-keeper-backup`）：从 v2.2.1 快照继续开发，安装包的更新检查与后续发布均以本仓库为准。

## 安装与更新

在 [GitHub Releases](https://github.com/UNO1742/chatgpt-model-keeper-backup/releases/latest) 下载 `ModelKeeper-Setup.exe`，安装后会显示可拖动的小圆球。点击圆球打开设置；设置中的“检查更新”读取本仓库的最新稳定 Release，下载后校验 GitHub 提供的 SHA-256，再运行安装程序。

- Windows 10/11 x64；安装针对当前用户，无需管理员权限。
- 首次安装默认登录自启；更新保留已有的开关选择。
- 首次需要从 ChatGPT 原始 CDN 下载约 9 MiB 的球体、原版界面 CSS、字体、原始滑条组件及其运行依赖；固定版本与 SHA-256 校验后缓存，后续可离线显示。
- 当前构建使用 Qt WebEngine 实时运行原始 Horizon 控制器，不使用预录动画或定时回放；保留原始时间推进、纹理和 WebGL 着色器。球体处于等待状态，不接入或采集麦克风音量。
- 安装包包含浏览器渲染引擎，体积较旧版增大。

## “浏览器扩展”是什么？

浏览器安全限制下，桌面程序需要配套扩展来操作普通网页标签页。**仅运行悬浮球并不能调整网页模型。**

设置中的“浏览器扩展”一行右侧是“安装”按钮：点击后本机程序把扩展打成已签名的 CRX，并写入当前用户的 Edge 外部扩展注册表项（`HKCU\Software\Microsoft\Edge\Extensions\<id>`）。**不需要开发者模式，不需要选择文件夹，也没有任何对话框。** 重启 Edge 后它会作为普通扩展出现并自动启用，按钮随即变为“卸载”。

- 签名密钥在首次部署时为本机生成（RSA 2048），保存为安装目录下的 `extension_key.json`；公钥写入扩展 `manifest.json`，扩展 ID 由它决定，本机消息白名单同步使用该 ID。公开源码和安装包不携带任何签名私钥。
- Edge 只在启动时扫描该注册表项，因此部署后需要重启一次浏览器。悬浮球右键菜单里有“重启 Edge（使扩展生效）”，也可以自己重启。
- 卸载会删掉注册表项，Edge 下次启动时移除该扩展；安装目录中的配置不受影响。
- 部分设备策略（`ExtensionInstallBlocklist`、`ExtensionSettings`）会阻止任何非商店扩展，此时需要管理员放行。

部署失败时（例如 PowerShell 被策略禁用），仍可用悬浮球右键菜单的“手动安装扩展…”走开发人员模式流程：

1. 点击“一键准备安装”。程序自动准备实际扩展文件夹、复制路径并打开 Edge 扩展管理页。
2. 开启开发人员模式，选择“加载解压缩的扩展”。
3. 在文件夹选择框中粘贴已复制的路径并选择，也可使用“复制路径”或“打开文件夹”。
4. 刷新 ChatGPT。连接后，设置中的状态会显示“已连接”。

已手动加载过旧版扩展的用户无需任何操作：本机消息白名单同时保留旧 ID 与新 ID，两者都能连接。

## 使用

点击圆球打开“额度助理”。按住标题区域可拖动设置框；点击框外会收起，悬浮球继续运行。聊天／工作切换条恢复圆角矩形滑块样式，分别设置模型与思考程度后点击“保存设置”。日间、夜间使用黑白主题与网页原来的蓝色强调色，切换后立即记住；滑条保留蓝色填充、已选范围内的浅色圆点和白色滑块。模型菜单按模式分开：聊天显示 GPT-6 和 GPT-5.6 Sol；工作显示 Sol / Astra / Luna / Terra 系列，不再混用一份清单。再次点击模型按钮、点击空白处或按 Esc 均可收起，支持方向键选择。

思考程度使用带圆点档位的滑条，也可点击档位文字或按方向键调整。聊天为“即时、轻度、中、高、极高”，工作为“轻度、中、高、极高”；没有 Pro 或 Ultra。中英文标签均适配，聊天网页内部 `max` 显示“极高”时会正确识别。旧配置中的 Max/Ultra/Minimal 等未保留档位会回到极高。

思考滑条直接运行网页的原始 PowerSlider 组件及其原始 React、Radix、Motion 依赖。程序仅通过一个导出桥接层暴露组件入口，不改写组件实现；给组件传入允许的档位和选中值，并接收选择事件。圆球定位、填充、圆点、指针拖动和弹簧动画全部由原组件处理，没有本地手写定位或透明 range 替代层。键盘和外侧档位文字通过组件的选中值接口连接。

模型菜单复用网页的原始 CSS 与结构；顶部聊天／工作切换条使用此前的圆角矩形滑块布局。程序补桌面布局、蓝色强调色变量和本地设置事件。原始组件、CSS 与字体只从源 CDN 获取和缓存，不打包进公开源码或安装包。仅运行独立滑条所需的通用依赖，不启动 ChatGPT 的账号或业务模块。

扩展约每 3 秒读取设置，等待用户空闲后检查当前可见页面；稳定情况下每 60 秒复核。用户输入、生成回复或打开菜单时会推迟。无法确认模式、模型不可用或档位不支持时会显示原因，不能解锁套餐权限。程序不会发送消息，也不会改变已发出的消息使用的模型。

## 数据与权限

配置、悬浮位置、状态、扩展签名密钥（`extension_key.json`）及图形资源缓存在本机安装目录。Native Messaging 接口只允许本仓库扩展的 ID（含手动加载时代的那一个）。扩展不上传聊天内容、Cookie 或浏览历史；更新检查不需要 GitHub 账户或 Token。

桌面渲染页面由仅绑定 `127.0.0.1` 的随机本地端口提供，使用随机路径、Host 校验和文件白名单；没有外部监听。该页面只承载本机 UI 和绘制资源，不加载 ChatGPT 登录页。浏览器与本机程序的模型控制仍走 Native Messaging。

原始图形资源不发布进本仓库或安装包，不适用本项目 MIT 许可证。来源和固定摘要见 `runtime_manifest.json`，组件说明见 [THIRD_PARTY.md](THIRD_PARTY.md)。本项目与 OpenAI 无隶属关系。

## 构建

需要 Windows x64、Python 3.13、Inno Setup 6/7。

```powershell
python -m pip install -r requirements-build.txt
./build.ps1 -InnoCompiler 'C:/Program Files (x86)/Inno Setup 6/ISCC.exe'
```

输出为 `release/ModelKeeper-Setup.exe` 和 `release/SHA256SUMS.txt`。Native Messaging 主机是单独的小型程序，不会每次连接都加载或解压浏览器引擎。

推送 `v*` 标签后，GitHub Actions 会构建并发布安装程序。发布版本号需要同步更新 `app.py` 与 `installer.iss`。

开发验证：`python -m unittest discover -s tests -p test_services.py`；网页适配验证需要安装 Playwright 与 Chromium 后运行 `python tests/test_adapter.py`。GUI 可用 `python app.py --gui-smoke <报告路径>` 验证实时绘制计数和截图。构建后，`python tests/test_installer.py` 在临时目录和独立 Edge 配置中验证安装、迁移、自启偏好、Native Messaging、中英文模式、实时渲染及卸载，并恢复原有注册信息。跨电脑验收仍需在另一台实体 Windows 设备执行。
