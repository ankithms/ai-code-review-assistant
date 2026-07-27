import unittest

from app.services.diff_line_mapper import (
    CommentSide,
    DiffLineMapper,
    LineType,
    MultiFileDiffLineMapper,
)
from app.services.inline_comment_validator import InlineCommentValidator


class DiffLineMapperTests(unittest.TestCase):
    def test_only_added_lines(self):
        mapper = DiffLineMapper(
            "file.txt",
            "@@ -1,2 +1,4 @@\n line one\n+new line\n line two",
        )

        added = mapper.resolve_line_ref("L2")
        self.assertEqual(added.patch_line.line_type, LineType.ADDED)
        self.assertIsNone(added.patch_line.old_line)
        self.assertEqual(added.patch_line.new_line, 2)
        self.assertEqual(added.side, CommentSide.RIGHT)
        self.assertTrue(added.patch_line.is_commentable)
        self.assertEqual(added.github_line, 2)

    def test_only_deleted_lines(self):
        mapper = DiffLineMapper(
            "file.txt",
            "@@ -1,3 +1,1 @@\n line one\n-deleted line\n-line three",
        )

        deleted = mapper.resolve_line_ref("L2")
        self.assertEqual(deleted.patch_line.line_type, LineType.DELETED)
        self.assertEqual(deleted.patch_line.old_line, 2)
        self.assertIsNone(deleted.patch_line.new_line)
        self.assertEqual(deleted.side, CommentSide.LEFT)
        self.assertEqual(deleted.github_line, 2)

    def test_mixed_additions_and_deletions(self):
        mapper = DiffLineMapper(
            "calculator.py",
            "@@ -8,4 +8,7 @@ def calculate_total(items):\n"
            "     total = 0\n"
            "-    return total\n"
            "+    for item in items:\n"
            "+        total += item.price\n"
            "+    return total",
        )

        self.assertEqual(mapper.resolve_line_ref("L2").patch_line.old_line, 9)
        self.assertEqual(mapper.resolve_line_ref("L2").side, CommentSide.LEFT)
        self.assertEqual(mapper.resolve_line_ref("L3").patch_line.new_line, 9)
        self.assertEqual(mapper.resolve_line_ref("L5").patch_line.new_line, 11)

    def test_multiple_hunks_in_one_file(self):
        mapper = DiffLineMapper(
            "file.txt",
            "@@ -1,2 +1,2 @@\n line one\n+new two\n"
            "@@ -20,2 +20,3 @@\n line twenty\n+new twenty-one",
        )

        self.assertEqual(mapper.resolve_line_ref("L2").patch_line.new_line, 2)
        self.assertEqual(mapper.resolve_line_ref("L4").patch_line.new_line, 21)

    def test_hunk_without_explicit_counts(self):
        mapper = DiffLineMapper("file.txt", "@@ -1 +1 @@\n-old\n+new")

        self.assertEqual(mapper.resolve_line_ref("L1").patch_line.old_line, 1)
        self.assertEqual(mapper.resolve_line_ref("L2").patch_line.new_line, 1)

    def test_context_lines_are_right_side_commentable(self):
        mapper = DiffLineMapper("file.txt", "@@ -8,2 +8,2 @@\n context\n+added")

        context = mapper.resolve_line_ref("L1")
        self.assertEqual(context.patch_line.line_type, LineType.CONTEXT)
        self.assertEqual(context.patch_line.old_line, 8)
        self.assertEqual(context.patch_line.new_line, 8)
        self.assertEqual(context.side, CommentSide.RIGHT)

    def test_blank_added_and_deleted_lines_are_commentable(self):
        mapper = DiffLineMapper("file.txt", "@@ -1,2 +1,2 @@\n-\n+")

        deleted_blank = mapper.resolve_line_ref("L1")
        added_blank = mapper.resolve_line_ref("L2")
        self.assertEqual(deleted_blank.patch_line.content, "")
        self.assertTrue(deleted_blank.patch_line.is_commentable)
        self.assertEqual(deleted_blank.side, CommentSide.LEFT)
        self.assertEqual(added_blank.patch_line.content, "")
        self.assertTrue(added_blank.patch_line.is_commentable)
        self.assertEqual(added_blank.side, CommentSide.RIGHT)

    def test_no_newline_marker_is_not_commentable(self):
        mapper = DiffLineMapper(
            "file.txt",
            "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new",
        )

        markers = [
            line
            for line in mapper.lines
            if line.line_type == LineType.NO_NEWLINE_MARKER
        ]
        self.assertEqual(len(markers), 1)
        self.assertFalse(markers[0].is_commentable)
        self.assertIsNone(markers[0].line_ref)

    def test_renamed_file_uses_new_filename_namespace(self):
        multi = MultiFileDiffLineMapper.from_files(
            [
                {
                    "filename": "new_name.py",
                    "previous_filename": "old_name.py",
                    "status": "renamed",
                    "patch": "@@ -1 +1 @@\n+value = 1",
                }
            ]
        )

        self.assertIsNotNone(multi.mapper_for_file("new_name.py"))
        self.assertIsNone(multi.mapper_for_file("old_name.py"))

    def test_new_file_old_line_numbers_begin_absent(self):
        mapper = DiffLineMapper("new.py", "@@ -0,0 +1,2 @@\n+one\n+two")

        self.assertIsNone(mapper.resolve_line_ref("L1").patch_line.old_line)
        self.assertEqual(mapper.resolve_line_ref("L1").patch_line.new_line, 1)

    def test_deleted_file_new_line_numbers_are_absent(self):
        mapper = DiffLineMapper("old.py", "@@ -1,2 +0,0 @@\n-one\n-two")

        self.assertEqual(mapper.resolve_line_ref("L1").patch_line.old_line, 1)
        self.assertIsNone(mapper.resolve_line_ref("L1").patch_line.new_line)
        self.assertEqual(mapper.resolve_line_ref("L1").side, CommentSide.LEFT)

    def test_multiple_files_can_share_numeric_lines(self):
        multi = MultiFileDiffLineMapper.from_files(
            [
                {"filename": "a.py", "patch": "@@ -1 +1 @@\n+same"},
                {"filename": "b.py", "patch": "@@ -1 +1 @@\n+same"},
            ]
        )

        self.assertEqual(multi.mapper_for_file("a.py").resolve_line_ref("L1").github_line, 1)
        self.assertEqual(multi.mapper_for_file("b.py").resolve_line_ref("L1").github_line, 1)

    def test_large_line_numbers(self):
        mapper = DiffLineMapper("big.py", "@@ -10000,1 +10000,2 @@\n context\n+added")

        self.assertEqual(mapper.resolve_line_ref("L2").patch_line.new_line, 10001)

    def test_missing_patch_is_not_inline_commentable(self):
        mapper = DiffLineMapper("binary.png", None)

        self.assertFalse(mapper.is_inline_commentable)
        self.assertIn("NOT_INLINE_COMMENTABLE", mapper.annotated_diff())

    def test_multiline_comment_range_validation(self):
        multi = MultiFileDiffLineMapper.from_files(
            [{"filename": "file.py", "patch": "@@ -10,2 +10,3 @@\n context\n+one\n+two"}]
        )
        validator = InlineCommentValidator(multi, source_commit_sha="abc", current_head_sha="abc")

        class Issue:
            file_path = "file.py"
            line_ref = "L3"
            start_line = 11
            start_side = "RIGHT"

        result = validator.validate_issue(Issue())

        self.assertTrue(result.valid)
        self.assertEqual(
            result.payload,
            {
                "line": 12,
                "side": "RIGHT",
                "start_line": 11,
                "start_side": "RIGHT",
            },
        )

    def test_annotated_diff_labels_stable_line_ref_separately_from_absolute_lines(self):
        mapper = DiffLineMapper("file.py", "@@ -24,1 +24,3 @@\n context\n+bad\n+line")

        annotated = mapper.annotated_diff()

        self.assertIn("line_ref=L2", annotated)
        self.assertIn("new_file_line=25", annotated)
        self.assertNotIn("NEW:25", annotated)

    def test_validator_accepts_model_returned_new_absolute_line_ref(self):
        multi = MultiFileDiffLineMapper.from_files(
            [{"filename": "file.py", "patch": "@@ -24,1 +24,3 @@\n context\n+bad\n+line"}]
        )
        validator = InlineCommentValidator(multi, source_commit_sha="abc", current_head_sha="abc")

        class Issue:
            file_path = "file.py"
            line_ref = "NEW:25"
            start_line = None
            start_side = None

        result = validator.validate_issue(Issue())

        self.assertTrue(result.valid)
        self.assertEqual(result.payload, {"line": 25, "side": "RIGHT"})


if __name__ == "__main__":
    unittest.main()
