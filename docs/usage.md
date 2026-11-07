# 使用方法

先选择模板系列，再选择客户端、过滤方案和手动/故障转移。SubWeave 模板库会把这些选择集中在同一个详情中。

## 订阅转换

Mihomo、OpenClash 使用 `target=clash` 与 `dist/<方案>/subconverter/<版本>.ini`；Stash 使用 `target=stash` 与 `dist/<方案>/subconverter-stash/<版本>.ini`。

新建现代配置建议使用完整配置、保留规则集合和 Clash 新字段；连接参数按订阅/内核能力继承。需要 MRS 或 Stash 的模板应使用通过对应检查的增强后端。转换器对格式的限制与客户端自身支持范围是两个边界。

## 本地 YAML

`dist/<方案>/mihomo/` 包含独立运行配置；`dist/<方案>/openclash/` 用于 OpenClash。自托管模板需要按 `config/secrets.example.yaml` 填写相应的订阅或节点信息。

```sh
python scripts/rules.py render --profile custom-only --variant standard
```

私有文件写入 `.local/rendered/custom-only/`。不得把真实订阅写入 config、rules、dist 或上传到公开仓库。YAML 运行配置不能直接作为转换器的 INI config 参数。

## 扩展规则

`rules/custom.yaml` 是唯一的自定义规则入口。`before_filter` 适合明确直连/放行例外，优先于过滤；`after_filter` 是过滤后的通常分流。关闭秋风的 custom-only 方案仍合并两组规则。

```yaml
before_filter:
  - DOMAIN,allowed.example,@direct
after_filter: []
formats:
  yaml:
    after_filter:
      - AND,((NETWORK,udp),(DST-PORT,443)),@reject
variants:
  lite:
    after_filter:
      - DOMAIN,lite.example,@proxy
```

INI 和 Stash 对自定义规则类型有各自的可移植范围；不支持的规则会报错，不静默删除。自定义规则不能提前加入 MATCH/FINAL 截断上游分流。

## 过滤方案

- custom-only：不添加秋风 Provider、过滤规则或过滤策略组。
- ads-only：仅广告。
- full-protection：广告、隐私与不受欢迎内容。
- ads-unwanted：不包含隐私规则。
- ads-privacy：不包含不受欢迎规则。

“不受欢迎”涉及强制更新、P2P/PCDN、推送、云控等功能连接。四个启用过滤的方案都使用独立缓存路径，过滤组排列在末尾，候选为 REJECT 和当前主策略组。

旧配置字段、旧目录与 Mainland 入口已经移除，请按新目录生成链接。
