from src.processing.content import select_content, split_content


def test_split_content_separates_appended_comments() -> None:
    parts = split_content("Article body\n\n--- Top Comments ---\n\nUseful reply")

    assert parts.main == "Article body"
    assert parts.comments == "Useful reply"


def test_prefix_sampling_preserves_existing_behavior() -> None:
    content = "0123456789" * 100

    assert select_content(content, 500, "prefix") == content[:500]


def test_head_middle_tail_sampling_preserves_article_ending() -> None:
    content = "A" * 1000 + "MIDDLE-MARKER" + "B" * 1000 + "ENDING-MARKER"

    selected = select_content(content, 600, "head-middle-tail")

    assert len(selected) <= 600
    assert selected.startswith("[Opening excerpt]")
    assert "MIDDLE-MARKER" in selected
    assert selected.endswith("ENDING-MARKER")
