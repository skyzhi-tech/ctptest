# 开源发布与 GitHub About 设置

[项目首页](../README.md) · [快速开始](quickstart.md) · [CTP 测试指南](ctp-testing.md)

此清单供 `skyzhi-tech/ctptest` 仓库管理员应用。文件中的配置是待发布值，不表示已修改 GitHub 后台、推送代码或发布 Python 包。

## GitHub About 可复制设置

Description：

```text
基于易行量化 exsdk 的开源 CTP 程序化交易测试工具，提供 Windows GUI、开平撤单、柜台错误核验和日志展示。
```

Website：

```text
https://skyzhi.com
```

Topics（逐项添加）：

```text
ctp
ctp-api
ctp-test
futures
futures-trading
python
tkinter
trading-api
exsdk
quantitative-trading
algorithmic-trading
```

管理员在仓库 About 设置中保存上述内容，发布后确认公开页面显示项目描述、官网、Topics 和 MIT 许可证。Topics 名称、数量要求及操作见 [GitHub 官方说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)。

## 发布检查

- README 首屏显示工具定位、exsdk Token 要求、获取入口与快速开始。
- 文档相对链接在目标分支上有效；官网登录页和文档页可访问。
- 测试列表与当前实现一致，真实验收与替身检查分别描述，不宣传保证通过。
- 公开配置及截图无凭据、真实账号、资金、身份信息或本机绝对路径；不要提交运行日志或数据库。
- 构建 wheel 和源码包，检查 README、MIT 许可证、关键词及项目链接。源码包应包含公开文档和脱敏配置样例。
- MIT 只覆盖 ctptest 的相关授权；exsdk 使用要求由其自身条款确定。

当前桌面指南按 Windows x64／Python 3.14 编写。更新 SDK 或交易流程时同步更新文档；不要将未验证版本写成已通过真实柜台验收。

## 搜索展示与内容维护

主定位保持为“基于易行量化 exsdk 的开源 CTP 程序化交易测试工具”。README 承接工具搜索，教程回答配置与操作问题，错误指南回答实际拒单与 SDK 边界问题。

关键词自然放在标题、首段、章节与相关链接中，不添加隐藏文本、堆词或无关 Topics。GitHub 托管页面的 HTML 标题及索引由平台和搜索引擎处理，本仓库不添加假装控制 GitHub 页面头部的 meta 标签，也不保证排名。内容原则参考 [Google 搜索基础建议](https://developers.google.com/search/docs/essentials)。

## 引流链接与观察口径

公开 README 和教程指向易行量化的链接采用以下 UTM 约定；包元数据和 About Website 使用不带追踪参数的正式地址。

| 参数 | 取值 |
| --- | --- |
| `utm_source` | `github` |
| `utm_medium` | README 用 `readme`，教程用 `docs` |
| `utm_campaign` | `ctptest` |
| `utm_content` | Token 用 `token`，快速开始用 `quickstart`，其他文档用对应主题，如 `trading`、`errors`、`orders` |

主要入口指向官网 `/login`，辅助入口指向 `/docs/quickstart`。这些链接只给访问请求附加来源信息，不在桌面应用中采集行为，不自动打开网站或发送统计事件。

发布后记录 GitHub 可获得的访问及克隆数据；官网已有统计支持时，再查看 UTM 来源访问和可归因的 Token 获取。若官网不保存 UTM 或不支持后续转化关联，只能记录可取得的访问数据，不将链接点击等同注册或 Token 获取。本轮不新增统计后台、自动任务或客户端埋点。
