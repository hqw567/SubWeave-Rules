# 使用与维护

本项目管理个人分流规则，并按 Aethersailor 正式模板生成 OpenClash、独立 Mihomo 和订阅转换配置。项目已包含 GitHub Actions 自动更新流程；本地准备文件不会创建远程仓库或启动 GitHub 调度。

## 模板范围

| 系列 | 普通版 | 故障转移版 |
| --- | --- | --- |
| 标准版 | `standard` | `standard-fallback` |
| 轻量版 | `lite` | `lite-fallback` |
| 极简 GFW 版 | `gfw` | `gfw-fallback` |
| 重度分流版 | `full` | `full-fallback` |

另外包含 `selfhosted-provider-fallback`、`selfhosted-manual-fallback` 两个自建节点优先版本，分别用 HTTP Provider 和完整静态节点定义加载自建节点。

公开构建共生成 **29 份配置**：

- `dist/openclash/<版本>.yaml`：10 个正式 YAML 版本，运行参数由 LuCI 管理。
- `dist/mihomo/<版本>.yaml`：上述 10 个版本加上独立运行设置。
- `dist/subconverter/<版本>.ini`：8 个正式 INI 版本，加上 Mainland 兼容入口。

Mainland 是上游生成的兼容入口，不是第九套独立分流方案。测试目录、归档模板和完整教学 YAML 不作为正式配置发布。

## 本地构建

在项目根目录执行。`python` 指 Python 3；如果系统使用 `python3`，替换命令名称即可。建议使用自己的 Python 虚拟环境。

```bash
python -m pip install -r requirements.txt
python scripts/rules.py build
python scripts/rules.py check
```

`build` 使用已保存的上游快照离线生成公开配置。`check` 检查项目结构与生成结果，不会启动 Mihomo、修改路由或测试真实订阅。

## 添加个人规则

编辑 `rules/custom.yaml`。初始实际规则为空，注释示例默认不生效。以下域名需要按实际用途替换：

```yaml
before_ads:
  - "DOMAIN,allow.example.com,@direct"
after_ads:
  - "DOMAIN-SUFFIX,proxy.example.com,@proxy"
  - "DOMAIN,block.example.com,@reject"
```

| 别名 | 生成目标 |
| --- | --- |
| `@proxy` | 普通版为 `🚀 手动选择`，故障转移版为 `🚀 故障转移` |
| `@direct` | `DIRECT` |
| `@reject` | `REJECT` |

优先使用别名，避免共用规则引用某个版本不存在的策略组。仅用于特定版本的规则放入 `variants`：

```yaml
before_ads: []
after_ads: []
variants:
  standard:
    before_ads: []
    after_ads:
      - "DOMAIN,ai.example.com,🤖 ChatGPT"
```

顺序是 `before_ads` → 秋风广告 → `after_ads` → 上游全部规则及 `MATCH`。`before_ads` 适合误杀白名单，优先用 `DOMAIN` 精确放行；`after_ads` 适合仍应接受广告过滤的普通路由调整。放在 `after_ads` 的规则不能解除前面已命中的广告拦截。

编辑后重新运行 `build` 和 `check`。不要直接维护 `dist/`，下次构建会覆盖它。不要在规则中放订阅凭据，内部域名也应先判断是否适合进入版本管理。

## 广告过滤

`config/settings.yaml` 中的 `ads` 控制秋风纯广告源、更新周期和策略组：

```yaml
ads:
  enabled: true
  name: awavenue-ads-only
  url: https://raw.githubusercontent.com/TG-Twilight/AWAvenue-Ads-Rule/main/Filters/AWAvenue-Ads-Rule-Clash-Classical-Only.Ads.yaml
  interval: 86400
  group: "🛡️ 广告过滤"
```

`enabled: false` 在重建后移除本项目的广告注入。运行时选广告组的 `REJECT` 表示拦截，`PASS` 表示跳过当前广告规则继续后续分流。不要用 `DIRECT` 代替关闭开关，也不要叠加同一套拦截规则。

秋风使用包含关键词规则的 Classical 格式，每天更新；只启用纯广告分类，没有另外叠加隐私或“不受欢迎”分类。

## 私有订阅与自建节点

公开 `dist/` 始终保留订阅占位地址。将 `config/secrets.example.yaml` 复制到 `.local/secrets.yaml`，在本机填写：

```yaml
subscription_url: "https://你的节点订阅地址"
```

执行：

```bash
python scripts/rules.py render
```

等价的完整参数：

```bash
python scripts/rules.py render --secrets .local/secrets.yaml --output .local/rendered
```

默认渲染 8 个常规版本的两种 YAML，共 16 份；提供对应自建参数时，额外生成该版本的两份 YAML。可重复 `--variant` 仅选择需要的版本：

```bash
python scripts/rules.py render --variant lite --variant standard-fallback
```

输出必须位于 Git 忽略的 `.local/`，不能写到 `dist/`。导入 `.local/rendered/` 中对应环境、版本的配置；不要公开或强制提交这些文件。渲染不会验证节点可用性，也不会把真实订阅写入公开 INI。

节点 Provider 支持 Mihomo 节点 YAML、URI 列表和 Base64 URI。它读取订阅中的节点，采用本项目的策略组与规则。订阅下载默认直连，首次使用需能访问订阅地址。

### 自建 Provider 版

增加自建 HTTP/HTTPS 订阅地址，保留普通订阅作为后备：

```yaml
subscription_url: "https://你的后备订阅地址"
selfhost_subscription_url: "https://你的自建节点订阅地址"
```

单条 `vless://` 等 URI 不能直接用作 HTTP Provider 地址。

### 手动自建节点版

增加 `selfhost_proxy`，值为完整 Mihomo 节点映射。以下仅示意 VLESS + REALITY 字段，参数必须改为自己的服务端设置：

```yaml
subscription_url: "https://你的后备订阅地址"
selfhost_proxy:
  type: vless
  server: selfhost.example.com
  port: 443
  uuid: "00000000-0000-0000-0000-000000000000"
  tls: true
  servername: example.com
  client-fingerprint: chrome
  flow: xtls-rprx-vision
  reality-opts:
    public-key: "替换为服务端Reality公钥"
    short-id: "0123456789abcdef"
```

示意值不可直接使用。生成器将名称固定为上游静态节点名称，保持组引用有效；其他协议可提供对应的完整节点映射。真实参数仅存放在 `.local/`，公开配置保留示例占位节点。

## 同步上游

```bash
python scripts/rules.py sync
```

默认将上游 `main` 解析为确定提交，下载允许的正式模板和许可证，验证后更新快照、重建全部公开配置。个人规则、广告设置、运行模板和私有订阅独立维护。

需要指定版本时执行 `python scripts/rules.py sync --ref 40位提交SHA`，将最后一项替换为真实完整 SHA。同步后查看 Git diff；需要最新私有配置时，再运行 `render`。公开构建不会自动刷新旧的私有渲染结果。

## GitHub Actions 自动更新

将项目推送到自己的 GitHub 仓库默认分支后启用 Actions，并确保仓库策略允许更新工作流以 `contents: write` 推送默认分支。流程使用内置 `GITHUB_TOKEN`，不需要节点订阅 Secret 或个人访问令牌。

更新工作流支持：

- 每天计划于 **北京时间 06:15** 同步最新上游。
- Actions 页面手动运行 **Update upstream templates**，`ref` 填 `main` 或 40 位 SHA。
- 默认分支的 `config/`、`rules/`、`templates/`、`scripts/` 或依赖文件变化时自动同步、重建，支持通过 GitHub 编辑个人规则。

工作流从默认分支当前内容开始，同步后运行单元测试和生成结果检查。仅当 `vendor/` 或 `dist/` 有变化时，以 `github-actions[bot]` 提交并推送这两个目录，不读取 `.local/`、不渲染真实订阅。首次上传后建议手动执行一次，确认权限与网络条件。

只读检查工作流在 push、PR 或手动触发时离线构建并检查，不同步、不推送。这样可以只提交源文件，在合入默认分支后由更新流程提交正式产物。

GitHub 定时触发可能延迟；工作流必须位于默认分支，公开仓库长期无活动时调度也可能被暂停。Fork 按 GitHub 的 Actions 启用规则处理。分支保护若拒绝机器人推送，任务会失败，不会绕过保护。当前文件准备完成不等于远程流程已经运行成功。

## 导入 OpenClash

使用对应 YAML，并按 [Aethersailor Wiki](https://github.com/Aethersailor/Custom_OpenClash_Rules/wiki) 配置 LuCI。DNS、端口、IPv6、TUN、嗅探和 GeoData 由 LuCI 管理；启用 GeoIP DAT 模式，保留覆盖当前模板标签的完整数据库并定期更新。不要再合并独立运行模板。

使用 YAML 时，节点由 Proxy Provider 更新，无需让在线订阅转换替换主文件。需要转换方式时使用 `dist/subconverter/` 对应 INI；它是转换模板，不能直接作为 Mihomo 运行配置。转换后端会收到订阅信息，需自行选择可信或自建服务。

绕过内核的流量不会经过广告和个人规则。检查“实验性：绕过指定区域 IP”和 IPv6 对应设置，按需关闭绕过或配置例外。关闭绕过后国内仍可按规则直连，但内核处理开销会增加。其他自定义规则或覆写也可能改变最终顺序，应查看实际运行配置。

## 导入独立 Mihomo

独立版合并 `templates/mihomo-runtime.yaml`：本机 HTTP/SOCKS5 `127.0.0.1:7890`，DNS `127.0.0.1:1053`，保留 IPv6，默认关闭 TUN 和外部控制器。应用仍需使用本机代理；SOCKS5 可选择远端域名解析以保留域名用于分流。

DNS 地址中的 `#@proxy` 按版本替换为主代理组。节点与直连解析走直连 DoH，一般境外解析经主代理组。局域网专用名称需要本地 DNS 策略或 hosts；系统 DNS、浏览器 DoH、未使用代理的程序不会自动被接管。

修改运行模板后重新构建、渲染；这不会影响 OpenClash。图形客户端可能覆盖部分设置，以最终运行配置为准。

## 验证与更新边界

客户端的节点、Rule Providers 和 GeoData 按各自周期更新；本项目同步的是模板结构。固定模板提交不冻结运行时的远程规则内容。

构建检查不能代替设备运行验证。导入后确认订阅、数据库与 Provider 下载成功，组中有可用节点，并观察连接命中。不要选择空地区组，部分内核可能用等效直连的 `COMPATIBLE` 补位；测速或故障转移不判断服务解锁。

导入模板不能单独证明全系统流量被接管、广告全部拦截或没有 DNS 绕过。结构说明见 [architecture.md](architecture.md)。

参考：[GitHub 定时工作流](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)、[Mihomo DNS](https://wiki.metacubex.one/config/dns/)、[Mihomo PASS](https://wiki.metacubex.one/config/proxies/built-in/)。
