"""前端资源的约定（回归保护）。

日报详情页的锚点跳转踩过一个坑：条目锚点是 ``<p><a id="item-1"></a></p>``，
如果这条规则写成 ``display: none``，锚点就没有盒子，浏览器滚不到它，
目录里的链接点了「没反应」。所以这里把两处约定固定下来：

* ``horizon.css`` 只把空锚点段落压成 0 高度，不用 ``display: none``；
* ``horizon.js`` 自己接管页内锚点点击（preventDefault + 滚动），
  并给外链/「近期消息」标题加上新标签页打开。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "docs" / "assets" / "css" / "horizon.css").read_text(encoding="utf-8")
JS = (ROOT / "docs" / "assets" / "js" / "horizon.js").read_text(encoding="utf-8")


def test_empty_anchor_paragraph_keeps_a_box():
    """锚点段落不能 display:none，否则浏览器无法滚动到该锚点。"""
    assert ".post-detail p:has(> a:not([href]):only-child)" in CSS
    rule = CSS.split(".post-detail p:has(> a:not([href]):only-child)", 1)[1].split("}", 1)[0]
    assert "display: none" not in rule
    assert "height: 0" in rule


def test_scroll_targets_leave_room_for_the_sticky_nav():
    assert ".post-detail .hz-item { scroll-margin-top:" in CSS
    assert ".post-detail h3 { scroll-margin-top:" in CSS


def test_anchor_click_is_handled_by_the_page():
    assert "function handleAnchorClick" in JS
    assert "event.preventDefault()" in JS
    assert "window.history.pushState" in JS
    assert "addEventListener('hashchange'" in JS


def test_item_titles_open_in_a_new_tab():
    assert "function setupOpenInNewTab" in JS
    assert "'.hz-recent-list a[href]'" in JS
    assert "'_blank'" in JS
    assert "'noopener'" in JS
