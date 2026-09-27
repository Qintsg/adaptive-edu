#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
验证公开数据转换的标签、时间场次和学习者边界。
@Project : adaptive-edu
@File : test_prepare_mefkt_expanded_data.py
@Author : Qintsg
@Date : 2026-09-24
'''

from __future__ import annotations

import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from prepare_mefkt_expanded_data import append_ednet, append_junyi, load_ednet_questions, load_junyi_content, token


FIELDS = ["user_id", "item_id", "timestamp", "correct", "response_time_seconds", "subject_id",
          "skill_ids", "course_name", "item_text", "skill_texts", "language", "difficulty",
          "part", "deployed_at", "bundle_id", "episode_id"]


class ExpandedDataTests(unittest.TestCase):
    """小型官方格式夹具，不下载数据即可验证转换规则。"""

    def test_ednet_uses_metadata_answer_and_bundle(self) -> None:
        """同一 EdNet bundle 的题目应共享因果场次。

        :returns: None。
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "kt1.zip", "w") as archive:
                archive.writestr("KT1/u1.csv", "timestamp,solving_id,question_id,user_answer,elapsed_time\n"
                                 "2000,7,q1,b,1000\n2001,7,q2,c,2000\n")
            with zipfile.ZipFile(root / "contents.zip", "w") as archive:
                archive.writestr("contents/questions.csv", "question_id,bundle_id,explanation_id,correct_answer,part,tags,deployed_at\n"
                                 "q1,b1,e1,b,3,1;2,1000\nq2,b1,e1,a,3,2,1000\n")
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            with zipfile.ZipFile(root / "kt1.zip") as kt1, zipfile.ZipFile(root / "contents.zip") as contents:
                summary = append_ednet(writer, kt1, load_ednet_questions(contents), 1)
            rows = list(csv.DictReader(io.StringIO(output.getvalue())))
            self.assertEqual(summary["events"], 2)
            self.assertEqual([row["correct"] for row in rows], ["1", "0"])
            self.assertEqual(rows[0]["episode_id"], rows[1]["episode_id"])
            self.assertEqual(rows[0]["skill_ids"], "ednet:tag:1;ednet:tag:2")

    def test_junyi_sorts_user_and_masks_same_time_slot(self) -> None:
        """Junyi 同时间槽作答须在同一场次，并按学习者连续输出。

        :returns: None。
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "junyi.zip", "w") as archive:
                archive.writestr("Info_Content.csv", "ucid,content_pretty_name,content_kind,difficulty,subject,learning_stage,level4_id\n"
                                 "c1,加法,Exercise,normal,math,elementary,l1\n")
                archive.writestr("Log_Problem.csv", "timestamp_TW,uuid,ucid,problem_number,is_correct,total_sec_taken\n"
                                 "2019-05-01 21:15:00 UTC,b,c1,2,True,12\n"
                                 "2019-05-01 21:00:00 UTC,a,c1,1,False,10\n"
                                 "2019-05-01 21:00:00 UTC,a,c1,2,True,15\n")
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            with zipfile.ZipFile(root / "junyi.zip") as archive:
                summary = append_junyi(writer, archive, load_junyi_content(archive), 1, root / "sort.sqlite", 200)
            rows = list(csv.DictReader(io.StringIO(output.getvalue())))
            self.assertEqual(summary["users"], 2)
            self.assertEqual(summary["events"], 3)
            a_rows = [row for row in rows if row["user_id"] == f"junyi:{token('a')}"]
            self.assertEqual(len(a_rows), 2)
            self.assertEqual(a_rows[0]["episode_id"], a_rows[1]["episode_id"])
            self.assertEqual(len({row["user_id"] for row in rows}), 2)
            self.assertEqual(rows[0]["difficulty"], "medium")

    def test_junyi_drops_unsplittable_coarse_time_slot(self) -> None:
        """过长的粗时间槽不可拆开，否则后段会看见前段标签。

        :returns: None。
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "junyi.zip", "w") as archive:
                archive.writestr("Info_Content.csv", "ucid,content_pretty_name,content_kind,difficulty,subject,learning_stage,level4_id\n"
                                 "c1,加法,Exercise,easy,math,elementary,l1\n")
                rows = ["timestamp_TW,uuid,ucid,problem_number,is_correct,total_sec_taken"]
                rows.extend(f"2019-05-01 21:00:00 UTC,a,c1,{index},True,10" for index in range(3))
                rows.append("2019-05-01 21:15:00 UTC,a,c1,4,False,10")
                archive.writestr("Log_Problem.csv", "\n".join(rows) + "\n")
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            with zipfile.ZipFile(root / "junyi.zip") as archive:
                summary = append_junyi(writer, archive, load_junyi_content(archive), 1, root / "sort.sqlite", 2)
            self.assertEqual(summary["oversize_slots_dropped"], 1)
            self.assertEqual(summary["oversize_events_dropped"], 3)
            self.assertEqual(summary["events"], 1)


if __name__ == "__main__":
    unittest.main()
