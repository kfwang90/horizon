(function () {
  'use strict';

  /** Replace ⭐️ N/10 with a colored badge in h2, h3, and li elements */
  function processScoreBadges() {
    var scoreRe = /⭐️\s*(\d+(?:\.\d+)?)\/10/;
    var targets = document.querySelectorAll('.main-content h2, .main-content h3, .main-content li');
    targets.forEach(function (el) {
      var m = el.innerHTML.match(scoreRe);
      if (!m) return;
      var score = parseFloat(m[1]);
      var tier;
      if (score >= 9) tier = 'high';
      else if (score >= 7) tier = 'good';
      else if (score >= 5) tier = 'mid';
      else tier = 'low';
      el.innerHTML = el.innerHTML.replace(
        scoreRe,
        '<span class="score-badge" data-tier="' + tier + '">' + m[1] + '</span>'
      );
    });
  }

  /** Add semantic classes to tag lines, source lines, and background paragraphs */
  function markSemanticElements() {
    var paragraphs = document.querySelectorAll('.main-content p');
    paragraphs.forEach(function (p) {
      var text = p.textContent.trim();

      // Tag line: starts with Tags or 标签 (bold prefix rendered by Markdown)
      if (/^(Tags|标签)\s*:/.test(text)) {
        p.classList.add('tag-line');
        return;
      }

      // Source line: pattern like "source · site · date"
      if (/^(github|hackernews|hn|rss|reddit|telegram|twitter|x|youtube|openbb|ossinsight|gdelt|google[ _]news)\s*·/i.test(text)) {
        p.classList.add('source-line');
        return;
      }
    });
  }

  var INITIAL_ITEMS = 8;
  var ITEMS_PER_EXPAND = 5;

  /** 各板块的分页状态，用于锚点跳转时先把被折叠的条目展开 */
  var sectionStates = [];

  function isZhPage() {
    return (document.documentElement.lang || '').toLowerCase().indexOf('zh') === 0;
  }

  function uiText() {
    return isZhPage()
      ? {
          toc: '目录',
          more: function (remaining) {
            return '显示更多（还有 ' + remaining + ' 条）';
          },
        }
      : {
          toc: 'Contents',
          more: function (remaining) {
            return 'Show ' + remaining + ' more';
          },
        };
  }

  /** 条目起始标记：Horizon 为每条内容生成的 <p><a id="item-..."></a></p> */
  function isItemStart(el) {
    if (!el || el.tagName !== 'P' || el.children.length !== 1) return false;
    var anchor = el.firstElementChild;
    return anchor.tagName === 'A' && !anchor.hasAttribute('href');
  }

  /** 把顶部的目录列表折叠进 <details>，避免展开全部内容后页面被目录占满 */
  function collapseToc(root, text) {
    var firstHeading = root.querySelector('h2');
    if (!firstHeading) return;

    var nodes = [];
    var node = root.firstElementChild;
    while (node && node !== firstHeading) {
      nodes.push(node);
      node = node.nextElementSibling;
    }

    var listIndexes = [];
    nodes.forEach(function (el, index) {
      if (el.tagName === 'OL') listIndexes.push(index);
    });
    if (!listIndexes.length) return;

    var start = listIndexes[0];
    if (start > 0 && nodes[start - 1].tagName === 'P') start -= 1;
    var tocNodes = nodes.slice(start, listIndexes[listIndexes.length - 1] + 1);

    var details = document.createElement('details');
    details.className = 'hz-toc';
    var summary = document.createElement('summary');
    summary.textContent = text.toc;
    details.appendChild(summary);

    tocNodes[0].parentNode.insertBefore(details, tocNodes[0]);
    tocNodes.forEach(function (el) { details.appendChild(el); });
  }

  /** 每个板块默认显示 8 条，点「显示更多」每次再展开 5 条 */
  function paginateSections(root, text) {
    var sections = [];
    var current = null;
    Array.prototype.forEach.call(root.children, function (el) {
      if (el.tagName === 'H2') {
        current = [];
        sections.push(current);
      } else if (current) {
        current.push(el);
      }
    });

    sections.forEach(function (nodes) {
      var groups = [];
      var group = null;
      nodes.forEach(function (el) {
        if (isItemStart(el)) {
          group = [];
          groups.push(group);
        }
        if (group) group.push(el);
      });
      if (groups.length <= INITIAL_ITEMS) return;

      var wrappers = groups.map(function (groupNodes) {
        var wrapper = document.createElement('div');
        wrapper.className = 'hz-item';
        groupNodes[0].parentNode.insertBefore(wrapper, groupNodes[0]);
        groupNodes.forEach(function (node) { wrapper.appendChild(node); });
        return wrapper;
      });

      var visible = INITIAL_ITEMS;
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'hz-more';
      button.style.display = 'none';

      function render() {
        var remaining = wrappers.length - visible;
        if (remaining <= 0) {
          button.style.display = 'none';
          return;
        }
        button.style.display = '';
        button.textContent = text.more(remaining);
        var last = wrappers[visible - 1];
        last.parentNode.insertBefore(button, last.nextSibling);
      }

      /** 只展开到 count 条；分页按钮与锚点跳转共用 */
      function show(count) {
        visible = Math.min(Math.max(count, INITIAL_ITEMS), wrappers.length);
        wrappers.forEach(function (wrapper, index) {
          wrapper.classList.toggle('hz-hidden', index >= visible);
        });
        render();
      }

      button.addEventListener('click', function () {
        show(visible + ITEMS_PER_EXPAND);
      });

      show(INITIAL_ITEMS);

      sectionStates.push({
        wrapperIndex: function (node) {
          for (var index = 0; index < wrappers.length; index += 1) {
            if (wrappers[index].contains(node)) return index;
          }
          return -1;
        },
        revealIndex: function (index) {
          if (index < visible) return false;
          show(index + 1);
          return true;
        },
      });
    });
  }

  /**
   * 目录里的链接、以及从首页「近期消息」带 #item-... 打开的链接，都可能指向
   * 被折叠（display:none）的条目：浏览器对这种情况不会滚动，表现为「点了没反应」。
   * 这里先把那一条展开，再滚动并短暂高亮。
   */
  function anchorTarget(hash) {
    if (!hash || hash.charAt(0) !== '#' || hash.length < 2) return null;
    var id = hash.slice(1);
    try {
      id = decodeURIComponent(id);
    } catch (error) {
      return null;
    }
    var target = document.getElementById(id);
    return target && target.tagName === 'A' ? target : null;
  }

  function flash(target) {
    var anchorParagraph = target.parentNode;
    var heading = anchorParagraph && anchorParagraph.nextElementSibling;
    var nodes = [anchorParagraph];
    if (heading && heading.tagName === 'H3') nodes.push(heading);
    nodes.forEach(function (node) {
      if (node && node.classList) node.classList.add('hz-flash');
    });
    window.setTimeout(function () {
      nodes.forEach(function (node) {
        if (node && node.classList) node.classList.remove('hz-flash');
      });
    }, 1600);
  }

  function revealAnchor(target) {
    if (!target) return false;
    var inPaginatedSection = false;
    var expanded = false;
    sectionStates.forEach(function (state) {
      var index = state.wrapperIndex(target);
      if (index < 0) return;
      inPaginatedSection = true;
      if (state.revealIndex(index)) expanded = true;
    });
    if (!inPaginatedSection) return false;
    // 只有真的展开过才需要我们滚动；否则交给浏览器自己的锚点跳转
    if (expanded && typeof target.scrollIntoView === 'function') {
      target.scrollIntoView();
    }
    flash(target);
    return true;
  }

  /** 捕获页内锚点点击（不阻止默认跳转，只负责把目标展开） */
  function setupAnchorLinks() {
    document.addEventListener('click', function (event) {
      var link = event.target;
      while (link && link.tagName !== 'A') link = link.parentNode;
      if (!link || !link.getAttribute) return;
      revealAnchor(anchorTarget(link.getAttribute('href') || ''));
    });
  }

  /**
   * 只在日报正文（含 Horizon 生成的 item 锚点）上启用目录折叠与分页，
   * 文档页等其他页面不受影响。
   */
  function setupDigestLayout() {
    var root = document.querySelector('.main-content');
    if (!root || !root.querySelector('a[id^="item-"]')) return;
    var text = uiText();
    collapseToc(root, text);
    paginateSections(root, text);
    // 带着 #item-... 打开时，目标条目可能刚被折叠起来
    revealAnchor(anchorTarget(window.location.hash));
  }

  /** Set up EN/中文 language toggle as a page-level control */
  function setupLanguageToggle() {
    // Create toggle buttons
    var toggle = document.createElement('div');
    toggle.className = 'lang-toggle';

    var btnEn = document.createElement('button');
    btnEn.textContent = 'EN';
    btnEn.type = 'button';

    var btnZh = document.createElement('button');
    btnZh.textContent = '中文';
    btnZh.type = 'button';

    toggle.appendChild(btnEn);
    toggle.appendChild(btnZh);

    // Insert at top of body
    document.body.insertBefore(toggle, document.body.firstChild);

    // Read saved preference, default to zh
    var saved = null;
    try { saved = localStorage.getItem('horizon-lang'); } catch (e) { /* noop */ }
    var currentLang = saved === 'en' ? 'en' : 'zh';

    function updateButtons(lang) {
      if (lang === 'en') {
        btnEn.classList.add('active');
        btnZh.classList.remove('active');
      } else {
        btnZh.classList.add('active');
        btnEn.classList.remove('active');
      }
    }

    // Index page: toggle lang-section visibility
    var zhSection = document.getElementById('lang-zh');
    var enSection = document.getElementById('lang-en');

    function showSection(lang) {
      if (!zhSection || !enSection) return;
      if (lang === 'en') {
        enSection.classList.remove('hidden');
        zhSection.classList.add('hidden');
      } else {
        zhSection.classList.remove('hidden');
        enSection.classList.add('hidden');
      }
    }

    // Article page: redirect to the other language version
    function switchArticleLang(lang) {
      var path = window.location.pathname;
      var target = null;
      if (lang === 'en' && /-zh(?:\.html)?$/.test(path.replace(/\/$/, ''))) {
        target = path.replace(/-zh(\.html)?$/, '-en$1').replace(/-zh\/$/, '-en/');
      } else if (lang === 'zh' && /-en(?:\.html)?$/.test(path.replace(/\/$/, ''))) {
        target = path.replace(/-en(\.html)?$/, '-zh$1').replace(/-en\/$/, '-zh/');
      }
      if (target) window.location.href = target;
    }

    function setLang(lang) {
      currentLang = lang;
      updateButtons(lang);
      try { localStorage.setItem('horizon-lang', lang); } catch (e) { /* noop */ }
      if (zhSection && enSection) {
        showSection(lang);
      } else {
        switchArticleLang(lang);
      }
    }

    btnEn.addEventListener('click', function () { setLang('en'); });
    btnZh.addEventListener('click', function () { setLang('zh'); });

    // Initialize
    updateButtons(currentLang);
    if (zhSection && enSection) {
      showSection(currentLang);
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    processScoreBadges();
    markSemanticElements();
    setupDigestLayout();
    setupAnchorLinks();
    setupLanguageToggle();
  });
})();
