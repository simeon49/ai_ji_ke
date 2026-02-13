#!/usr/bin/env python3
"""
课程标签迁移脚本

为现有课程自动推断并生成分类标签
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.label_manager import get_label_manager


def load_column_info(course_dir: Path) -> dict | None:
    """加载课程的 column_info.json"""
    info_file = course_dir / ".column_info.json"
    if not info_file.exists():
        return None

    try:
        with open(info_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("data", {})
    except Exception as e:
        print(f"  警告: 无法解析 {info_file}: {e}")
        return None


def assign_labels_to_course(course_dir: Path, label_manager) -> bool:
    """为单个课程分配标签"""
    # 加载课程元数据
    course_data = load_column_info(course_dir)
    if not course_data:
        print(f"  跳过: 无 .column_info.json")
        return False

    # 推断标签
    labels = label_manager.infer_labels(course_data)

    # 保存到 .labels.json
    labels_file = course_dir / ".labels.json"
    labels_data = labels.to_dict()
    labels_data["inferred_at"] = datetime.now().isoformat()

    try:
        with open(labels_file, "w", encoding="utf-8") as f:
            json.dump(labels_data, f, ensure_ascii=False, indent=2)
        print(f"  ✓ 方向: {labels.direction_name}, 分类: {', '.join(labels.category_names) if labels.category_names else '无'}")
        return True
    except Exception as e:
        print(f"  错误: 无法保存标签文件: {e}")
        return False


def main():
    """主函数"""
    org_courses_dir = Path("./org_courses")

    if not org_courses_dir.exists():
        print(f"错误: 目录不存在 {org_courses_dir}")
        sys.exit(1)

    print("=" * 60)
    print("课程标签自动分配脚本")
    print("=" * 60)

    # 初始化标签管理器
    try:
        label_manager = get_label_manager()
        print(f"✓ 加载标签配置成功")
        print(f"  方向数量: {len(label_manager.directions)}")
    except Exception as e:
        print(f"错误: 无法加载标签配置: {e}")
        sys.exit(1)

    # 统计
    total_courses = 0
    success_count = 0
    skip_count = 0
    error_count = 0

    # 遍历所有课程目录
    print("\n开始处理课程...")
    print("-" * 60)

    for course_dir in sorted(org_courses_dir.iterdir()):
        if not course_dir.is_dir():
            continue
        if course_dir.name.startswith("."):
            continue

        total_courses += 1
        print(f"\n[{total_courses}] {course_dir.name}")

        try:
            if assign_labels_to_course(course_dir, label_manager):
                success_count += 1
            else:
                skip_count += 1
        except Exception as e:
            print(f"  错误: {e}")
            error_count += 1

    # 统计报告
    print("\n" + "=" * 60)
    print("处理完成!")
    print("=" * 60)
    print(f"总课程数: {total_courses}")
    print(f"成功分配: {success_count}")
    print(f"跳过: {skip_count}")
    print(f"错误: {error_count}")

    if success_count > 0:
        print(f"\n标签文件已生成到各课程目录下的 .labels.json")


if __name__ == "__main__":
    main()
