# 当前测试和发布

在本项目目录运行：

```powershell
python -m macfit doctor
python -m unittest discover -s tests -v
python -m macfit verify
python -m macfit integrity
```

`test_core.py` 检查源数据指纹、开孔拓扑、G3、对称、孔遮罩与冻结保护；`test_release.py` 检查当前冻结轮廓与参考侧壁。`integrity` 核对 `fit_reference_manifest.json` 所列的参考输入和结果。

完整重新拟合可运行 `python -m macfit run --model both --output .tmp/refit`，再使用 `python -m macfit verify --results .tmp/refit` 验证。拟合数值与当前基准比较，PNG/3DM 文件无需字节相同。正式轮廓基准受覆盖保护。

8 个实体由 `python tools/build_nominal_solids.py --replace` 构建并进入共享严格发布流程。实体的 STEP、3DM、X_T 原生曲面及指定接缝 G3 验收与参考侧壁验证分别记录；从总目录运行 `python tools/audit_delivery.py` 核对当前发布与最终设计证据。

严格转换与发布保护测试从总目录运行 `python -m unittest discover -s tools -p 'test_exact_*.py' -v`。临时构建、测试、预览文件可以删除，不是现行流程的预先输入。参考观察误差不代替实物测量。
