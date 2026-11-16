# ctptest 快速开始：配置 exsdk 与 CTP 测试账号

[项目首页](../README.md) · [CTP 程序化交易测试指南](ctp-testing.md) · [常见错误与 SDK 边界](troubleshooting.md)

本篇介绍从安装到首次测试的流程。ctptest 是基于易行量化 exsdk 的 Windows 桌面工具，日常操作通过图形界面完成。

## 准备环境与 Token

- Windows x64、Python 3.14，安装 Python 时保留 Tcl/Tk 支持。项目元数据的 Python 下限为 3.12，但当前桌面使用说明按 3.14 编写；其他版本需确认 exsdk 提供兼容安装包。
- 前往官网 [获取 exsdk Token](https://skyzhi.com/login?utm_source=github&utm_medium=docs&utm_campaign=ctptest&utm_content=token)，按官网要求配置权益及绑定账号。
- 准备期货公司提供的模拟或仿真账号、交易前置地址、BrokerID、AppID 和 AuthCode。
- 准备有效期货合约及买入价／卖出价。交易测试会发送真实请求，请使用专用测试环境。

## 安装并启动

克隆项目并在项目根目录执行：

```powershell
git clone https://github.com/skyzhi-tech/ctptest.git
cd ctptest
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\ctptest.exe
```

安装完成后直接启动 `.venv\Scripts\ctptest.exe`。也可运行 `.\.venv\Scripts\python.exe -m ctptest`，两者打开同一个 GUI。

## 配置账号与测试场景

点击“配置”，在“账号与连接”页填写：

| 字段 | 来源与用途 |
| --- | --- |
| 测试环境 | 自定义显示名称，例如“仿真期货” |
| 交易前置地址 | 期货公司提供的 `tcp://地址:端口` |
| BrokerID、UserID、Password | 期货公司代码、资金账号及交易密码 |
| AppID、AuthCode | 期货公司提供的应用认证参数 |
| exsdk Token | 从易行量化官网获取 |

在“测试场景”页填写主合约（`交易所.合约`）、买入价、卖出价与资金不足委托手数。普通开平仓每笔一手；资金不足测试默认 100 手，需按目标场景调整。“测试参数”中可设置回报等待期限，默认 60 秒。

合约和价格由用户确定；ctptest 不读取行情，不自动偏移、取整或调整报价。没有填写价格时仍可先做认证登录和本地指令检查。

不必复制 [配置样例](../config.example.toml) 才能启动。默认配置位于 `%LOCALAPPDATA%\ctptest\config.toml`，密码、Token、AuthCode 保存在 Windows 凭据管理器，TOML 仅保存凭据引用。日志默认位于配置目录的 `data` 子目录。

## 连接与首次测试

1. 保存配置后点击主窗口“连接”；连接、登录及同步进度显示在底部。
2. 底部显示“已连接”、SDK 为 `READY` 且交易日已取得后，才可开始测试。已有配置的后续启动会自动尝试连接。
3. 从左侧选择“认证登录”，点击“开始”，查看账号、交易前置、交易日及资金快照等核对记录。
4. 按 [测试指南](ctp-testing.md) 准备对应条件，再运行交易或异常场景测试。

选择测试点仅查看内容，不会自动下单。“开始／停止”控制当前前台执行步骤。开平仓与柜台错误测试提交后恢复“开始”，回报在后台按原委托更新；恢复“开始”不代表已成交或已通过。

## 保存证据与修改参数

结果日志使用上海时间，并展示实际取得的 `OrderRef`、`OrderSysID`、`TradeID`、价格数量、状态及错误原文。使用系统截图工具留存，截图要求见 [证据说明](ctp-testing.md#截图与证据保存)。

主合约、买卖价格、资金不足手数、等待期限等参数保存并由交易线程确认后供下次测试使用，无需重连。账号、认证凭据、前置地址、环境或日志目录改变后，需要断开再连接。

同一次应用运行中重连保留记录；重开工具会清空上次测试记录、计数、阈值和暂停状态。请在退出前另行保存截图及所需日志；账号配置保留。界面显示完整账号，对外分享材料前请脱敏。

停止不撤销全部委托；退出或断开不自动平仓。仅明确创建为辅助用途且已确认可撤的委托参与自动清理，详见 [委托与停止规则](ctp-testing.md#委托与停止规则)。

## 更新 exsdk

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade exsdk
```

更新后重启 ctptest。项目不限定 exsdk 版本，使用包源中兼容当前 Python 的最新正式版本。若接入失败，按 [常见错误](troubleshooting.md) 保留版本及原始回报再核对。

继续了解 [exsdk 快速开始](https://skyzhi.com/docs/quickstart?utm_source=github&utm_medium=docs&utm_campaign=ctptest&utm_content=quickstart) 与 [交易接入文档](https://skyzhi.com/docs/trading?utm_source=github&utm_medium=docs&utm_campaign=ctptest&utm_content=trading)。
