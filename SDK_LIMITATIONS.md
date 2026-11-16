# exsdk 接入限制与建议修改

当前公开说明已整理到 [常见错误与 SDK 边界](docs/troubleshooting.md)，原有文件名保留以兼容已有链接。安装与 Token 配置见 [快速开始](docs/quickstart.md)，29 个测试点及判定见 [CTP 程序化交易测试指南](docs/ctp-testing.md)。

## 当前适配边界

- exsdk 不限定版本，更新后应重新验证目标柜台场景；历史测试结果不代表新版本已通过验收。
- 即时拒绝保留 `TradingResult.message`，柜台状态和拒单保留 `Order.status_msg`，撤单失败保留 `Order.cancel_error`。文本中明确标注的错误码按原文识别，不根据原因猜测码值。
- 超量平仓若被 SDK 提前拦截，不能算柜台持仓不足通过；专用验收场景需要 SDK 公开提供相应请求能力，工具不使用私有接口绕过检查。
- 当前通过持续快照更新接入，不承诺捕获每一次原始 CTP 回调；逐条回调审计需要 SDK 提供有序事件能力。
- 普通报单使用用户买卖价格，不读取行情；指令检查测试需要真实静态合约规则。
- 登录非法输入测试选择 UserID，使用 ctptest 实际登录入口的共用校验。没有发送非法登录，不要求 SDK 提供原始 ReqUserLogin；不把本地拦截写成柜台拒绝。
- 持续报单使用公开 insert_order 接口；频率不足、即时拒绝、未知发送或回报超时按实际记录，不以补单或模拟回报冒充达标。已开始的 SDK 同步调用须等待返回，停止会阻止后续步骤。

字段与约定参见 [exsdk 错误处理](https://skyzhi.com/docs/errors?utm_source=github&utm_medium=docs&utm_campaign=ctptest&utm_content=errors)、[订单文档](https://skyzhi.com/docs/orders?utm_source=github&utm_medium=docs&utm_campaign=ctptest&utm_content=orders) 和 [数据参考](https://skyzhi.com/docs/data-reference?utm_source=github&utm_medium=docs&utm_campaign=ctptest&utm_content=data-reference)。

## 历史现象

早期 exsdk 1.7 运行曾出现“持仓查询包含 SDK 不支持的合约类别”。此记录仅用于排查同类问题，不能据此判断当前版本是否仍受影响；实际处理方法见 [历史现象与当前版本分开核对](docs/troubleshooting.md#历史现象与当前版本分开核对)。

原文中的本机 wheel 路径、旧安装要求及无法在当前仓库复现的测试通过数量不再作为公开接入依据。真实柜台验收请逐项记录于 [验收检查表](ACCEPTANCE.md)。
