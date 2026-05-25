---
title: Comments and HTML Fixture
tags: [test, html]
aliases: [HTML Fixture]
---

%% This comment should be hidden in Reading View. %%

Normal paragraph.

%% Multi-word inline comment %% still visible text after comment.

Safe inline HTML: <span style="color:red">styled text</span>

Unsafe HTML - script must be stripped: <script>alert('xss')</script>

Unsafe event handler: <img src="x" onerror="alert('xss')">

Remote image via HTML: <img src="https://external.example.com/image.png">
