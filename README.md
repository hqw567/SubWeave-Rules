# Personal Clash Rules

以 Aethersailor 的正式模板为基础，维护自己的规则和秋风纯广告配置，生成 OpenClash、独立 Mihomo 与订阅转换 INI。Python 3.10+，唯一依赖为 PyYAML。

## 支持范围

| 模板 | OpenClash YAML | Mihomo YAML | 订阅转换 INI |
| --- | --- | --- | --- |
| 标准 / Lite / GFW / Full | 支持 | 支持 | 支持 |
| 上述四种 Fallback 版 | 支持 | 支持 | 支持 |
| 自建节点 Provider Fallback | 支持 | 支持 | 上游未提供 |
| 手动自建节点 Fallback | 支持 | 支持 | 上游未提供 |
| Mainland 兼容入口 | 对应标准版 | 对应标准版 | 支持 |

当前共 **20 份 YAML + 9 份 INI**。上游已归档、测试目录和教学用 Complete 配置不作为正式模板发布。后续新增模板需在 `scripts/rules.py` 的映射中显式加入，避免自动引入未经适配的格式。

## 本地开始

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# 离线生成全部模板
python scripts/rules.py build

# 同步上游 main，固定到提交 SHA，检查后重新生成全部模板
python scripts/rules.py sync

# 检查源文件哈希、YAML 引用和生成一致性
python scripts/rules.py check
```

Windows PowerShell 激活命令为 `.venv\Scripts\Activate.ps1`。脚本支持 `sync --ref <完整40位提交SHA>`，可固定版本或回退上游快照。公共 API 限流时，会通过 `git ls-remote` 读取上游提交；本机需安装 Git。临时下载错误自动重试，失败时保留已有文件。

## 只维护自己的规则

编辑 `rules/custom.yaml`：

```yaml
before_ads:
  - DOMAIN,allow.example.com,@direct
after_ads:
  - DOMAIN-SUFFIX,proxy.example.com,@proxy
  - DOMAIN,block.example.com,@reject
variants: {}
```

示例域名请换成自己的真实目标；仓库默认个人规则为空。

`@proxy` 自动对应当前模板的手动选择或故障转移组。顺序为：**个人例外 → 秋风 → 一般个人分流 → 原有模板规则**。只适用于某个版本的规则放入 `variants.<版本>.before_ads/after_ads`。

所有模板统一生成，因此共享规则应使用 INI/YAML 都支持的单条域名/IP等规则；`RULE-SET`、逻辑和子规则等不支持跨格式自动转换，会报错，避免静默丢失。

秋风纯广告开关、URL 与更新周期在 `config/settings.yaml`；广告策略组可选 `REJECT` 或 `PASS`。`PASS` 继续后续原有分流，不强制直连。

## 生成自己的可用配置

`dist/` 只保留订阅占位符，可作为仓库公开模板。真实订阅写入 `.local/`，不会进入 Git：

```bash
mkdir -p .local
cp config/secrets.example.yaml .local/secrets.yaml
# 用编辑器填写 .local/secrets.yaml 内的 subscription_url
python scripts/rules.py render --variant standard
```

结果在 `.local/rendered/openclash/standard.yaml` 与 `.local/rendered/mihomo/standard.yaml`。不传 `--variant` 时生成全部常规八版本；填写自建节点字段后也生成相应自建版。命令不会改动公开 `dist/`，日志不打印订阅地址。

OpenClash 的 DNS、TUN、端口、GeoData 由 LuCI 配置。独立 Mihomo 默认本机代理 `127.0.0.1:7890`，TUN 关闭。需要统一广告过滤时，注意 OpenClash 大陆 IP 绕过会让部分流量不进入内核。详见 [使用说明](docs/usage.md)。

## GitHub Actions 自动更新

`.github/workflows/update-upstream.yml` 已提供：

- 每天北京时间 **06:15** 同步上游；GitHub 调度可能延迟。
- Actions 页面手动运行，可指定 `main` 或提交 SHA。
- 默认分支的个人规则、设置、模板或脚本修改后自动重新生成。
- 下载同一提交的上游模板 → 合并个人规则 → 生成 29 份模板 → 测试与检查 → 仅提交 `vendor/`、`dist/` 的变化。
- 无变化时不创建提交。更新流程不读取私有订阅，不调用本地私有渲染。

将仓库推送到 GitHub 后，确认 Actions 已启用，仓库允许工作流写入内容；默认分支保护若禁止 bot 直接提交，需要调整为允许此工作流或改用 PR 流程。当前只创建了本地仓库，远程运行需上传后发生。

另有只读 `check.yml` 验证 push / PR。自动更新若遇到格式变化、未知策略组或下载失败会失败退出，保留已有有效结果；不会静默忽略错误或覆盖个人规则。

## 项目结构

```text
rules/custom.yaml             # 个人规则
config/settings.yaml          # 秋风公共设置
config/secrets.example.yaml   # 私有订阅格式示例
templates/mihomo-runtime.yaml # 独立客户端运行设置
vendor/aethersailor/          # 上游模板、许可证、提交与哈希记录
scripts/                     # 同步、合成、验证与私有渲染
dist/openclash/              # 10 份 OpenClash YAML
dist/mihomo/                 # 10 份独立 Mihomo YAML
dist/subconverter/           # 9 份 INI
.local/                     # 私有数据与渲染结果，Git 忽略
```

完整说明：[用法](docs/usage.md) · [维护方式](docs/architecture.md) · [来源与许可证](NOTICE.md)。本地检查不等于真实订阅、内核运行、设备接管、DNS 或广告效果验证。
