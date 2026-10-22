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

`build` 使用已保存的上游快照离线生成公开配置。`check` 检查项目结构与生成结果，不会启动 Mihomo、修改路由或测试真实订阅。真正的内核配置校验由后面的独立命令执行。

只构建、检查所用版本时，可以限制格式与平台：

```bash
python scripts/rules.py build --format yaml --platform mihomo --variant lite
python scripts/rules.py check --format yaml --platform mihomo --variant lite
```

`--format` 支持 `all`、`yaml`、`ini`；`--platform` 支持 `all`、`openclash`、`mihomo`，单个平台必须搭配 `--format yaml`；`--variant` 可重复。部分构建保留未选中的产物，清单记录每个文件的哈希和来源提交；因此未选中的旧版本不会被误标为已经更新。默认不加参数仍处理全部 29 份。

## 添加个人规则

当前生效的个人规则维护在 `rules/custom.yaml`。以下仅演示写法，新增规则时请按实际用途替换域名，并保留文件中的已有规则：

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

通用部分适合各格式都支持的单条域名/IP 规则。YAML 专有逻辑规则放入 `formats.yaml`，既能使用高级语法，也能继续自动生成全部 INI：

```yaml
before_ads: []
after_ads: []
formats:
  yaml:
    before_ads: []
    after_ads:
      - "AND,((DOMAIN-SUFFIX,example.com),(DST-PORT,443)),@proxy"
  ini:
    before_ads: []
    after_ads: []
variants: {}
```

`variants.<版本>` 下也可以放相同的 `formats.yaml`、`formats.ini`。每个阶段按“通用 → 格式专用 → 版本通用 → 版本格式专用”拼接；前面的规则优先匹配，并非后写的规则覆盖前面的规则。

整体顺序仍是 `before_ads` → 秋风广告 → `after_ads` → 上游全部规则及 `MATCH`。`before_ads` 适合误杀白名单，优先用 `DOMAIN` 精确放行；`after_ads` 适合仍应接受广告过滤的普通路由调整。放在 `after_ads` 的规则不能解除前面已命中的广告拦截。

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

广告策略组放在策略组列表末尾，默认选择 `REJECT` 拦截。另一个选项是当前版本的主代理组：普通版为 `🚀 手动选择`，Fallback 及自建版为 `🚀 故障转移`。选择它后，命中广告规则的流量直接交给该组，不再继续匹配后面的个人规则或上游分流。

需要移除广告匹配、完整恢复原有分流时，将 `enabled` 改为 `false`，重新构建并加载配置。不要另外叠加同一套广告拦截规则。广告组的显示位置调整不改变规则顺序：广告规则仍位于 `before_ads` 与 `after_ads` 之间。

广告组选项已移除 `PASS`，处理本次在 Stash 中遇到的该策略兼容问题。本项目没有新增 Stash 专用平台输出，完整配置的 Stash 真机运行尚未验证。若继续使用原来的标准版 INI 地址，更新模板并重新转换订阅即可，无需因为此次调整切换模板地址。

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

按版本渲染只更新选中的 YAML，保留其他已渲染文件并维护清单哈希。私有渲染不经过 INI 转换器，因此无关的 INI 转换限制不会阻断 YAML 使用；保留的旧版本也不会因此自动更新。

输出必须位于 Git 忽略的 `.local/`，不能写到 `dist/`。导入 `.local/rendered/` 中对应环境、版本的配置；不要公开或强制提交这些文件。渲染不会验证节点可用性，也不会把真实订阅写入公开 INI。每次更新源规则后，应重新渲染所用版本，并让客户端重新加载。

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

默认读取 `config/upstream.yaml`：

```yaml
ref: main
```

`main` 表示每次同步跟踪上游最新提交。要持续冻结或回退，将 `ref` 改为真实的完整 40 位 SHA，然后执行 `sync`；定时任务和未填写临时覆盖值的手动任务都会遵守它。个人规则、广告设置、运行模板和私有订阅不被同步改写。

`python scripts/rules.py sync --ref 40位提交SHA` 仅覆盖本次同步，不改写持久配置；下一次无参数同步仍使用配置文件。同步会从一个确定提交下载允许的模板和许可证，验证后更新快照、重建公开配置。修改 `config/upstream.yaml` 后须主动同步或等定时任务，快照才会切换。

同步后查看 Git diff；需要最新私有配置时，再运行 `render`。公开构建不会自动刷新旧的私有渲染结果。

## GitHub Actions 自动更新

将项目推送到自己的 GitHub 仓库默认分支后启用 Actions，并确保仓库策略允许更新工作流以 `contents: write` 推送默认分支。流程使用内置 `GITHUB_TOKEN`，不需要节点订阅 Secret 或个人访问令牌。

更新工作流支持：

- 每天计划于 **北京时间 06:15** 按 `config/upstream.yaml` 同步上游。
- Actions 页面手动运行 **Update upstream templates**，`ref` 留空遵守持久配置；填写 `main` 或 40 位 SHA 只覆盖这一次。
- 默认分支的 `config/`、`rules/`、`templates/`、`scripts/` 或依赖文件变化时，只从当前快照重建，支持通过 GitHub 编辑个人规则且不会顺带升级上游。

工作流从默认分支当前内容开始，按触发原因选择同步或构建，然后运行单元测试、生成结果检查和固定版本的 Mihomo 内核配置校验。全部通过且 `vendor/` 或 `dist/` 有变化时，才以 `github-actions[bot]` 提交并推送这两个目录；它不读取私有订阅、不执行私有渲染。首次上传后建议手动执行一次，确认权限与网络条件。

只读检查工作流在 push、PR 或手动触发时，从现有快照离线构建，再执行内核校验和一致性检查。内核及公开校验数据可能需要下载，但不会同步上游模板或推送提交。这样可以只提交源文件，在合入默认分支后由更新流程提交正式产物。

GitHub 定时触发可能延迟；工作流必须位于默认分支，公开仓库长期无活动时调度也可能被暂停。Fork 按 GitHub 的 Actions 启用规则处理。分支保护若拒绝机器人推送，任务会失败，不会绕过保护。当前文件准备完成不等于远程流程已经运行成功。

## 导入 OpenClash

使用对应 YAML，并按 [Aethersailor Wiki](https://github.com/Aethersailor/Custom_OpenClash_Rules/wiki) 配置 LuCI。DNS、端口、IPv6、TUN、嗅探和 GeoData 由 LuCI 管理；启用 GeoIP DAT 模式，保留覆盖当前模板标签的完整数据库并定期更新。不要再合并独立运行模板。

使用 YAML 时，节点由 Proxy Provider 更新，无需让在线订阅转换替换主文件。需要转换方式时使用 `dist/subconverter/` 对应 INI；它是转换模板，不能直接作为 Mihomo 运行配置。转换后端会收到订阅信息，需自行选择可信或自建服务。

绕过内核的流量不会经过广告和个人规则。检查“实验性：绕过指定区域 IP”和 IPv6 对应设置，按需关闭绕过或配置例外。关闭绕过后国内仍可按规则直连，但内核处理开销会增加。其他自定义规则或覆写也可能改变最终顺序，应查看实际运行配置。

## 导入独立 Mihomo

独立版合并 `templates/mihomo-runtime.yaml`：本机 HTTP/SOCKS5 `127.0.0.1:7890`，DNS `127.0.0.1:1053`，保留 IPv6，默认关闭 TUN 和外部控制器。应用仍需使用本机代理；SOCKS5 可选择远端域名解析以保留域名用于分流。

DNS 地址中的 `#@proxy` 按版本替换为主代理组。节点与直连解析走直连 DoH，一般境外解析经主代理组。局域网专用名称需要本地 DNS 策略或 hosts；系统 DNS、浏览器 DoH、未使用代理的程序不会自动被接管。

修改运行模板后重新构建、渲染；这不会影响 OpenClash。图形客户端可能覆盖部分设置，以最终运行配置为准。

## 内核配置校验

```bash
python scripts/check_mihomo.py --download --config-dir dist
```

版本由 `config/mihomo-version.txt` 固定。检查器验证官方内核归档的 SHA256 后缓存二进制；规则和 GeoData 每次重新下载，在同次检查中共享，结束后删除。它在隔离目录执行 `mihomo -t`，校验公开 YAML 的内核语法、规则和 GeoData 分类，不启动监听或 TUN，也不会连接真实订阅。订阅在校验目录中替换为临时节点 Provider；已下载的真实规则内容也会交给内核解析。

默认完整构建对应 20 个 YAML 校验样本。INI 由转换器结构检查负责，未在这里提交给第三方转换后端。内核校验通过也不证明节点连通、客户端实际接管、广告覆盖、DNS 路径或服务解锁。

## 验证与更新边界

客户端的节点、Rule Providers 和 GeoData 按各自周期更新；本项目同步的是模板结构。固定模板提交不冻结运行时的远程规则内容。

结构检查和内核配置校验不能代替设备运行验证。导入后确认订阅、数据库与 Provider 下载成功，组中有可用节点，并观察连接命中。不要选择空地区组，部分内核可能用等效直连的 `COMPATIBLE` 补位；测速或故障转移不判断服务解锁。

导入模板不能单独证明全系统流量被接管、广告全部拦截或没有 DNS 绕过。结构说明见 [architecture.md](architecture.md)。

参考：[GitHub 定时工作流](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)、[Mihomo DNS](https://wiki.metacubex.one/config/dns/)。
