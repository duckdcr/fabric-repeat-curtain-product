# 输入和分类

文件名接受 `<SKU>_detail_10` 或 `<SKU>_detail_15`，格式 JPG/JPEG/PNG/WebP，照片应为正方形。10/15 是照片的厘米边长。默认扫描一层，`--recursive` 才扫描子目录。无效文件也进入统计。

## 分类 CSV（不是目录 CSV，也不是审核文件）

由 `scan_fabrics.py` 产生，执行者依据原图填入 `category`，不等待用户批准。脚本只做枚举与执行，不内置视觉分类器。

| 字段 | 含义 |
|---|---|
| file | 相对于输入目录的文件路径，保留原始文件名，不允许目录外路径 |
| category | plain / large-pattern / uncertain / invalid；空值跳过 |
| reason | 分类或跳过理由 |
| complete_repeat | 可选完整花位图路径，绝对路径或相对于分类 CSV |
| fused_master | 可选已有完整花位母版路径，与 complete_repeat 相同路径规则 |
| repeat_width_cm | 可选真实花位宽（厘米） |
| repeat_height_cm | 可选真实花位高（厘米） |

有花型的批次去掉 `--plain-only`，提供目录 CSV 或在分类表中填写真实花位宽高，以及完整花位图/已有母版。没有花位资产的大花纹跳过。分类与目录冲突不能改为素色。

## 可选目录 CSV

默认列名 `SKU`、`长`、`宽`，支持 `--sku-column`、`--length-column`、`--width-column`。UTF-8 BOM/UTF-8，失败后尝试 GB18030。SKU 压缩空白并忽略 ASCII 英文大小写，不模糊匹配。

- 长/宽均 `/` 或 `／`：素色路线，但原图分类为大花纹时仍不允许按素色批处理。
- 长/宽均有限正数：完整花位，长→高，宽→宽。
- 混合、空白、缺行、零、负数、NaN、无穷大、重复冲突记录：报告错误。
- 没有目录 CSV 时，素色用 `--plain` 或已分类的批处理，不编造目录数据。
