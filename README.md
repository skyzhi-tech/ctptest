# ctptest｜CTP 程序化交易测试工具 · 基于易行量化 exsdk

ctptest 是基于易行量化 exsdk 开发的开源 CTP 程序化交易测试工具，提供 Windows 图形界面，支持开平撤单、连接监测、柜台错误核验及日志展示，辅助期货公司程序化交易测试验收。

**[获取 exsdk Token](https://skyzhi.com/login?utm_source=github&utm_medium=readme&utm_campaign=ctptest&utm_content=token)** · [ctptest 快速开始](docs/quickstart.md) · [exsdk 快速开始](https://skyzhi.com/docs/quickstart?utm_source=github&utm_medium=readme&utm_campaign=ctptest&utm_content=quickstart)

使用流程：**选择测试点 → 点击开始 → 查看真实回报 → 使用系统工具截图**。运行需要 exsdk Token 和可用的 CTP 测试账号。

ctptest is an open-source Python CTP testing tool for futures trading. Built with exsdk, it provides a Windows GUI for order tests, connection monitoring, counter error checks, and execution logs.

## 适合谁使用

- 需要整理程序化交易测试证据的期货公司测试人员。
- 使用 Python 接入 CTP、需要核对开平撤单与柜台错误的开发者。
- 希望通过实际工具了解易行量化 exsdk 交易接口的使用者。

## 支持哪些测试

| 类别 | 能力 |
| --- | --- |
| 认证与连接 | 登录同步核对、连接成功、真实断线及恢复监测 |
| CTP 开平撤单 | 买开／卖开各一手，直接卖平／买平各一手，单笔撤单 |
| 统计与控制 | 报撤单计数、阈值预警、暂停与恢复交易入口 |
| 指令与柜台错误 | 合约／价位／手数本地拦截，资金不足、持仓不足、市场状态错误核验 |
| 登录参数检查 | UserID 空值／空白、ASCII 控制字符、特殊符号及超长输入的客户端拦截 |
| 接入安全性 | 默认每秒一笔、持续 6 分钟报单，核对逐笔回报与实际频率 |
| 测试证据 | 交易、系统、监测与错误日志，CTP 相关字段及上海时间 |

共内置 **29 个测试点**，完整操作、条件及截图要求见 [CTP 程序化交易测试指南](docs/ctp-testing.md)。

## 快速运行

当前桌面使用环境为 **Windows x64、Python 3.14（含 Tkinter）**。请先下载或克隆本仓库，在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\ctptest.exe
```

1. 前往易行量化官网 [获取 exsdk Token](https://skyzhi.com/login?utm_source=github&utm_medium=readme&utm_campaign=ctptest&utm_content=token)，并准备期货公司提供的测试账号与接入参数。
2. 在“配置”中填写账号、Token、交易前置、主合约及买入价／卖出价，保存后点击“连接”。
3. 等到底部显示“已连接”，选择测试点并点击“开始”。选择列表项目本身不会下单。

详细环境、字段及更新方法见 [快速开始](docs/quickstart.md)。exsdk 不限定版本，更新后重启工具。

## 测试范围与准备

- 使用专用模拟或仿真账号；执行交易测试会向柜台发送真实请求。
- 普通开平仓买卖各一笔、每笔一手；平仓直接使用账号现有可平持仓。资金不足测试默认 100 手，可在配置中调整。
- 买卖价格由用户设置。ctptest 不订阅行情，不根据盘口或涨跌停自动改价。
- “通过”须有对应本地拦截证据或真实柜台回报；即时 `SUBMITTED` 仅表示提交，超时和 `UNKNOWN` 不自动重发。
- 停止、退出和断开不会自动平掉账号持仓或撤销全部委托；辅助单清理与主委托的区别见测试指南。
- 每次重开工具清空上次测试记录；验收截图和日志应在退出前另行留存。对外分享时脱敏完整账号及其他身份信息。

重复报单、批量撤单等选测未实现。具体测试项目与证据要求应以接收测试材料的期货公司要求为准，本工具不代表已获得认证或已通过验收。

## 关于易行量化 exsdk

[易行量化 exsdk](https://skyzhi.com/?utm_source=github&utm_medium=readme&utm_campaign=ctptest&utm_content=overview) 是提供合约查询、实时行情、期货 K 线和本地直连 CTP 交易的 Python SDK。ctptest 使用其中的合约信息和交易接口，本工具本身不依赖行情。

通过 ctptest 熟悉交易回报后，可继续阅读 [exsdk 交易接入文档](https://skyzhi.com/docs/trading?utm_source=github&utm_medium=readme&utm_campaign=ctptest&utm_content=trading)，了解如何在自己的 Python 程序中使用 SDK。

## 文档与常见问题

- [快速开始](docs/quickstart.md)：安装、Token、配置与首次测试。
- [CTP 程序化交易测试指南](docs/ctp-testing.md)：29 个测试点、前置条件及截图证据。
- [常见错误与 SDK 边界](docs/troubleshooting.md)：本地拒绝、柜台错误码、等待回报及 SDK 限制。
- [真实柜台验收检查表](ACCEPTANCE.md)：逐项记录实际验收情况。

## 参与贡献

欢迎在 [GitHub Issues](https://github.com/skyzhi-tech/ctptest/issues) 反馈问题或提交 Pull Request。请说明系统、Python／exsdk 版本、复现步骤和脱敏后的相关回报，不要上传密码、Token、AuthCode、账号配置或原始数据库。

修改交易流程时，应使用 SDK 替身和模拟时钟验证登录参数检查、持续报单、停止与失败路径、计数恢复及 GUI 响应，再在专用仿真环境核对真实回报。当前仓库不包含可直接运行的自动化测试套件；模拟时钟中的 6 分钟不能作为真实持续报单验收证据。替身结果与真实柜台验收分别记录。

仓库管理员可参考 [开源发布与 GitHub About 设置](docs/publishing.md) 完成项目展示。

## 许可证

ctptest 采用 [MIT 许可证](LICENSE)，Copyright (c) 2026 skyzhi-tech。exsdk 的使用条款、Token 及账号要求由易行量化另行规定，不因 ctptest 开源而改变。

[易行量化官网](https://skyzhi.com/?utm_source=github&utm_medium=readme&utm_campaign=ctptest&utm_content=overview) · [获取 exsdk Token](https://skyzhi.com/login?utm_source=github&utm_medium=readme&utm_campaign=ctptest&utm_content=token) · [exsdk 文档](https://skyzhi.com/docs/overview?utm_source=github&utm_medium=readme&utm_campaign=ctptest&utm_content=docs)
