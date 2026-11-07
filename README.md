# SubWeave-Rules

基于 Aethersailor 的公开扩展规则生成器，为 Mihomo、OpenClash、Stash 提供可定制分流。自定义规则、过滤方案与基础模板分别维护，GitHub Actions 自动同步和验证。

## 五种过滤方案

| 方案 | 标识 | 内容 |
| --- | --- | --- |
| 仅自定义扩展 | `custom-only` | 基础分流＋自定义规则，不加载秋风，不添加过滤策略组 |
| 纯广告（默认） | `ads-only` | 广告 |
| 完整防护 | `full-protection` | 广告＋隐私＋不受欢迎 |
| 广告＋不受欢迎 | `ads-unwanted` | 保留隐私统计与遥测相关连接 |
| 广告＋隐私 | `ads-privacy` | 保留更新、推送等相关功能连接 |

秋风四种订阅来自官方 Clash Classical YAML；其中“不受欢迎”包括强制更新、P2P/PCDN、推送、云控等连接，拦截可能影响对应功能。[官方说明](https://github.com/TG-Twilight/AWAvenue-Ads-Rule#订阅规则)

每种方案使用独立的规则集名称与缓存路径。四种秋风方案都支持在末尾的「🛡️ 秋风过滤」组选择 `REJECT` 或当前主策略组。

## 正式模板

每种方案生成 36 份配置，五种方案合计 **180 份：100 YAML＋80 INI**。

| 模板 | Mihomo YAML | OpenClash YAML | Clash INI | Stash INI |
| --- | --- | --- | --- | --- |
| 标准、Lite、GFW、Full 及各自 Fallback | 各 8 | 各 8 | 各 8 | 各 8 |
| 自托管订阅、手动节点 Fallback | 各 2 | 各 2 | — | — |

新目录按方案组织，不提供旧目录或 Mainland 别名：

```text
dist/
  ads-only/
    mihomo/standard.yaml
    openclash/standard.yaml
    subconverter/standard.ini
    subconverter-stash/standard.ini
  custom-only/...
  full-protection/...
  ads-unwanted/...
  ads-privacy/...
  manifest.json
  catalog.json
```

[纯广告标准 INI](https://raw.githubusercontent.com/hqw567/SubWeave-Rules/main/dist/ads-only/subconverter/standard.ini) · [纯自定义标准 INI](https://raw.githubusercontent.com/hqw567/SubWeave-Rules/main/dist/custom-only/subconverter/standard.ini) · [Stash 完整防护标准 INI](https://raw.githubusercontent.com/hqw567/SubWeave-Rules/main/dist/full-protection/subconverter-stash/standard.ini)

## 构建与同步

需要 Python 3.10+：

```sh
python -m pip install -r requirements.txt
python scripts/rules.py build
python scripts/rules.py check
python scripts/rules.py sync
```

`config/upstream.yaml` 指定上游 main 或完整 SHA。同步固定到一个提交后下载白名单文件，不执行上游脚本；失败保留原快照与产物。

可按方案、平台和版本构建，未选中的新格式产物保留：

```sh
python scripts/rules.py build --profile custom-only --format ini --platform stash --variant lite
python scripts/rules.py check --profile custom-only --format ini --platform stash --variant lite
```

`--profile`、`--variant` 可重复。默认构建全部 180 份；旧格式配置需重新生成，不进行迁移兼容。

## 自定义规则

编辑 `rules/custom.yaml`：

```yaml
before_filter:
  - DOMAIN,allowed.example,@direct
after_filter:
  - DOMAIN-SUFFIX,proxy.example,@proxy
```

顺序为：强制例外 → 所选秋风方案（如启用）→ 一般自定义规则 → Aethersailor。`@proxy` 随模板解析为主策略组，`@direct` 为 DIRECT，`@reject` 为 REJECT。支持按 `formats.yaml / ini / stash` 和 `variants.<版本>` 扩展。

`config/settings.yaml` 只配置过滤组名称、Provider 名称前缀和更新间隔；规则 URL 由方案统一决定。旧 `ads` 配置块及 `before_ads / after_ads` 字段不再接受。

## 私有订阅

公共模板只含占位符。真实订阅保存在被忽略的 `.local/secrets.yaml`，输出只能写入 `.local` 子目录：

```sh
python scripts/rules.py render --profile ads-privacy --variant standard
```

结果位于 `.local/rendered/ads-privacy/mihomo/standard.yaml` 等路径。默认私有渲染使用纯广告方案。OpenClash 与独立 Mihomo 的 DNS、TUN 和运行设置仍分别处理。

## 自动化与验证

Actions 每天约北京时间 06:15 同步，也支持手动触发。代码变更构建当前快照；无数据变化的定时任务跳过重复检查。发布前运行：

- 单元测试与产物一致性检查。
- 固定 Mihomo 内核验证全部 100 份 YAML，使用真实公开规则与 GeoData。
- 固定 SubConverter-Extended 转换全部 80 份 INI，并校验 Stash 使用的规则资源。

检查仅用合成节点与公开数据，不启动代理隧道，不读取真实订阅。已知 jsDelivr GitHub 别名下载失败时，校验器可回退到同一仓库路径的 GitHub Raw 原始资源；配置中的规则 URL 保持原始定义。转换与解析通过不等于 Stash 实机、连通性或拦截效果验证。

## 接入 SubWeave

`dist/catalog.json` 是 **schemaVersion 2**：包含五种方案、180 项产物、用途、客户端、参数约束、哈希和上游来源。前端据此统一展示模板系列和方案选择，不重复生成规则。

详细说明：[使用方法](docs/usage.md) · [目录契约](docs/catalog.md) · [架构](docs/architecture.md) · [来源与许可](NOTICE.md)
