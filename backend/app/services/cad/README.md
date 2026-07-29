# CAD 解析底座（Task 2）

本目录提供 CAD 文件解析与几何查询能力，统一输出
`app.schemas.cad_intermediate.CADIntermediateModel` 中间表示。

## 子模块

| 模块 | 职责 | 主要依赖 |
|---|---|---|
| `dxf_parser.py` | DXF → CADIntermediateModel | ezdxf |
| `dwg_converter.py` | DWG → DXF | ezdxf.addons.odafc + ODA File Converter |
| `occ_engine.py` | STEP/IGES B-Rep 几何查询 | cadquery-ocp（OCP）或 pythonocc-core（OCC） |
| `freecad_engine.py` | 跨格式转换 + 几何校验（备用引擎） | FreeCAD Python 模块 |

## 外部依赖安装

### 1. ezdxf（pip 直接安装）

```bash
pip install ezdxf==1.4.4
```

PyPI：https://pypi.org/project/ezdxf/
官方文档：https://ezdxf.readthedocs.io/en/stable/

### 2. OCP / pythonOCC（STEP/IGES 几何查询）

**方式 A（推荐，pip 安装 cadquery-ocp）：**

```bash
pip install cadquery-ocp==7.9.3.1.1
```

PyPI：https://pypi.org/project/cadquery-ocp/
- Windows cp313 wheel 可用（截至 2026-07-25）
- 模块名为 `OCP`（导入：`import OCP`）
- CadQuery 维护：https://github.com/CadQuery/OCP

**方式 B（conda 安装 pythonocc-core）：**

```bash
conda install -c conda-forge pythonocc-core=7.8.1.1
```

- 模块名为 `OCC`
- 官方仓库：https://github.com/tpaviot/pythonocc-core

`occ_engine.py` 同时支持上述两种后端，优先用 `OCP`，缺失时回退 `OCC`，
两者都不可用时 `is_occ_available()` 返回 False，所有几何查询函数抛出
`OCCEngineNotAvailableError`。

### 3. ODA File Converter（DWG → DXF 转换）

ODA File Converter **不能通过 pip 安装**，需注册下载：

1. 访问 https://www.opendesign.com/guestfiles/oda_file_converter 注册账号
2. 下载 Windows/Linux/macOS 版本并安装
3. Windows 默认安装路径：
   `C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe`
4. 配置环境变量（任选其一）：
   - 设置环境变量 `ODAFC_PATH` 指向 `ODAFileConverter.exe` 完整路径
   - 或将 ODAFileConverter 所在目录加入 `PATH`
5. 验证：`python -c "from app.services.cad import is_odafc_available; print(is_odafc_available())"`

官方文档：https://ezdxf.readthedocs.io/en/stable/addons/odafc.html

未安装时 `is_odafc_available()` 返回 False，
`dwg_to_dxf()` 抛出 `ODANotAvailableError`，不影响 DXF 解析与其他引擎使用。

### 4. FreeCAD（备用引擎：跨格式转换 + 几何校验）

FreeCAD 作为 Python 模块需要手动配置 PYTHONPATH：

1. 下载安装：https://www.freecadweb.org/downloads.php
2. Windows：找到 FreeCAD 安装目录（含 `FreeCAD.pyd`、`bin`、`lib`、`Mod`、`Ext`）
3. 将该目录加入 `PYTHONPATH`，或将 `bin` 目录加入 `PATH`，重启 Python
4. 验证：`python -c "import FreeCAD; print(FreeCAD.Version())"`

官方文档：https://wiki.freecadweb.org/Embedding_FreeCAD

未安装时 `is_freecad_available()` 返回 False，相关函数抛出
`FreeCADNotAvailableError`。

## 公共接口

```python
from app.services.cad import (
    # DXF 解析
    parse_dxf_to_intermediate,
    CADParseError,
    # DWG 转换
    dwg_to_dxf,
    is_odafc_available,
    ODANotAvailableError,
    # OCC 几何查询
    read_step_file,
    get_bounding_box,
    get_volume,
    get_surface_area,
    check_interference,
    is_occ_available,
    OCCEngineNotAvailableError,
    # FreeCAD 备用引擎
    convert_format,
    validate_geometry,
    is_freecad_available,
    FreeCADNotAvailableError,
)
```

## 统一中间表示

下游审图（Task 4）/生成（Task 5）模块消费 `CADIntermediateModel`：

```python
from app.schemas.cad_intermediate import CADIntermediateModel
```

字段定义详见 `app/schemas/cad_intermediate.py`。

## 测试

```bash
cd backend
pytest tests/test_cad_parser.py -v
```

测试 fixture 通过 `tests/fixtures/generate_sample_dxf.py` 重新生成：
```bash
python tests/fixtures/generate_sample_dxf.py
```
