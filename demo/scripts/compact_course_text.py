# -*- coding: UTF-8 -*-
# 文件描述：精简大数据课程知识点的重复说明。
# 项目：adaptive-edu；文件：compact_course_text.py；作者：Qintsg；日期：2026-10-29。

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "adaptive_edu_api.settings")

import django

django.setup()

from django.db import transaction
from courses.models import Course
from knowledge.models import KnowledgePoint


REPEATED_SENTENCES = (
    "需要掌握常用命令、API 或实验步骤，并能在课程环境中完成可复现操作。",
    "需要从设计目标、技术优势、适用场景和局限性等角度理解该知识点。",
    "学习时需要理解其核心概念、关键流程、典型场景和与上下游知识点的关系。",
    "该内容服务于课程能力目标，学生应能够说明其基本含义、关键机制和应用价值，并在相关实验或案例中完成识别、分析与应用。",
)


def main() -> None:
    """删除课程描述中重复的教学说明。

    :returns: 无。
    """
    course = Course.objects.get(name="大数据技术与应用")
    changed: list[KnowledgePoint] = []
    removed_characters = 0
    for point in KnowledgePoint.objects.filter(course=course):
        original = point.description or ""
        revised = original
        for sentence in REPEATED_SENTENCES:
            revised = revised.replace(sentence, "")
        revised = revised.strip()
        if revised != original:
            if not revised:
                raise ValueError(f"知识点描述为空：{point.name}")
            point.description = revised
            changed.append(point)
            removed_characters += len(original) - len(revised)
    with transaction.atomic():
        KnowledgePoint.objects.bulk_update(changed, ["description"])
    print(f"updated_points={len(changed)} removed_characters={removed_characters}")


if __name__ == "__main__":
    main()
