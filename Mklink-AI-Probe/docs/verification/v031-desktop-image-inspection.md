# 0.3.1 安装版在线文件检查并发修复

2026-10-09 用户覆盖安装候选 `72962eda` 后报告：RTT/SuperWatch运行时，
选择HEX显示 `Another shared operation or exclusive job is active`，无法开始烧录。
这重新打开本轮验收；此前分项通过不能代表原生文件选择入口完整覆盖。

## 复现与原因

核对已安装桌面/sidecar哈希，分别与旧候选的 `76ac37d3…`、`a8a576c7…` 相同。
直接读取原生窗口确认错误、空预览和禁用烧录按钮。SuperWatch最初正在最快设置运行。
再次用原生文件对话框选择同一HEX可成功，故非“采集运行时必然拒绝”。
通过同一安装后台同时提交三次本地文件检查，得到两个409、一个200；该次采集已停止，
说明本地检查之间也会互相排斥。后台前一次检查200记录与界面遗留失败提示均已确认。

共享入口原先把全部POST归类为硬件操作。本地BIN/HEX解析、快照缓存及FLM扇区检查
不访问探针，却获取设备操作锁；前次请求在后台处理时，后续检查或硬件操作被拒绝。
前端取消或替换检查后，旧请求的迟到异常还可能覆盖最新成功结果。

## 修复与验证

- 仅两条本地镜像检查POST移出硬件互斥；仍经过认证、同源和后台停止检查，
  镜像解析自身保留线程安全快照缓存。烧录/读写/维护等操作的互斥保持。
- 前端仅允许当前检查请求更新错误，忽略已取消或被替代请求的迟到异常。
- 新增两个入口在已有操作/任务和RTT+Watch状态下可解析、认证仍拒绝、硬件访问仍拒绝的测试。
- 新增旧桌面检查返回409晚于新检查成功的界面回归。
- 后端相关192通过，在线页面118通过。首次扩大测试未绑定既有算法资产，
  一个安全流程测试失败；绑定既有 `MKLINK_BUILTIN_FLM_ROOT` 后完整192项通过。

修复源码 `acdcc997`，生产资源 `d89c0827`；该资源提交三项 CI 全通过。
TypeScript/Vite、PyInstaller、Tauri/NSIS生产构建通过，内置7059目标/2224算法。

## 冻结包及原生桌面补验

新包 `Mklink-0.3.1-acdcc997-local-setup.exe`，96805356字节，SHA-256
`5f2858333155e541a40c850fec97e0e05e27c33638d05337880983b13f975780`。
包内桌面SHA-256 `058bb70ed950318c6e25d35cae75fb23df6e0f2f3ce2ae7a6a88026115e9997e`，
sidecar `58f2b338f7f672e616a1d6619c4c79e59d3f33b2d11ab4368ff93fca75793192`。
三负载及安装包完整清单见本地 `manifest.json`。

- Windows-only PATH下真实冻结MCP/CLI及lobby启动通过，启动5.44秒，正常退出删除endpoint。
- 使用新NSIS提取的原生桌面与sidecar连接V4.6.3/F103RE；先备份512KiB，
  确认已知HEX每个段均与目标当前程序相同，没有改变VCC。
- SuperWatch单独运行、RTT8单独运行、两者同时运行三种状态，各四个并发请求，
  交替multipart上传和本地路径检查，12次全部200且快照ID独立；采集持续运行。
- RTT8与单变量Watch（请求1µs）同时运行时，实际点击原生“选择BIN/HEX”、
  文件对话框输入已核对的HEX，预览/扇区/FLM检查完成，烧录按钮可用。
- 实际点击开始烧录，连接/擦除/编程/校验/复位/断开全部成功，任务用时10.73秒。
  后台任务回执确认RTT与SuperWatch自动暂停、恢复，恢复错误为空；
  Watch读周期及RTT计数继续增长。原生页面显示100%及succeeded。
- 停采集后，以10MHz分块读回整个512KiB，与本次烧录前备份逐字节相同，SHA-256
  `40aab8a117e7db22dfeffd13a2a592ab596bdd28a66fcd4a26443d2e72548732`。
- 原生关闭按钮退出后，桌面和后台进程结束、endpoint删除，命令口可再次打开关闭。

证据包括 `frozen-smoke.json`、`installed-before.json`、`new-desktop-prepare.json`、
`new-desktop-inspect.json`、`new-desktop-burn.json`、`native-burn-complete.jpg/txt`、
`new-desktop-final.json` 和 `new-desktop-release.json`。

## 安装态与读回限制

实际覆盖安装尝试被Windows以WinError740拒绝；已向用户提供新包并请求人工安装，
截至记录时未收到安装完成回复，安装目录sidecar仍为旧候选哈希。
上述新版本真机结果来自新包的原生提取程序，不能称为新包已覆盖安装验证。
历史UAC豁免不改变这个证据边界。旧候选完整4566 Python/911 GUI通过记录
不等于本次新代码重跑全套；本次相关回归为192 Python/118 GUI，正式发布仍需精确tip门槛。

另发现原采集连接的30MHz SWD下，大块内存读偶发返回`Multiplex target status 5`；
4096B与1024B块均遇到，16B短读通过。在线烧录使用10MHz并校验成功；
临时设置medium/10MHz且`save:false`后，4096B块整片读回通过。
没有保存时钟修改；已将30MHz现象交给固件会话进行源码核查。
暂不能将其归因于已修复的本地文件检查互斥，也不能宣称30MHz大块读取已修复。

本地证据保存在主工作区 `.build/artifacts/v031-inspection-fix/`，不提交设备身份、原程序或令牌。
