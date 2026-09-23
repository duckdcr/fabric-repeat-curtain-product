---
name: fabric-repeat-curtain-product
description: 独立生成素色或完整花位面料的双捏褶窗帘成品，支持文件夹扫描、素色筛选、批量渲染和生成统计。适用于 detail_10/detail_15 细节图，无需外层项目或人工审核文件。
---

# 独立窗帘成品生成

所有渲染脚本、模板、蒙版和 UV 文件均随此 skill 打包。只需要 Python 3.10+、NumPy 和 Pillow。无需外层项目、其他 skill、GPU、网络生图 API、人工确认或融合审核文件。

## 环境

在任意位置使用脚本的绝对路径，素材始终从此 skill 的 `assets/` 读取。

```powershell
python -m pip install -r "<skill>/requirements.txt"
python "<skill>/scripts/check_environment.py"
```

已有依赖时无需重复安装。保留原始细节图，工作文件放在独立临时目录。正式成品为 `<SKU>_double-pinch.webp`，2880×2880、RGB、无损 WebP。

## 文件夹流程：先分类，再生成，不等人工审核

扫描是文件枚举，不是图像识别。不要将扫描到的所有文件默认标为素色，也不要为所有文件伪造 `/` 目录记录。

1. 运行扫描脚本，生成带序号的原图联系表和 `classification.csv`。默认扫描一层，子文件夹使用 `--recursive`。
2. 由执行 skill 的视觉能力查看原图联系表，按行号填分类；有疑问时查看原始图片。直接完成分类，不向用户请求审核通过。
3. 填 `category`：`plain` 为素色或细密、均匀织纹；`large-pattern` 为明显花卉、山水、器物、大幅图案等；无法确定填 `uncertain` 并说明原因。扫描发现无效输入填 `invalid`。
4. 没有 CSV、没有完整花位图且用户只要素色时，运行 `--plain-only`。大花纹、未知分类和无效输入均跳过，并写入统计。JLW828551 和 JLW828559 是既往大花纹实例，不是代替原图分类的固定 SKU 黑名单。
5. 批处理完成即交付成品与 `生图统计表.csv`。CSV 为 UTF-8 BOM，可直接用 Excel 打开，含成功、跳过、失败和原因。仅在用户指定 XLSX 时另外转换为 XLSX，不把 CSV 改扩展名冒充 XLSX。

```powershell
python "<skill>/scripts/scan_fabrics.py" "<细节图目录>" --work-dir "<临时工作目录>"
# 执行者根据原图填好临时工作目录中的 classification.csv，不需要用户审核。
python "<skill>/scripts/batch.py" "<细节图目录>" --classification "<临时工作目录>/classification.csv" --plain-only --output-dir "<输出目录>"
```

分类字段和有花型批处理见 [catalog-routing.md](references/catalog-routing.md)。脚本本身不带机器视觉模型；直接在命令行运行扫描后，空分类不会被当作素色生成。

## 单张素色

已根据原图确定为素色或细密织纹时，可直接用 `--plain`，不需要 CSV。

```powershell
python "<skill>/scripts/render_curtain_delivery.py" "<SKU>_detail_15.jpg" --plain --output-dir "<输出目录>"
```

`_detail_10` / `_detail_15` 表示正方形照片实际覆盖的厘米边长，不是花位尺寸。文件名保留不同照片的（1）/（2）标记。`--plain` 是调用者的分类声明，不是大花纹转换成素色的功能。

## 完整花位

直接输入完整花位图与真实宽高，不需要融合审核 JSON，不等待审核，不强制调用其他 skill。可选 `--fused-master` 接收已有完整花位母版。程序不会自动把细节照片融合进完整花位图，也不会从局部细节恢复缺失图案；默认使用提供的完整花位图本身的颜色和纹理。

```powershell
python "<skill>/scripts/render_curtain_delivery.py" "<SKU>_detail_15.jpg" --complete-repeat "<完整花位图>" --repeat-width-cm 70 --repeat-height-cm 64 --output-dir "<输出目录>"
```

上例 70/64 仅示例，实际必须使用用户给定尺寸。也可用 `--catalog "<目录.csv>"`，默认 `长` 为花位高、`宽` 为花位宽。CSV 双 `/` 走素色；双正数走完整花位；部分、缺失、冲突、非正数不生成。显式尺寸不能覆盖冲突目录数据。目录有花位但缺完整图时跳过，不降级为素色。细节图不能当完整花位源。

更多说明见 [fusion-contract.md](references/fusion-contract.md)。

## 固定生成行为

- 素色：保留 193.9×270 cm 单片展开尺寸、两片、九个 73% 源窗口、18% 最小误差重叠、固定种子、不翻转不旋转；先做乘性低频 RGB 光照校正。
- 完整花位：使用 560×280 cm 连续布卷、两片各 280 cm，跨中缝连续，不镜像或随机偏移。
- 两条路线自动按真实模板轮廓裁切；模板灰度 <245 与蒙版相交，清除侧边、底摆、中缝外纹理，保持原画布和白底。
- 尺寸、可读性、纯白背景属于自动文件校验；不设置人工审核关卡。不会判断美学质量或证明局部图包含完整花位。
- 默认不覆盖已存在成品；只有用户要求替换才使用 `--overwrite`。批处理遇到同名成品会跳过并记录；重名 SKU 导致输出冲突时停止批次。
- 正式目录只放成品和统计表。中间图、分类表与自动诊断留在临时工作区。详见 [output-audit.md](references/output-audit.md)。

## 便携验证

```powershell
python "<skill>/scripts/test_standalone.py"
```

验证会将 skill 复制到独立临时目录，从不相关的工作目录启动，实际运行素色、完整花位和跳过流程；不修改用户成品。
