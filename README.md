# Mac Mini / Mac Studio 统一 G3 建模项目

曲线拟合、无孔实体和带接口壳体已合并为一个项目。所有模型使用 [同一份拟合轮廓](data/fitted_profiles.json)：采用原曲线拟合项目的已验收曲线，控制点、次数、节点和权重统一管理。选择依据见 [曲线比较](validation/profile-comparison.json)。

完整原理、拟合结果、数学公式和独立复现方法见 [项目技术文档](docs/technical/README.md)，也可打开 [离线图文版](docs/technical/index.html)。其中包含完整精度控制点、内曲线节点表及可直接绘图的 Python 脚本。

最终模型集中存放在 `results`，文件名包含机型、系列、厚度和零件，见 [完整文件索引](DELIVERY.md)：

- [3DM](results/3DM)：Rhino 文件；`reference` 子目录另存有效拟合和偏移参考曲线。
- [STP](results/STP)：STEP 文件，统一使用 `.stp`，不重复存放 `.step`。
- [X_T](results/X_T)：Parasolid 文件。
- [masters](results/masters)：BREP 母版、当前设计参数、孔位表及尺寸验收。
- [fitting](results/fitting)：仍有效的拟合报告、偏移报告和图表。

共 20 个模型、60 个三格式使用文件，另有 20 个 BREP 母版。无孔系列有原高度实心体、总高 1 mm 实心薄片、2/3 mm 壁厚壳体，共 8 个模型；带接口系列按机型和 2/3 mm 壁厚分别提供壳体、底座、两实体装配，共 12 个模型。无孔系列原高度为 Mini 50 mm、Studio 95 mm。

| 带接口系列 | 壳体高度 | 底座高度 | 嵌入深度 | 装配总高 |
|---|---:|---:|---:|---:|
| Mini | 43 mm | 8 mm | 1.5 mm | 49.5 mm |
| Studio | 86.5 mm | 10.0 mm | 1.5 mm | 95.0 mm |

两款底座的上下平板及锥面法向厚度均为 1.5 mm，交接延长区允许局部增厚。内锥面直接接至平板，底座外圈与壳体内圈相同。Mini 大平板下表面与壳体底面重合，内底缘无环形台阶；Studio 朝桌面的带孔底板并入底座。两款均无支撑垫圈。锥面母线与水平面的锐角为 Mini 45°、Studio 30°，底座高度及底部外圆尺寸保持当前设计值。

Mini 有 108 个宽 2 mm、总长约 7.692388 mm 的长圆孔。Studio 底座有 8 圈 × 244 个、共 1952 个直径 1.5 mm 的圆孔，同圈孔心等高；背面有 27 排、86/85 孔交错的 2309 个直径 1.5 mm 圆孔。背孔先在展开平面中按横向 2 mm、纵向约 1.732051 mm、隔排错开 1 mm 布置，再将孔心按外轮廓弧长贴合，展开后的相邻孔心三角形为等腰。Studio 背孔与底孔均沿孔心处曲面法线，用全深度保持直径 1.5 mm 的直圆柱贯穿。通风口外缘沿锥面距上下交界各 0.75 mm，Studio 由最上、最下圈分别满足边距。前后 14 个接口沿用纠正后的顺序。当前重建规则见 [设计参数](data/enclosure_design.json)。

从本目录运行统一入口：

```powershell
python -B project.py verify
python -B project.py verify --refresh-design-audits
python -B project.py fit-check
python -B project.py build --family all
```

`build` 可加 `--model mac-mini` 或 `--model mac-studio`；带接口系列可加 `--family enclosure --thickness 2` 或 `3`。`export` 执行严格三格式转换及发布，`files` 核对交付文件。Python 与依赖版本见 [requirements.txt](requirements.txt)；本机保留统一 `.vendor` 和 `.devtools` 环境，原生转换使用已安装的 Rhino 和 SolidWorks。

仅重建 Studio 两种壁厚的底座及装配，可运行 `python -B tools/rebuild_studio_base.py`；同时修改背孔时添加 `--rebuild-housing`。随后运行 `python -B project.py verify --refresh-design-audits`。该流程从解析锥体和平板重新切孔，共用等高孔阵列；只有背孔规则与已发布壳体一致时才允许复用该壳体。

验收状态以 [最终验收报告](exact_release_check.json) 为准；[发布清单](exact_delivery_manifest.json) 将每个母版、规范几何数据和原生回读记录绑定到最终文件 SHA-256。[转换与 G3 验收说明](EXACT_MIGRATION.md) 和 [建模约定](docs/MODELING_NOTES.md) 说明适用范围及阈值。

清理按“是否符合最新需求、是否为必要输入或最终证据”判断，文件日期不作为依据。原始 USDZ、有效拟合曲线、当前代码、参数、依赖及最终验收证据保留；被替代的设计、导出实现、重复结果、旧打包文件和可重建缓存按 [清理记录](delivery_cleanup.json) 处理。运行构建会再次产生 `.tmp` 工作文件。
