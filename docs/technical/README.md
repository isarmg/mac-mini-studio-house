# Mac Mini Mac Studio 项目技术文档

这套文档解释当前交付模型的来源、拟合方法、数学定义、三维建模方案和验收结果。阅读入口是 [完整离线浏览版](index.html)，也可以按下列顺序阅读 Markdown 原文。

1. [项目方案与运行流程](01_PROJECT.md)：输入、模块、输出以及操作命令。
2. [拟合方法与结果](02_FITTING.md)：数据筛选、目标函数、模型选择、误差及限制。
3. [精确数学定义](03_MATHEMATICS.md)：完整闭合轮廓、控制点、G3、内偏移、曲面和孔的公式。
4. [复现与验收](04_REPRODUCTION.md)：独立绘图、Rhino 曲线导出、验证方法及格式转换。
5. [完整内曲线控制表](05_INNER_CONTROLS.md)：四种内轮廓的全部 156 个控制点。

[完整精度参数](geometry_definition.json) 和 [独立复现脚本](reproduce_profiles.py) 可以一起复制到其他目录。SVG 和 CSV 是采样显示；选择 `--rhino` 时，脚本将公式中的样条控制数据直接写入 3DM。

本套文档对应当前冻结交付，而不是重新拟合所得的新模型。[文档验收记录](../../validation/documentation.json) 记录参数来源、数值交叉检查以及交付 CAD 的哈希核对结果。必要的图表由 [文档生成脚本](../../tools/build_technical_docs.py) 从正式参数和拟合报告生成。

<!-- BEGIN SUMMARY -->
本次文档对应发布 `20261001T030828560157Z`。外轮廓公式、四种内轮廓与独立 3DM 曲线复现均已检查；正式模型文件保持原值。
<!-- END SUMMARY -->
