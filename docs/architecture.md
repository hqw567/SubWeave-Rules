# 架构

流水线：不可变上游快照 → 自定义扩展规则 → 五种过滤方案 → 平台/格式适配 → 校验 → 原子发布。

- `vendor/aethersailor/`：指定提交的白名单源文件及哈希。
- `rules/custom.yaml`：全局、格式、模板专属扩展。
- `config/settings.yaml`：过滤组与缓存名称前缀、更新间隔。
- `scripts/filter_profiles.py`：五种方案的统一定义。
- `scripts/rules.py`：组合、完整/部分构建、同步及私有渲染。
- `scripts/ini_support.py`：在原始 INI 上合并扩展。
- `scripts/stash_support.py`：对固定转换器的 Stash 目标进行必要映射。
- `scripts/catalog_support.py`：v2 公开目录。

默认生成 5 × (10 OpenClash YAML＋10 Mihomo YAML＋8 Clash INI＋8 Stash INI) = 180 份。每个方案的 Provider 名称带方案后缀；custom-only 不生成该 Provider。

公共构建只使用占位符；私有渲染必须在 `.local` 下，拒绝逃逸路径、符号链接跳转和公开输出目录。同步失败保留旧快照，构建先在临时目录完成后再替换。部分构建保留其他有效产物，并分别记录源版本；没有旧目录迁移逻辑。

单元测试、100 份 YAML 的真实内核检查、80 次实际转换与去重后的公开规则资源解析组成发布检查。源配置与最终转换结果同时比较规则顺序、策略组引用和过滤选项。测试不读取私有订阅、不启动代理隧道。

前端只消费版本化目录和模板 URL。未来新增 UI 或模板不需要复制生成逻辑，也不要求合并两个仓库。
