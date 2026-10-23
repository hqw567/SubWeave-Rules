# Personal Clash Rules

仓库：[hqw567/personal-clash-rules](https://github.com/hqw567/personal-clash-rules) · [自动更新与检查](https://github.com/hqw567/personal-clash-rules/actions)

以 Aethersailor 的正式模板为基础，维护自己的规则和秋风纯广告配置，生成 OpenClash、独立 Mihomo 与订阅转换 INI。构建需要 Python 3.10+ 与 PyYAML；自动发布还使用固定 Mihomo 内核和本地订阅转换器验证产物。

## 支持范围

| 模板 | OpenClash YAML | Mihomo YAML | Clash INI | Stash INI |
| --- | --- | --- | --- | --- |
| 标准 / Lite / GFW / Full | 支持 | 支持 | 支持 | 支持 |
| 上述四种 Fallback 版 | 支持 | 支持 | 支持 | 支持 |
| 自建节点 Provider Fallback | 支持 | 支持 | 上游未提供 | 不生成 |
| 手动自建节点 Fallback | 支持 | 支持 | 上游未提供 | 不生成 |
| Mainland 兼容入口 | 对应标准版 | 对应标准版 | 支持 | 支持 |

当前共 **38 份产物：20 份 YAML + 9 份 Clash INI + 9 份附加 Stash INI**。原有 29 份文件及地址保留。上游已归档、测试目录和教学用 Complete 配置不作为正式模板发布；新增版本需在生成器中显式适配。

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

仓库公开，模板可匿名获取。标准版订阅转换模板地址为：

```text
https://raw.githubusercontent.com/hqw567/personal-clash-rules/refs/heads/main/dist/subconverter/standard.ini
```

将该地址填入订阅转换服务的 `config` 参数即可使用最新生成的标准版模板。仓库仅保存规则与订阅占位符，真实订阅仍保留在本地 `.local/`；也可在本机渲染后，将对应 YAML 导入客户端。

额外的 Stash 标准版地址为：

```text
https://raw.githubusercontent.com/hqw567/personal-clash-rules/refs/heads/main/dist/subconverter-stash/standard.ini
```

选择附加版本时，在转换服务使用 `target=stash`，将新地址填入 `config`。原来的标准版 `config` 地址与 `target=clash` 链路仍可继续使用，不会被新版本替换。转换目标由后端决定输出格式，不等同于客户端的全部兼容范围。

只处理日常使用的版本，也可选择格式与平台：

```bash
python scripts/rules.py build --format yaml --platform mihomo --variant lite
python scripts/rules.py check --format yaml --platform mihomo --variant lite
```

`--format` 可选 `all`、`yaml`、`ini`；YAML 可按 `--platform openclash` 或 `mihomo` 筛选，Stash 仅用于 INI：

```bash
python scripts/rules.py build --format ini --platform stash --variant standard
python scripts/rules.py check --format ini --platform stash --variant standard
```

`--format ini` 默认生成两套共 18 份 INI；`--variant` 可重复。部分构建保留其他产物，默认不加参数仍生成全部 38 份。不支持 `--format yaml --platform stash`。

## 控制上游版本

`config/upstream.yaml` 保存持续使用的同步目标：

```yaml
ref: main
```

希望持续冻结或回退时，把 `ref` 改为完整 40 位提交 SHA，然后运行 `sync`。之后定时任务和未指定覆盖值的手动任务都会遵守这个设置。`sync --ref <完整40位提交SHA>` 只覆盖本次同步，不改写该文件。

修改个人规则后，push 工作流只基于当前快照重新构建，不会顺带升级上游。修改 `config/upstream.yaml` 后，需要手动同步或等待下一次定时任务，才会切换快照。

同步解析出的 SHA 未变化且本地快照哈希完整时，直接复用快照，不重复下载上游文件；个人规则或运行模板的改动仍会参与本地构建。

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

通用规则由所有产物共享。YAML 专有规则写入 `formats.yaml`，现有 Clash INI 专有规则写入 `formats.ini`，附加 Stash INI 专有规则写入 `formats.stash`；各块支持 `before_ads/after_ads`，`variants.<版本>` 下也支持相同结构。这样格式专有规则不会阻断全部 38 份产物的自动构建。

每个阶段的合并顺序为：通用 → 格式专用 → 版本通用 → 版本格式专用。完整示例见 [使用说明](docs/usage.md)。私有渲染只处理 YAML，不调用 INI 转换器。

秋风纯广告开关、URL 与更新周期在 `config/settings.yaml`。广告策略组位于列表末尾，可选 `REJECT` 或当前版本的主代理组：普通版为 `🚀 手动选择`，Fallback 版为 `🚀 故障转移`。选择主代理组后，命中广告规则的流量交给该组处理；需要恢复后续原有分流时，将 `ads.enabled` 改为 `false` 并重建。

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
- 产物变化后，完成含真实内核反例的单元测试、结构检查、20 份 YAML 内核检查，以及 9 份 Clash INI 和 9 份 Stash INI 的实际转换检查，才提交 `vendor/`、`dist/`。
- 定时或手动同步无产物变化时，在下载内核和规则数据前结束；不重复重验证，也不创建提交。源代码 push 即使产物未变化，仍执行完整门禁。
- 更新流程不读取私有订阅，不调用本地私有渲染。

Actions 需要启用，仓库策略需允许工作流写入内容。默认分支保护若禁止机器人直接提交，任务会失败，需要仓库所有者调整权限；流程不会绕过保护。实际运行状态以 [Actions 页面](https://github.com/hqw567/personal-clash-rules/actions) 为准。

默认分支 push 只由更新工作流执行重验证；其他分支 push、PR 和手动检查由只读 `check.yml` 处理。纯文档修改不触发完整门禁。两者使用同一个本地 action，统一准备内核、运行测试和验证产物，避免步骤漂移。

Actions 仅缓存经过 SHA256 校验的 Mihomo 和转换器归档，分别按系统、架构及版本/检查器配置区分；命中缓存后仍重新校验、解压。动态规则和 GeoData 在每次真正执行内核检查时重新下载。更新任务任何一步失败都不提交产物，个人规则不被同步改写。

## 内核配置校验

```bash
python scripts/check_mihomo.py --download --config-dir dist
python scripts/check_conversion.py --download --config-dir dist
```

固定内核版本见 `config/mihomo-version.txt`。检查器下载所需内核和公开数据，在隔离目录运行 `mihomo -t` 校验公开 YAML 的配置、规则和 GeoData 分类，不启动监听或 TUN。CI 在运行单元测试前准备内核并设置 `MIHOMO_TEST_BINARY`，使真实内核拒绝错误配置的用例实际运行。

INI 检查使用固定版本的本地转换器与虚拟节点，在本机回环地址将原有 9 份 INI 转为 Clash、附加 9 份 INI 转为 Stash，共检查 18 份结果，不使用真实订阅或公共转换服务。转换成功不等于 Stash 真机或服务解锁验证。

Stash 官方明确支持 [Clash 配置标准](https://stash.wiki/en)，也支持域名/IP 类型的 [MRS 规则集](https://stash.wiki/en/rules/rule-set)和 [`url-test.tolerance`](https://stash.wiki/en/proxy-protocols/proxy-groups)。附加模板针对当前转换后端的目标格式进行适配，不应把后端某项转换失败推断为 Stash 客户端完全不支持相应能力。

附加 INI 保留原有测速 URL 和完整时间参数。当前固定转换器 v1.10.5 的 Stash 目标仍可能省略部分字段，例如实测未导出 tolerance；需要对应设置时应核对最终输出。

这比 YAML 解析更进一步，但不能证明设备接管、广告实际命中、DNS 路径或服务解锁。真实使用仍需在客户端验证。

## 项目结构

```text
rules/custom.yaml             # 个人规则
config/settings.yaml          # 秋风公共设置
config/upstream.yaml          # 持久上游引用：main 或完整 SHA
config/mihomo-version.txt     # 内核校验版本
config/converter-version.txt  # 本地转换器校验版本
config/secrets.example.yaml   # 私有订阅格式示例
templates/mihomo-runtime.yaml # 独立客户端运行设置
vendor/aethersailor/          # 上游模板、许可证、提交与哈希记录
scripts/                     # 同步、合成、验证与私有渲染
.github/actions/             # 两条工作流共用的验证步骤
dist/openclash/              # 10 份 OpenClash YAML
dist/mihomo/                 # 10 份独立 Mihomo YAML
dist/subconverter/           # 原有 9 份 Clash INI
dist/subconverter-stash/     # 附加 9 份 Stash INI
.local/                     # 私有数据与渲染结果，Git 忽略
```

完整说明：[用法](docs/usage.md) · [维护方式](docs/architecture.md) · [来源与许可证](NOTICE.md)。本地检查不等于真实订阅、内核运行、设备接管、DNS 或广告效果验证。
