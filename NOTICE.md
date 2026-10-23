# 来源与修改说明

基础模板来自 [Aethersailor/Custom_OpenClash_Rules](https://github.com/Aethersailor/Custom_OpenClash_Rules)，作者为 Aethersailor。准确提交和各源文件 SHA-256 记录在 `vendor/aethersailor/upstream.json`。

上游模板的 CC BY-SA 4.0 许可证保留在 `vendor/aethersailor/LICENSE`，本项目代码、文档与派生配置同样按根目录 `LICENSE` 中的 CC BY-SA 4.0 提供。修改包括广告 Provider 和策略组、个人规则合并、独立 Mihomo 运行配置、跨模板策略别名、附加 Stash 转换模板、同步和自动生成脚本。Stash 适配参考了上游 `py/generate_stash_configs.py`，并保留当前文档已支持的测速参数输入。

实际转换回归使用 [Aethersailor/SubConverter-Extended](https://github.com/Aethersailor/SubConverter-Extended) 的固定官方发布版；内核校验使用 [MetaCubeX/mihomo](https://github.com/MetaCubeX/mihomo)。检查工具下载到被忽略的 `.local/`，不随本仓库提交；各工具遵循其自身许可证。

广告规则引用 [TG-Twilight/AWAvenue-Ads-Rule](https://github.com/TG-Twilight/AWAvenue-Ads-Rule) 的纯广告 Classical YAML，由运行客户端按周期获取。本仓库未复制广告名单；它独立遵循其项目的 GPL-3.0 许可。

本项目与上述维护者及 Mihomo/OpenClash 官方不存在官方支持或背书关系。
