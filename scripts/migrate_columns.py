"""
列名迁移脚本 (ADR-0004)

将所有 judged/raw parquet 文件:
  - Yield1 -> Project (NULL -> "967E1")
  - Yield2 -> Vendor (NULL -> "LY")
  - CFG    -> Line (数据不变)

原始文件备份到 data/archive/<原名>
幂等: 已迁移的文件跳过备份但仍检查 NULL
"""
import shutil
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.compute as pc

RENAME_MAP = {
    # 旧名
    "Yield1": "Project",
    "Yield2": "Vendor",
    "CFG": "Line",
    # 新文件的别名 (新同事上传用了不同名字)
    "Project Code": "Project",
    "Vendor Code": "Vendor",
}

FILL_MAP = {
    "Project": "967E1",
    "Vendor": "LY",
}


def migrate_file(path: Path, archive_dir: Path) -> dict:
    result = {"file": path.name, "renamed": [], "filled": 0, "backed_up": False, "rows": 0}
    pf = pq.ParquetFile(path)
    schema = pf.schema_arrow
    old_names = set(RENAME_MAP.keys())

    # 决定是否要备份 (有旧列名才备份)
    has_old = bool(set(schema.names) & old_names)

    # 读数据
    table = pf.read()
    pf.close()

    # 构造新列名列表
    new_names = []
    for name in schema.names:
        if name in old_names:
            new_names.append(RENAME_MAP[name])
            result["renamed"].append(f"{name}->{RENAME_MAP[name]}")
        else:
            new_names.append(name)

    # 构造新 table
    new_columns = {}
    for i, col_name in enumerate(schema.names):
        new_col_name = new_names[i]
        col_data = table.column(i)
        if new_col_name in FILL_MAP:
            fill_val = FILL_MAP[new_col_name]
            # 旧列可能是 float64, 不能直接填字符串
            if col_data.type != pa.string():
                col_data = pc.cast(col_data, pa.string(), safe=False)
            try:
                null_count = pc.sum(pc.is_null(col_data)).as_py() or 0
            except Exception:
                null_count = 0
            if null_count > 0:
                col_data = pc.fill_null(col_data, fill_val)
                result["filled"] += null_count
        new_columns[new_col_name] = col_data

    # 补缺失列: 如果新表没有 Project/Vendor 列, 加一个全填默认值的列
    for fill_name, fill_val in FILL_MAP.items():
        if fill_name not in new_columns:
            new_columns[fill_name] = pa.array([fill_val] * len(table), type=pa.string())
            result["renamed"].append(f"<新增> {fill_name}={fill_val}")
            new_names.append(fill_name)

    new_table = pa.table(new_columns)
    result["rows"] = len(new_table)

    # 备份
    if has_old:
        archive_path = archive_dir / path.name
        if not archive_path.exists():
            shutil.copy2(path, archive_path)
        result["backed_up"] = True

    # 写回 (atomic)
    tmp_path = path.with_suffix(".parquet.tmp")
    pq.write_table(new_table, str(tmp_path))
    os.replace(tmp_path, path)
    return result


def main():
    project_root = Path(__file__).resolve().parent.parent
    data_raw = project_root / "data" / "raw"
    data_judged = project_root / "data" / "judged"
    archive_dir = project_root / "data" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    all_files = sorted(list(data_raw.glob("*.parquet")) + list(data_judged.glob("*.parquet")))
    if not all_files:
        print("没有要迁移的文件")
        return

    print(f"将迁移 {len(all_files)} 个 parquet 文件\n")
    total_filled = 0
    for path in all_files:
        try:
            r = migrate_file(path, archive_dir)
        except Exception as e:
            print(f"  X {path.name}: {e}")
            continue
        size_mb = os.path.getsize(path) / 1024 / 1024
        status = "备份+重命名" if r["backed_up"] else "仅填NULL"
        print(f"  - {path.parent.name}/{r['file']} ({size_mb:.1f}MB, {r['rows']:,}行) [{status}]")
        if r["renamed"]:
            print(f"      rename: {', '.join(r['renamed'])}")
        if r["filled"] > 0:
            print(f"      fill: {r['filled']} NULL -> 填充")
            total_filled += r["filled"]
    print(f"\nOK 迁移完成, 共填 {total_filled} 个 NULL, 备份在 {archive_dir}/")


if __name__ == "__main__":
    main()
