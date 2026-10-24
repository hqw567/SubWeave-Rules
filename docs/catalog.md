# 模板目录契约 v2

`catalog.json` 与产物原子发布，由 `manifest.json` 中的实际文件及内容派生。目录字段不包含订阅、凭据或私有渲染结果。不读取 v1 格式或旧路径别名。

顶层字段：schemaVersion=2、repository、ref、license、source、testedWith、defaultProfile、profiles、templates。

profiles 定义方案 id、名称、简述、categories 和 ruleUrl。categories 使用 ads/privacy/unwanted；custom-only 的 categories 为空、ruleUrl 为 null。默认方案为 ads-only。规则文件来自 AWAvenue 官方的四种 Clash Classical YAML。

每个产物包含：

- id：`<profile>/<target>/<variant>`。
- profile、variant、target、kind：方案、版本、客户端和使用方式。
- path：`<profile>/<目录>/<variant>.<ini|yaml>`。
- url：跟随 publication ref 的公开 Raw 地址。
- sha256、upstreamCommit：当前文件哈希与源版本；部分构建保留未修改文件的原始信息。
- requiredFlags、capabilities：转换参数约束和从实际内容提取的规则能力。

`config/catalog.yaml` 配置发布仓库与 ref。源方案和文件名映射集中在 `scripts/filter_profiles.py`，生成器与目录共用定义。新增或改变契约应同步消费端。默认完整构建包含 180 项；前端发布快照应使用完整目录。

`manifest.json` 校验模板文件；catalog 由相同数据重建比对，避免自引用哈希。新方案不能复用其他方案的规则缓存路径。私有 render 不生成公共目录。
