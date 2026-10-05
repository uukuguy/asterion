from __future__ import annotations

import unittest

from asterion.applications.prime.p7 import cognition_narrative


class TestP7ColorNames(unittest.TestCase):
    def test_direct_palette_labels_reject_non_palette_values(self):
        self.assertEqual(cognition_narrative.color_label(9), "蓝色（9）")
        for invalid in (-1, 16, True, "9"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                cognition_narrative.color_label(invalid)

    def test_adds_official_palette_names_to_explicit_color_references(self):
        describe = cognition_narrative.describe_color_names_zh
        names = ("白", "浅灰", "灰", "深灰", "炭灰", "黑", "品红", "粉", "红", "蓝", "浅蓝", "黄", "橙", "暗红", "绿", "紫")
        for color_id, name in enumerate(names):
            for source in (f"颜色{color_id}", f"{color_id}色", f"color-{color_id}"):
                with self.subTest(source=source):
                    self.assertEqual(describe(source), f"{name}色（{color_id}）")

    def test_grouped_references_and_existing_names_are_idempotent(self):
        describe = cognition_narrative.describe_color_names_zh
        for source in ("颜色4、6、11结构", "4、6、11色结构"):
            with self.subTest(source=source):
                result = describe(source)
                self.assertEqual(result, "炭灰色（4）、品红色（6）、黄色（11）结构")
                self.assertEqual(describe(result), result)
        self.assertEqual(describe("蓝色（9）横条"), "蓝色（9）横条")
        self.assertEqual(describe("蓝色颜色9横条"), "蓝色（9）横条")
        for source in ("蓝色（颜色9）横条", "蓝色(color-9)横条", "蓝色（9色）横条"):
            with self.subTest(source=source):
                self.assertEqual(describe(source), "蓝色（9）横条")

    def test_other_numbers_and_unrecognized_english_are_preserved(self):
        describe = cognition_narrative.describe_color_names_zh
        source = "64×64网格，20×4横带，ACTION4，坐标(12,16)，颜色16，color-64。"
        self.assertEqual(describe(source), source)
        self.assertEqual(describe("The color-9 bar may move."), "The 蓝色（9） bar may move.")
        narrative = cognition_narrative.render_cognition_narrative_zh({"natural_language_context": "The color-9 bar may move."}, None)
        self.assertIn("〔历史原文，尚未中文复述〕The 蓝色（9） bar may move.", narrative)
