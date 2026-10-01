# Mac Mini / Mac Studio 统一 G3 建模项目

项目包含曲线拟合、无孔实体和带接口壳体。所有模型使用 [同一份拟合轮廓](data/fitted_profiles.json)，控制点、次数、节点和权重统一管理。轮廓一致性数据见 [曲线比较](validation/profile-comparison.json)。

完整原理、拟合结果、数学公式和独立复现方法见 [项目技术文档](docs/technical/README.md)，也可打开 [离线图文版](docs/technical/index.html)。其中包含完整精度控制点、内曲线节点表及可直接绘图的 Python 脚本。

项目提供两套并行方案，共用已验收的拟合轮廓和精确母版：

| 方案 | 运行入口 | 产物与范围 |
|---|---|---|
| 统一建模与严格三格式导出 | `python -B project.py build --family all`；`python -B project.py export` | `results/3DM`、`results/STP`、`results/X_T`；完整 20 件正式模型及 BREP 母版 |
| [SolidWorks 原生参数化方案](solidworks/README.md) | `python -B project.py sw-build` | `results/SW`；16 个 `.sldprt` 零件与 4 个 `.sldasm` 装配体，包含完整接口及通风孔阵列 |

SW 方案保留固定的精确 G3 轮廓，以原生特征编辑高度、顶板、底座、接口位置及孔阵列，装配体使用原生配合。编辑入口、参数范围和数学定义见 [SW 方案说明](solidworks/README.md)，逐件参数修改、恢复与原生重开的结果见 [SW 验收报告](validation/solidworks-native/acceptance.json)。打开交付文件即可编辑这些特征，无需执行 FeatureWorks 识别。

统一建模方案的正式模型集中存放在 `results`，文件名包含机型、系列、厚度和零件，见 [完整文件索引](DELIVERY.md)：

- [3DM](results/3DM)：Rhino 文件；`reference` 子目录另存有效拟合和偏移参考曲线。
- [STP](results/STP)：STEP 文件，统一使用 `.stp`，不重复存放 `.step`。
- [X_T](results/X_T)：Parasolid 文件。
- [SW](results/SW)：SolidWorks 原生零件与关联装配体。
- [masters](results/masters)：BREP 母版、当前设计参数、孔位表及尺寸验收。
- [fitting](results/fitting)：拟合报告、偏移报告和图表。

共 20 个模型、60 个三格式使用文件，另有 20 个 BREP 母版。无孔系列有标称高度实心体、总高 1 mm 实心薄片、2/3 mm 壁厚壳体，共 8 个模型；带接口系列按机型和 2/3 mm 壁厚分别提供壳体、底座、两实体装配，共 12 个模型。无孔系列标称高度为 Mini 50 mm、Studio 95 mm。

| 带接口系列 | 壳体高度 | 底座高度 | 嵌入深度 | 装配总高 |
|---|---:|---:|---:|---:|
| Mini | 43 mm | 8 mm | 1.5 mm | 49.5 mm |
| Studio | 86.5 mm | 10.0 mm | 1.5 mm | 95.0 mm |

两款底座的上下平板及锥面法向厚度均为 1.5 mm，交接延长区允许局部增厚。内锥面直接接至平板，底座外圈与壳体内圈相同。Mini 大平板下表面与壳体底面重合，内底缘无环形台阶；Studio 朝桌面的带孔底板与底座为同一实体。两款均无支撑垫圈。锥面母线与水平面的锐角为 Mini 45°、Studio 30°。

Mini 有 108 个宽 2 mm、总长约 7.692388 mm 的长圆孔。Studio 底座有 8 圈 × 244 个、共 1952 个直径 1.5 mm 的圆孔，同圈孔心等高；背面有 27 排、86/85 孔交错的 2309 个直径 1.5 mm 圆孔。背孔先在展开平面中按横向 2 mm、纵向约 1.732051 mm、隔排错开 1 mm 布置，再将孔心按外轮廓弧长贴合，展开后的相邻孔心三角形为等腰。Studio 背孔与底孔均沿孔心处曲面法线，用全深度保持直径 1.5 mm 的直圆柱贯穿。通风口外缘沿锥面距上下交界各 0.75 mm，Studio 由最上、最下圈分别满足边距。前后 14 个接口的位置与排列由各壁厚的 `model_parameters.json` 定义。当前重建规则见 [设计参数](data/enclosure_design.json)。

统一建模方案从本目录运行：

```powershell
python -B project.py verify
python -B project.py verify --refresh-design-audits
python -B project.py fit-check
python -B project.py build --family all
python -B project.py sw-verify
```

`build` 可加 `--model mac-mini` 或 `--model mac-studio`；带接口系列可加 `--family enclosure --thickness 2` 或 `3`。`export` 执行严格三格式转换及发布，`files` 核对交付文件。Python 与依赖版本见 [requirements.txt](requirements.txt)；本机保留统一 `.vendor` 和 `.devtools` 环境，原生转换使用已安装的 Rhino 和 SolidWorks。

仅重建 Studio 两种壁厚的底座及装配，可运行 `python -B tools/rebuild_studio_base.py`；同时修改背孔时添加 `--rebuild-housing`。随后运行 `python -B project.py verify --refresh-design-audits`。该流程从解析锥体和平板重新切孔，共用等高孔阵列；只有背孔规则与已发布壳体一致时才允许复用该壳体。

验收状态以 [最终验收报告](exact_release_check.json) 为准；[发布清单](exact_delivery_manifest.json) 将每个母版、规范几何数据和原生回读记录绑定到最终文件 SHA-256。[转换与 G3 验收说明](EXACT_MIGRATION.md) 和 [建模约定](docs/MODELING_NOTES.md) 说明适用范围及阈值。

文件保留范围为原始 USDZ、有效拟合曲线、当前代码、参数、依赖、正式模型及最终验收证据。判断依据是是否符合当前需求、是否为必要输入或证据，文件日期不作为依据。`.tmp` 存放构建工作文件，可在任务结束后清理。
