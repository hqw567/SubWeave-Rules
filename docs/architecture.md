# 配置结构与维护边界

项目把上游快照、个人规则、广告设置、运行参数和私有节点信息分开保存。Python 脚本同步与构建，GitHub Actions 在计划时间、手动请求或默认分支源文件变化后调用相同脚本。

## 输入与产物

| 文件或目录 | 内容 | 公开构建用途 |
| --- | --- | --- |
| `vendor/` | 已记录提交的正式模板、兼容入口与许可证 | 保留上游原始分流结构 |
| `config/settings.yaml` | 秋风广告源、更新周期与广告组 | 注入广告配置 |
| `rules/custom.yaml` | 共用和按版本的 `before_ads`、`after_ads` | 注入个人规则 |
| `templates/mihomo-runtime.yaml` | 独立 Mihomo 的运行参数 | 仅用于独立 YAML |
| `dist/openclash/` | 10 个正式版本 YAML | 运行参数由 LuCI 管理 |
| `dist/mihomo/` | 10 个正式版本 YAML | 附加独立运行设置 |
| `dist/subconverter/` | 8 个正式 INI 与 Mainland 兼容入口 | 订阅转换模板 |
| `.local/` | 私有订阅、自建参数与渲染结果 | 不参与公开构建，Git 忽略 |

正式范围为标准、Lite、GFW、Full 及各自 Fallback，共 8 组 INI/YAML，再加 2 组 YAML 自建版本。Mainland 为兼容入口，测试、归档和完整教学模板不作为正式版本生成。

公开构建输出 29 份配置，不读取私有参数。默认私有渲染输出 16 份常规 YAML；提供自建参数后增加对应版本的两份，也可按 `--variant` 选择。

## 规则与别名

顺序为共用与当前版本的 `before_ads` → 广告过滤 → 共用与当前版本的 `after_ads` → 上游原有规则及 `MATCH`。原有规则之间的相对顺序保持不变。

`@proxy` 映射为当前主代理组：普通版是 `🚀 手动选择`，Fallback 与自建版是 `🚀 故障转移`。`@direct`、`@reject` 分别为 `DIRECT`、`REJECT`。DNS 地址中的 `#@proxy` 也按版本替换。

广告组的 `REJECT` 拦截请求，`PASS` 跳过当前广告规则继续后续分流。误杀放行放在 `before_ads`，普通路由放在 `after_ads` 可继续接受广告过滤。其他位置叠加的拦截不受这个开关控制。

## 运行环境

OpenClash 保留上游最小 YAML 方式，由 LuCI 提供 DNS、端口、TUN、IPv6、嗅探和数据库，不合并独立运行模板。绕过内核的连接不会接受本项目规则。

独立版合并运行模板，默认本机代理、TUN 关闭、外部控制器未开启。DNS 显式指定连接出口，节点域名使用直连 DoH，避免代理尚未建立时的解析循环。局域网私有名称和流量接管依赖实际网络与客户端设置。

## 公开与私有边界

`build` 只读公开输入和本地快照，向 `dist/` 输出订阅占位地址及自建示例节点。

`render` 才读取 `.local/secrets.yaml`：`subscription_url` 提供普通节点订阅，`selfhost_subscription_url` 提供自建 Provider，`selfhost_proxy` 提供完整静态节点映射。静态节点名称固定为上游引用的名称；缺少相应参数时默认跳过自建版本。

私有输出限制在 `.local/`。同步、公开构建与 Actions 不读取私有参数，不把渲染结果写回 `dist/`。Git 忽略不加密文件，也不清除已提交历史，真实参数不能强制加入版本管理。

## 同步与自动化

`sync` 默认将上游 `main` 解析为完整 SHA，下载允许的模板与许可证，验证后更新 `vendor/`、重建 `dist/`。可指定完整 SHA。同步不运行上游脚本，也不改写个人规则、设置、运行模板或私有参数。

更新工作流每天计划于北京时间 06:15 执行，也可手动运行，或由默认分支配置源文件变更触发。更新任务共用一个并发组，始终操作默认分支；测试与检查通过且内容变化后，仅提交 `vendor/`、`dist/`。使用内置令牌，无需订阅 Secret。

只读工作流在 push/PR 上从现有快照离线构建与检查，不同步、不推送。它允许仅修改源文件的 PR，默认分支更新任务负责提交产物。

远程执行需要 GitHub 仓库、默认分支上的工作流、已启用的 Actions 和允许更新的仓库策略。调度可能延迟，分支保护可能拒绝推送。文件准备、离线验证和远程执行是不同状态。

## 动态数据与验证边界

固定上游提交只固定模板。客户端仍按各自间隔更新节点、Rule Providers 和 GeoData，远程内容不随模板 SHA 冻结；排查时应查看当时实际加载的数据。

结构检查不能证明节点可用、流量已接管、广告命中、DNS 没有绕过或服务已解锁。导入后仍需观察实际客户端上的 Provider 加载与连接命中。

## 参考

- [Aethersailor YAML 使用说明](https://github.com/Aethersailor/Custom_OpenClash_Rules/tree/main/cfg/yaml)
- [Mihomo DNS 配置](https://wiki.metacubex.one/config/dns/)
- [Mihomo PASS 策略](https://wiki.metacubex.one/config/proxies/built-in/)
- [秋风纯广告规则](https://github.com/TG-Twilight/AWAvenue-Ads-Rule/blob/main/Filters/AWAvenue-Ads-Rule-Clash-Classical-Only.Ads.yaml)
- [GitHub 定时工作流](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
