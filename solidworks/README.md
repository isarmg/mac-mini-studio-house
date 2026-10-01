# SolidWorks 原生参数化方案

本方案共用项目的[精确曲线定义](../docs/technical/geometry_definition.json)和[设计参数](../data/enclosure_design.json)，以 SolidWorks 原生移动面、拉伸、切除、阵列、方程和装配配合建立模型。

## 文件和编辑入口

交付目录为 [`results/SW`](../results/SW)。每个机型包含以下文件，两款共 16 个 `.sldprt` 和 4 个 `.sldasm`：

| 文件名后缀 | 内容 | 数量／机型 |
|---|---|---:|
| `_solid.sldprt` | 标称高度实心体，Mini 50 mm、Studio 95 mm | 1 |
| `_1mm-solid.sldprt` | 总高度 1 mm 的实心薄片 | 1 |
| `_plain-shell_2mm.sldprt`、`_plain-shell_3mm.sldprt` | 无孔壳体 | 2 |
| `_enclosure_2mm_housing.sldprt`、`_enclosure_3mm_housing.sldprt` | 完整接口和通风孔壳体 | 2 |
| `_enclosure_2mm_base.sldprt`、`_enclosure_3mm_base.sldprt` | 完整底座和通风孔 | 2 |
| `_enclosure_2mm_assembly.sldasm`、`_enclosure_3mm_assembly.sldasm` | 关联壳体与底座的原生装配体 | 2 |

文件名前缀为 `mac-mini` 或 `mac-studio`。装配体与其引用的两个零件放在同一目录；复制项目时应一并保留。原有三格式方案位于 `results/3DM`、`results/STP`、`results/X_T`。

打开原生零件后，在“工具 → 方程式”中修改全局变量，再按 **Ctrl+Q 强制重建**。特征树中的具体草图、移动实体、拉伸、切除和阵列也可直接编辑。交付文件包含这些特征，无需执行 FeatureWorks 特征识别。

| 参数 | 作用 | 标称值 |
|---|---|---|
| `HousingHeight` | 壳体／实心体高度 | 取决于文件 |
| `TopThickness` | 壳体顶部厚度 | 2 或 3 mm |
| `PortHeightOffset` | 功能接口整体沿 Z 移动 | 0 mm |
| `BaseHeight` | 底座总高度 | Mini 8、Studio 10 mm |
| `PlateThickness` | 上下平板厚度及锥面法向壁厚 | 1.5 mm |
| `ConeAngle` | 锥母线与水平面的锐角 | Mini 45°、Studio 30° |
| `LowerRadius` | 外锥面在 Z=0 处的半径 | 由精确设计定义 |
| `VentClearance` | 孔口沿锥面距上下交界的边距 | 0.75 mm |
| `VentWidth`、`VentCount` | Mini 长圆孔宽度与数量 | 2 mm、108 |
| `VentDiameter` | Studio 底孔直径 | 1.5 mm |
| `RingPairs`、`HolesPerRing` | Studio 底孔的环对数与每圈孔数 | 4、244 |
| `RearHoleDiameter` | Studio 背孔直径 | 1.5 mm |
| `RearRowPairs` | Studio 背孔的行对数，总行数为 `2n+1` | 13 |
| `RearRowPitch`、`RearBottomZ` | 背孔竖向间距及最低孔心高度 | 由展开阵列定义 |

接口孔的 `PortNNPosition` 是原生移动实体特征，其 X、Y、Z 尺寸可单独编辑。Z 尺寸受 `PortHeightOffset` 方程控制；单独调整时应在该方程中加入需要的偏移。背孔在圆角区域按各列法线建立圆形草图，平直区域使用横向阵列；圆孔直径由共同变量驱动。

轮廓的 XY 控制点、节点、权重，以及功能接口的源轮廓，是固定的精确参考几何。2 mm 与 3 mm 侧壁分别使用各自精确内曲线。修改轮廓或连续改变侧壁厚度，需要更新统一曲线定义并运行生成程序；原生参数编辑的范围是表中尺寸、接口位置、孔阵列及装配关系。FeatureWorks 对这些参考曲线的近似识别不属于本方案的几何定义。

Studio 背孔的横向弧长列和对应法向基准由统一曲线定义固定；直接联动编辑的参数为孔径、竖向间距、最低孔心高度及排数。整体改变横向孔距或开孔覆盖宽度时，需要更新设计定义并重新生成，以保持圆角区各孔的法向方向正确。

参数应保持实体可构造：孔之间有间隙，孔口位于锥面范围内，内腔高度和顶部厚度大于 0.5 mm，锥面能与装配平板相交。交付参数遵循项目尺寸要求；验收另外检查下述联合修改状态。

## 精确 G3 轮廓与壳体

`prepare.py` 按完整精度控制点、节点重数和权重构造 0.5 mm 深的参考棱柱，其曲面采用曲线的原生直线拉伸支撑。外轮廓每角为七次、8 个控制点；内轮廓每角为七次、39 个控制点。四角由刚性旋转得到，角间用直线连接。

`ExactG3OuterProfile` 与 `ExactG3InnerProfile` 保存参考实体。`ExtrusionHeight` 移动外棱柱顶面，`CavityDepth` 移动内棱柱顶面，`HollowHousing` 作原生布尔切除。`HousingHeight` 是驱动高度的全局变量。高度和顶板厚度改变时，侧面支撑曲线的 XY 控制点保持固定。内侧使用独立的精确内轮廓。

以曲线 \(C(u)\)、拉伸方向 \(d\) 表示侧面：

\[
S(u,v)=C(u)+vd.
\]

验收读取原生曲线的全部控制点、节点、权重，并独立计算曲线与曲面的求值结果。设 \(v=C'\)、\(a=C''\)、\(j=C'''\)，平面曲线的曲率及其弧长导数为：

\[
\kappa=\frac{\det(v,a)}{\|v\|^3},\qquad
\frac{d\kappa}{ds}=\frac{\det(v,j)}{\|v\|^4}
-\frac{3\det(v,a)(v\cdot a)}{\|v\|^6}.
\]

直线接点满足位置相同、切向平行、\(\kappa=0\)、\(d\kappa/ds=0\)。G3 指轮廓角段与直线的连接；孔口与平面／锥面的锐边按设计保留。

## 底座、锥面和孔位联动

取底座总高 \(H\)、板厚及法向壁厚 \(\tau=1.5\rm\,mm\)、锥角 \(\alpha\)、外半径截距 \(r_0\)。底部圆板覆盖 \(0\le z\le\tau\)，上方装配平板覆盖 \(H-\tau\le z\le H\)。外锥面的显露区为 \(0\le z\le H-\tau\)，内锥面从 \(z=\tau\) 延长至 \(z=H\)，直接与上下平板相交。内外锥面为：

\[
r_o(z)=r_0+z\cot\alpha,\qquad
r_i(z)=r_0+z\cot\alpha-\tau\csc\alpha.
\]

原生带拔模拉伸及切除的拔模角为 \(90^\circ-\alpha\)。外锥体的拉伸终点为 \(H-\tau\)，与装配平板下表面合并；上方外轮廓由精确装配平板控制。内锥面直接延长与平板相交；交接延长区域允许局部增厚。顶部装配平板使用相应壳体的精确内轮廓，上平板下表面位于 \(H-\tau\)。

在外锥面点
\[
P(z,\theta)=\big(r_o(z)\cos\theta,r_o(z)\sin\theta,z\big)
\]
处，单位母线方向与单位法线分别为：
\[
g=(\cos\alpha\cos\theta,\cos\alpha\sin\theta,\sin\alpha),\quad
n=(\sin\alpha\cos\theta,\sin\alpha\sin\theta,-\cos\alpha).
\]

孔草图建立在以 \(n\) 为法线的平面，使用直线双向切除；孔壁为完整的直圆柱，半径沿轴线不变。

Mini 长圆孔宽 \(w=2\rm\,mm\)，边距 \(c=0.75\rm\,mm\)，长度和中心高度为：
\[
L=\frac{H-\tau}{\sin\alpha}-2c,\qquad z_c=\frac{H-\tau}{2}.
\]
两个圆弧端的圆心为 \(P(z_c,\theta)\pm g(L-w)/2\)，圆弧半径为 \(w/2\)。原生长圆槽草图、法向切除和圆周阵列给出全部 108 孔。相位来自统一设计参数。

Studio 底孔直径 \(D=1.5\rm\,mm\)，总圈数 \(R=2\,\texttt{RingPairs}\)，每圈孔数 \(N=\texttt{HolesPerRing}\)：
\[
z_0=(c+D/2)\sin\alpha,\quad
z_j=z_0+j\frac{H-\tau-2z_0}{R-1},\quad
\theta_{j,k}=\frac{2\pi}{N}\left(k+\frac{j\bmod2}{2}\right).
\]
两组原生沿母线阵列加圆周阵列构成 8 圈、1952 孔。每圈孔心等高；高度、锥角、直径或圈数改变后，草图参考平面、孔心位置与阵列间距共同更新。

Studio 背面先在展开平面中以横向间距 2 mm、纵向间距 \(\sqrt3\rm\,mm\) 排布，隔行横向错开 1 mm，再按外轮廓弧长映射孔心。每个圆的切除方向采用该处轮廓的水平法线。两组沿 Z 的原生阵列给出 27 行、86／85 孔交错的完整 2309 孔。展开映射、14 个功能接口及其方向均由共同设计数据定义。

## 装配

装配体固定底座，壳体保持可通过配合定位。`BaseToHousing` 将壳体 XY 基准面与底座的 `MatingPlane` 重合，另两个平面配合对齐 XZ、YZ。`MatingPlane` 高度由 `BaseHeight-PlateThickness` 驱动。

因此底座进入壳体 1.5 mm；Mini 总高为 \(43+8-1.5=49.5\rm\,mm\)，Studio 为 \(86.5+10-1.5=95\rm\,mm\)。改变底座高度并重建装配体后，壳体位置随配合更新。

## 验收与复现

[`acceptance.json`](../validation/solidworks-native/acceptance.json) 记录每个文件的 SHA-256、原生重开、参数修改前后及恢复后的独立几何检查。原生 API 读回数据保存在同目录的 `*.native.json`、`*.assembly.json`；`images` 保存原生预览、壳体内侧和底座底面视图。独立的 `review.ps1` 在使用默认建模容差的 SW 会话中，只读打开全部原生零件、强制重建并读取实际几何。`default-session.json` 记录这些曲面、孔壁和特征数据，以及检查图哈希和 CAD 文件未改变的检查结果。

检查内容包括：

- 原生实体 `Check3` 无错误，单零件为一个实体，特征与配合无错误，必需特征未被压缩。
- 控制点误差不超过 \(10^{-7}\rm\,mm\)，归一化节点误差不超过 \(10^{-11}\)；G3 切向残差小于 \(10^{-9}\)，曲率及曲率弧长导数残差小于 \(10^{-8}\)。
- 实际包围尺寸、水平平面高度、内外直壁平面位置、内外锥面厚度及锥角符合公式。
- 全部孔壁的轴线与半径匹配独立孔位公式；实体边界 Euler 特征检查贯穿孔拓扑。
- 功能接口完整控制点、节点、所在前后侧与位置符合源轮廓。
- 壳体高度增加 2 mm、顶部厚度增加 0.5 mm、接口上移 1 mm；Studio 背孔直径变为 1.6 mm、行对数变为 12。
- 底座高度增加 1 mm、锥角增加 5°；Mini 孔宽改为 2.2 mm、孔数改为 96；Studio 底孔直径改为 1.6 mm、每圈 200 孔、总圈数 6。
- 所有参数恢复标称值，强制重建、保存、关闭、原生重开后重复检查；装配单独验证底座增高 1 mm 时的配合联动。

在项目根目录执行：

```powershell
./solidworks/run.ps1 -Output ./results/SW -Evidence ./validation/solidworks-native
./solidworks/review.ps1
python -B solidworks/verify.py
```

依赖 SolidWorks 2025、其官方 Interop SDK、默认 `gb_part.prtdot` 与 `gb_assembly.asmdot`、.NET Framework 编译器，以及项目 Python 依赖。构建脚本创建独立隐藏的 SW 会话，临时在当前用户下注册进程内构建组件，并在结束时撤销注册、恢复设置、关闭该会话。保存的原生零件使用 SW 自带特征，编辑时不依赖构建组件。

`-Mode plain`、`housing`、`base`、`assembly` 可分组生成；`thin` 生成两件 1 mm 薄片；例如 `-Mode mac-mini-2-base` 生成一件底座。`-Mode preview` 从已保存的原生文件生成验收视图，并核对 CAD 哈希不变。`-SkipPrepare` 复用校验过哈希的构造参考；`-CompileOnly` 仅检查原生组件编译。构建工作文件位于 `.tmp/solidworks-native`，完整验收通过后可删除；正式模型和验收证据应保留。

`-Mode revalidate` 打开现有的 16 个原生零件，实际执行与生成时相同的参数修改、恢复、保存和原生重开检查，再建立四个关联装配体，并更新读回证据。几何构造规则变化时应先重建受影响零件。该模式直接操作并检查真实原生特征；证据中的源码绑定对应本次执行的构造及验收组件。

本机没有 NX，交付不含 NX 原生 `.prt`。Parasolid 交换文件仍位于 `results/X_T`，其转换验收与 SW 原生特征验收分别记录。
