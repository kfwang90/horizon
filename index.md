---
layout: default
title: Horizon 每日速递
---

<div id="lang-zh" class="lang-section" markdown="1">

## 每日速递 <a class="rss-icon" href="{{ '/feed-zh.xml' | relative_url }}" aria-label="订阅中文"><svg viewBox="0 0 448 512" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M128.081 415.959c0 35.369-28.672 64.041-64.041 64.041S0 451.328 0 415.959s28.672-64.041 64.041-64.041 64.04 28.673 64.04 64.041zm175.66 47.25c-8.354-154.6-132.185-278.587-286.95-286.95C7.656 175.765 0 183.105 0 192.253v48.069c0 8.415 6.49 15.472 14.887 16.018 111.832 7.284 201.473 96.702 208.772 208.772.547 8.397 7.604 14.887 16.018 14.887h48.069c9.149.001 16.489-7.655 15.995-16.79zm144.249.288C439.596 229.677 251.465 40.445 16.503 32.01 7.473 31.686 0 38.981 0 48.016v48.068c0 8.625 6.835 15.645 15.453 15.999 191.179 7.839 344.627 161.316 352.465 352.465.353 8.618 7.373 15.453 15.999 15.453h48.068c9.034-.001 16.329-7.474 16.005-16.504z"/></svg></a>

<ul>
  {% assign zh_posts = site.posts | where: "lang", "zh" %}
  {% for post in zh_posts limit:20 %}
    <li>
      <a href="{{ post.url | relative_url }}">{{ post.date | date: "%Y-%m-%d" }}</a>
    </li>
  {% else %}
    <li><em>暂无内容</em></li>
  {% endfor %}
</ul>

<h2 id="recent-zh">近期消息</h2>

<p class="hz-recent-hint">最近一周收录的条目，点标题跳到当日速递里的点评。</p>

{% if zh_posts.size == 0 %}
<p><em>暂无内容</em></p>
{% else %}
{% for post in zh_posts limit:7 %}
{% if post.items.size > 0 %}
<details class="hz-recent-day"{% if forloop.first %} open{% endif %}>
<summary>{{ post.date | date: "%Y-%m-%d" }} · {{ post.items | size }} 条</summary>

<ul class="hz-recent-list">
{% for item in post.items %}
<li><a href="{{ post.url | relative_url }}#{{ item.anchor }}">{{ item.title | escape }}</a> <span class="hz-recent-meta">{{ item.section | escape }} · ⭐️ {{ item.score }}/10</span></li>
{% endfor %}
</ul>

</details>
{% endif %}
{% endfor %}
{% endif %}

</div>

<div id="lang-en" class="lang-section" markdown="1">

## Daily Digest <a class="rss-icon" href="{{ '/feed-en.xml' | relative_url }}" aria-label="Subscribe English"><svg viewBox="0 0 448 512" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="M128.081 415.959c0 35.369-28.672 64.041-64.041 64.041S0 451.328 0 415.959s28.672-64.041 64.041-64.041 64.04 28.673 64.04 64.041zm175.66 47.25c-8.354-154.6-132.185-278.587-286.95-286.95C7.656 175.765 0 183.105 0 192.253v48.069c0 8.415 6.49 15.472 14.887 16.018 111.832 7.284 201.473 96.702 208.772 208.772.547 8.397 7.604 14.887 16.018 14.887h48.069c9.149.001 16.489-7.655 15.995-16.79zm144.249.288C439.596 229.677 251.465 40.445 16.503 32.01 7.473 31.686 0 38.981 0 48.016v48.068c0 8.625 6.835 15.645 15.453 15.999 191.179 7.839 344.627 161.316 352.465 352.465.353 8.618 7.373 15.453 15.999 15.453h48.068c9.034-.001 16.329-7.474 16.005-16.504z"/></svg></a>

<ul>
  {% assign en_posts = site.posts | where: "lang", "en" %}
  {% for post in en_posts limit:20 %}
    <li>
      <a href="{{ post.url | relative_url }}">{{ post.date | date: "%Y-%m-%d" }}</a>
    </li>
  {% else %}
    <li><em>No posts yet</em></li>
  {% endfor %}
</ul>

<h2 id="recent-en">Recent items</h2>

<p class="hz-recent-hint">Everything selected in the last week. Click a title to jump to its write-up in that day's digest.</p>

{% if en_posts.size == 0 %}
<p><em>No posts yet</em></p>
{% else %}
{% for post in en_posts limit:7 %}
{% if post.items.size > 0 %}
<details class="hz-recent-day"{% if forloop.first %} open{% endif %}>
<summary>{{ post.date | date: "%Y-%m-%d" }} · {{ post.items | size }} items</summary>

<ul class="hz-recent-list">
{% for item in post.items %}
<li><a href="{{ post.url | relative_url }}#{{ item.anchor }}">{{ item.title | escape }}</a> <span class="hz-recent-meta">{{ item.section | escape }} · ⭐️ {{ item.score }}/10</span></li>
{% endfor %}
</ul>

</details>
{% endif %}
{% endfor %}
{% endif %}

</div>
