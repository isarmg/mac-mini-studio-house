# 使用手册

所有命令在项目根目录运行。CLI：`python -m macfit --help`。

## 命令

| 命令 | 作用 | 默认目录 |
|---|---|---|
| `doctor` | 检查依赖和两份 USDZ 指纹 | `data/input` |
| `run` | 拟合、导出、数值/CAD 验证、高度变化试验和绘图 | `.tmp/refit` |
| `verify` | 只读验证已有结果，不改文件 | `results/fitting/reference` |
| `plot` | 根据已有结果重绘图片，不重新拟合 | `.tmp/refit` |
| `height` | 重新进行低阶高度变化试验，不修改 CAD | `.tmp/refit` |
| `integrity` | 只读核验正式文件 SHA-256 | `fit_reference_manifest.json` |

`run/verify/plot/height` 均支持 `--model mini`、`--model studio` 或 `--model both`。读入结果的命令使用 `--results`；`run` 使用 `--output`。

```powershell
python -m macfit run --model both --output results/work
python -m macfit verify --results results/work
python -m macfit plot --results results/work
python -m macfit height --results results/work
```

工作目录非空时 `run` 会要求指定新目录或加 `--overwrite`。该选项只更新生成文件，不递归删除目录。正式版本目录禁止通过 `run/plot/height` 修改。

`run --input-dir` 可指定源文件目录，但文件名和 SHA-256 必须符合 `configs/models.json`。当前协议仅支持配置中的两个资产，不自动猜测其他 USDZ 的外壳。

## 结果内容

| 文件 | 用途 |
|---|---|
| `optimized_sidewall_raw.3dm` | 原尺度参考侧壁与开孔边界 |
| `optimized_sidewall_nominal.3dm` | 水平统一标定为 127 / 197 mm 的参考侧壁 |
| `optimized_report.json` | 选中模型、参数、各截面误差、G3 指标与限制 |
| `model_comparison.json` | 四种候选在共同数据上的评分 |
| `opening_boundaries.json` | 源世界坐标下的孔/面板闭合边界 |
| `section_*.csv` | 观测点、有效标记、补线距源数据的距离、孔遮罩 |
| `control_points_mm.csv` | 控制点，不是曲线上插值点 |
| `usd_audit.json` | 全部源 Mesh、单位、变换和 Prim 信息 |
| `height_dependence.json` | 是否有证据加入高度变化场 |
| `verification.json` | 拟合参考的验收记录 |
| `run_info.json` | 版本、依赖、输入指纹、配置指纹及运行时间 |
| `comparison.png` / `sidewall_preview.png` | 数值比较与三维边界预览 |

## Rhino 图层及坐标

- `Optimized_G3_outline`：闭合轮廓。
- `Sidewall_NURBS`：未裁孔中段参考侧壁。
- `Opening_boundaries_REFERENCE`：源开口的红色闭合参考边界。
- `Source_reference`：原尺度的 50% 高度截面。

单位为 mm。Rhino X/Y 对应 USD X/Z；Rhino Z 对应 USD Y，Z=0 位于保留侧壁区的下边界。源坐标中心和保留高度范围写在报告中。

公称版只缩放水平轮廓和孔边水平坐标，竖向高度保持不变；灰色源截面仍保留原尺度。红色边界可能部分超出保留高度，属于完整源边界参考，不代表该处已有实体。

在 Rhino 中可以用 `Check`、`What`、`CurvatureGraph` 查看结构。不要将控制点 CSV 当作插值点重建，否则曲线会改变。

## 安装和常见问题

已验证 Python 3.14.3 x64，依赖版本见 `requirements.txt`。推荐独立 venv，不依赖安装 Rhino 所附带的 Python。

当前电脑 `.vendor` 中包含 rhino3dm。独立安装可直接在 venv 中安装依赖。若报告 rhino3dm 不完整或不可读，应检查依赖目录的读取权限，或使用正常用户权限下的独立 venv。

`integrity` 报告 Changed 表示正式文件和发布指纹不同，可能是编辑或重生成造成的，并不自动等于几何损坏。保留改动并生成下一版本，不要直接改校验文件掩盖变化。

`verify` 使用 Python 断言执行验收，不允许 `python -O`。验证失败会以非零退出码结束。
