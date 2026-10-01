# SolidWorks 参数化实验原型

本分支验证“保留精确 G3 轮廓，参数化高度、底座和孔阵列”的可行性。基线提交为 `ad5e7f0`，实验分支为 `experiment/solidworks-parametric`。正式交付仍使用已有的 20 件模型；本实验只增加三件独立的 `.sldprt` 原型。

## 已完成的原型

| 原型 | 保存的状态 | 已实测的修改及恢复 |
|---|---|---|
| [Mini 壳体](../../results/experimental/solidworks-parametric/mac-mini_G3_height_prototype.sldprt) | 高 43 mm，固定 2 mm 壁厚，无接口孔 | 高度 43 → 45 → 43 mm |
| [Studio 壳体](../../results/experimental/solidworks-parametric/mac-studio_G3_height_prototype.sldprt) | 高 86.5 mm，固定 2 mm 壁厚，无接口孔 | 高度 86.5 → 88.5 → 86.5 mm |
| [Studio 圆锥及单圈孔阵列](../../results/experimental/solidworks-parametric/mac-studio_cone_ring_prototype.sldprt) | 高 10 mm，板厚及锥面法向厚度 1.5 mm，锥母线与水平面 30°，一圈 244 个直径 1.5 mm 的法向圆柱孔 | 无孔锥体高度 10 → 11 → 10 mm；锥角 30 → 35 → 30°；孔径 1.5 → 1.6 → 1.5 mm；孔数 244 → 200 → 244 |

三件模型均已保存、关闭、在 SolidWorks 2025 中重开，并通过原生实体 `Check3` 检查。完整证据见 [独立验证报告](verification.json)，原始参数修改记录及原生回读数据位于 [实验产物目录](../../results/experimental/solidworks-parametric)。模型文件沿用仓库规则保存在本机，代码、说明和哈希绑定的验证报告纳入 Git。

## 壳体如何保留精确轮廓

直接将 B 样条控制数据写入 SolidWorks 草图时，本机的两种官方接口都会把内轮廓从 39 个控制点简化成 25 个。Mini 内轮廓同参数最大点偏差约 `1.88×10⁻⁶ mm`，公共节点下的控制点偏差约 `3.23×10⁻⁶ mm`，超出本项目的严格容差，因此最终原型采用精确母版方案。

程序从当前已验收的 `plain-shell_2mm.x_t` 读取无孔壳体，先核对正式发布清单中的 SHA-256，再将原生体复制到新的零件文档。特征树中的 `FixedG3Master` 保存这一固定母版，`NativeHeight` 是原生移动面特征：把外顶面和内腔顶面同时沿 Z 平移，维持顶部 2 mm 厚度。方程为：

```text
"HousingHeight" = 43mm          // Studio 为 86.5mm
"SeedHeight" = 50mm            // Studio 为 95mm
"D1@NativeHeight" = "SeedHeight" - "HousingHeight"
```

曲线的完整定义来自 [统一数学定义](../../docs/technical/geometry_definition.json)，原理见 [项目技术文档](../../docs/technical/README.md)。固定外轮廓仍为七次、每角 8 个控制点；固定内轮廓仍为七次、每角 39 个控制点。高度变化只改变面上的修剪范围，XY 控制点、权重和节点不变。

独立验证逐一检查母版导入、初始高度、修改后、恢复后及保存重开后的全部八个曲面支撑。实际结果：

| 指标 | Mini | Studio |
|---|---:|---:|
| XY 控制点最大误差，mm | `4.15×10⁻¹⁴` 以下 | `1.43×10⁻¹⁴` 以下 |
| 归一化节点最大误差 | `0` | `0` |
| 接点曲率最大绝对值，mm⁻¹ | `4.63×10⁻¹⁴` 以下 | `0` |
| 接点曲率弧长导数最大绝对值，mm⁻² | `1.35×10⁻¹³` 以下 | `0` |

位置及切向同时通过验证。验收容差仍为几何 `10⁻⁷ mm`、参数 `10⁻¹¹`；G3 接点曲率及其弧长导数阈值为 `10⁻⁸`。完整数据及各状态的结果记录在验证报告中。

移动后的八条曲边由水平面与原有 B 样条拉伸支撑相交产生。SolidWorks 回读 API 未直接暴露这些包装交线的 B 样条参数。验证程序核对完整支撑定义、交线端点、原生交线求值及面环连接关系；不将这份原型报告标为完整三格式发布验收。

## 底座及孔阵列如何参数化

原型用圆形草图、带拔模的原生拉伸及切除构造上下平板和内外锥面。取 `H` 为总高，`τ=1.5 mm`，`α` 为母线与水平面的锐角，`r₀=76.68363284099085 mm`，则：

```text
k = cot(α)
外锥面：r(z) = r₀ + k z
内锥面：r(z) = r₀ + k z - τ sqrt(1+k²)
上平板起始高度：H - τ
上平板外半径：r₀ + k(H - τ)
下平板内面高度：τ
```

两条母线间的法向距离恒为 `τ`。原生拔模角以竖直方向为参考，因此设为 `90°−α`。代码从实际特征中发现尺寸名称，再建立方程，避免假定尺寸编号。`BaseHeight`、`PlateThickness`、`ConeAngle` 和 `LowerRadius` 均保存在原生方程管理器中；本轮验证固定 `PlateThickness=1.5 mm`。

先在外锥面 `z=4.25 mm` 处建立法向草图平面，以完整圆形草图进行双向切除，得到直圆柱孔，再用原生 `VentRingPattern` 绕 Z 轴复制 244 次。独立验证读取每个圆柱的轴线和半径，检查直径、孔数、法向方向、等高孔心及等分角距；保存重开后再次验证。锥面实测法向厚度误差小于 `6×10⁻¹⁰ mm`。

## 原型的边界及后续迁移

- 壳体验证了两个机型的固定精确母版与可编辑高度，侧壁厚度固定为 2 mm。接口孔、Studio 背孔、3 mm 变体和装配尚未迁入原生特征树。
- 底座原型使用圆形上边界，只验证解析锥体和一圈孔阵列。它不是正式底座：G3 装配外圈、Studio 全部八圈底孔、Mini 底座及长圆孔仍使用正式项目中的现有结果。
- 孔的参考平面和孔心位置在本原型中固定。锥角及底座高度的修改检查在生成孔之前完成；修改成品原型中的锥角或高度后，尚未自动重算孔位、法向平面和 0.75 mm 边距。进一步迁移需要完成这项关联并重新验收。
- `.sldprt` 内包含固定精确体和实际可编辑原生特征；固定母版不会恢复为完整历史草图。本机未安装 NX，此分支不生成或声称验收 NX 原生 `.prt`。

原生质量属性采用 `Higher` 精度，但实测 SolidWorks 报出的体积仍与解析积分存在差异，恢复相同几何后也可有数值差异。验证报告分别列出原生体积与由七次多项式逐节点区间积分得到的解析体积。体积只作量级检查；严格形状判断依赖完整控制网、节点、原生求值和 G3 接点数据。

## 复现

依赖本机 SolidWorks 2025、默认 `gb_part.prtdot` 模板、随软件安装的官方 Interop DLL、Windows .NET Framework C# 编译器、Python 及项目 `.vendor` 中的 NumPy/SciPy。精确母版文件及其发布证据必须保留在当前项目中。

在项目根目录运行：

```powershell
./experiments/solidworks-parametric/run.ps1
```

脚本启动独立隐藏的 SolidWorks 进程，保留并恢复本次修改的导入及尺寸输入设置，不附着用户已有会话，不注册 COM 插件。建模完成后保存三个原型，回读并执行 `verify.py`；任一步失败均返回非零状态。默认运行结束后清理自己的编译文件。控制台会显示当前建模步骤和总用时。

已有原型的独立验证可单独运行，无需再次启动 CAD：

```powershell
python -B experiments/solidworks-parametric/verify.py
```

开发时可用 `-Mode housing` 或 `-Mode base` 重做一组原型，之后运行独立验证；`-CompileOnly` 仅编译并保留临时可执行文件。所有原型使用原始标称参数保存，修改测试后的状态已恢复。

官方 API 依据：[原生移动面](https://help.solidworks.com/2015/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFeatureManager~InsertMoveFace3.html)、[方程管理器](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IEquationMgr_members.html)、[质量属性精度](https://help.solidworks.com/2025/english/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swMassPropertyAccuracyLevel_e.html)。实现以本机安装的官方 SDK 和原生运行结果为准。
