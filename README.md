# Personal Clash Rules

仓库：[hqw567/personal-clash-rules](https://github.com/hqw567/personal-clash-rules) · [自动更新与检查](https://github.com/hqw567/personal-clash-rules/actions)

以 Aethersailor 的正式模板为基础，维护自己的规则和秋风纯广告配置，生成 OpenClash、独立 Mihomo 与订阅转换 INI。构建需要 Python 3.10+ 与 PyYAML；自动发布还使用固定版本的 Mihomo 内核校验公开 YAML。

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
git clone https://github.com/hqw567/personal-clash-rules.git
cd personal-clash-rules
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# 离线生成全部模板
python scripts/rules.py build

# 按 config/upstream.yaml 同步上游，记录提交并重新生成全部模板
python scripts/rules.py sync

# 检查源文件哈希、YAML 引用和生成一致性
python scripts/rules.py check
```

Windows PowerShell 激活命令为 `.venv\Scripts\Activate.ps1`。公共 API 限流时，通过 `git ls-remote` 读取提交，因此本机需安装 Git。下载错误会重试；下载或生成失败时保留已有结果。

仓库为私有，需要有权限的 GitHub 账号克隆。仓库中的 Raw 链接不能当作匿名公开订阅地址；在本机渲染后，将对应 YAML 导入客户端即可。

只处理日常使用的版本，也可选择格式与平台：

```bash
python scripts/rules.py build --format yaml --platform mihomo --variant lite
python scripts/rules.py check --format yaml --platform mihomo --variant lite
```

`--format` 可选 `all`、`yaml`、`ini`；`--platform` 为 YAML 选择 `all`、`openclash`、`mihomo`，指定单个平台时需同时使用 `--format yaml`；`--variant` 可重复。部分构建保留其他产物，默认命令仍生成全部 29 份。

## 控制上游版本

`config/upstream.yaml` 保存持续使用的同步目标：

```yaml
ref: main
```

希望持续冻结或回退时，把 `ref` 改为完整 40 位提交 SHA，然后运行 `sync`。之后定时任务和未指定覆盖值的手动任务都会遵守这个设置。`sync --ref <完整40位提交SHA>` 只覆盖本次同步，不改写该文件。

修改个人规则后，push 工作流只基于当前快照重新构建，不会顺带升级上游。修改 `config/upstream.yaml` 后，需要手动同步或等待下一次定时任务，才会切换快照。

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

当前生效的个人规则维护在 `rules/custom.yaml`。以上仅演示格式，新增规则时请替换示例域名，并保留已有规则。

`@proxy` 自动对应当前模板的手动选择或故障转移组。顺序为：**个人例外 → 秋风 → 一般个人分流 → 原有模板规则**。只适用于某个版本的规则放入 `variants.<版本>.before_ads/after_ads`。

通用规则需满足 INI/YAML 的共同转换范围。YAML 专有规则可以写入 `formats.yaml.before_ads/after_ads`，INI 专有规则写入 `formats.ini`；`variants.<版本>` 下也支持相同的 `formats`。这样高级 YAML 规则不会阻断全部 29 份模板的自动构建。

每个阶段的合并顺序为：通用 → 格式专用 → 版本通用 → 版本格式专用。完整示例见 [使用说明](docs/usage.md)。私有渲染只处理 YAML，不调用 INI 转换器。

秋风纯广告开关、URL 与更新周期在 `config/settings.yaml`；广告策略组可选 `REJECT` 或 `PASS`。`PASS` 继续后续原有分流，不强制直连。

## 生成自己的可用配置

`dist/` 只保留订阅占位符，可作为仓库公开模板。真实订阅写入 `.local/`，不会进入 Git：

```bash
mkdir -p .local
cp config/secrets.example.yaml .local/secrets.yaml
# 用编辑器填写 .local/secrets.yaml 内的 subscription_url
python scripts/rules.py render --variant standard
```

结果在 `.local/rendered/openclash/standard.yaml` 与 `.local/rendered/mihomo/standard.yaml`。不传 `--variant` 时生成全部常规八版本；填写自建字段后也生成相应自建版。按版本渲染只更新所选文件，保留其他已渲染版本并维护清单哈希。命令不改动公开 `dist/`，日志不打印订阅地址。

上游或个人规则更新后仍需重新渲染所用版本，并在客户端重新加载；保留的其他版本不会自动更新。

OpenClash 的 DNS、TUN、端口、GeoData 由 LuCI 配置。独立 Mihomo 默认本机代理 `127.0.0.1:7890`，TUN 关闭。需要统一广告过滤时，注意 OpenClash 大陆 IP 绕过会让部分流量不进入内核。详见 [使用说明](docs/usage.md)。

## GitHub Actions 自动更新

`.github/workflows/update-upstream.yml` 已提供：

- 每天北京时间 **06:15** 按 `config/upstream.yaml` 同步；GitHub 调度可能延迟。
- Actions 页面手动运行，`ref` 留空遵守配置；填写 `main` 或 SHA 只覆盖本次。
- 默认分支的个人规则、设置、模板或脚本修改后，从当前快照重新生成，不升级上游。
- 生成全部 29 份模板后，完成单元测试、结构检查与固定 Mihomo 内核配置校验，才提交 `vendor/`、`dist/` 的变化。
- 无变化时不创建提交。更新流程不读取私有订阅，不调用本地私有渲染。

Actions 需要启用，仓库策略需允许工作流写入内容。默认分支保护若禁止机器人直接提交，任务会失败，需要仓库所有者调整权限；流程不会绕过保护。实际运行状态以 [Actions 页面](https://github.com/hqw567/personal-clash-rules/actions) 为准。

只读 `check.yml` 在 push / PR 上从现有快照构建，再运行内核校验和一致性检查。它不会升级上游或推送提交；内核及校验数据可能需要下载。更新任务任何一步失败都不提交产物，个人规则不被同步改写。

## 内核配置校验

```bash
python scripts/check_mihomo.py --download --config-dir dist
```

固定内核版本见 `config/mihomo-version.txt`。检查器下载所需内核和公开数据，在隔离目录运行 `mihomo -t` 校验公开 YAML 的配置、规则和 GeoData 分类，不启动监听或 TUN。节点订阅使用临时替身，不验证真实节点连通性；INI 仍由转换器结构检查负责。

这比 YAML 解析更进一步，但不能证明设备接管、广告实际命中、DNS 路径或服务解锁。真实使用仍需在客户端验证。

## 项目结构

```text
rules/custom.yaml             # 个人规则
config/settings.yaml          # 秋风公共设置
config/upstream.yaml          # 持久上游引用：main 或完整 SHA
config/mihomo-version.txt     # 内核校验版本
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
