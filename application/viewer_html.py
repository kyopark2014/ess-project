"""CSP-safe HTML helpers for markdown/text viewers (no inline scripts, no CDN)."""

from __future__ import annotations

import html


def markdown_to_safe_html(text: str) -> str:
    """Best-effort Markdown → HTML without client JS (CSP-safe).

    Prefer the optional ``markdown`` package; otherwise escape into ``<pre>``.
    """
    try:
        import markdown as md_lib  # type: ignore

        return md_lib.markdown(
            text,
            extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
            output_format="html5",
        )
    except Exception:
        return f'<pre class="code">{html.escape(text)}</pre>'


_MARKDOWN_BODY_CSS = """
    .markdown-body {
      background: transparent;
      color: #e6edf3;
      line-height: 1.6;
      font-size: 15px;
    }
    .markdown-body h1, .markdown-body h2, .markdown-body h3 {
      margin: 1.2em 0 0.5em;
      font-weight: 650;
      border-bottom: 1px solid #30363d;
      padding-bottom: 0.3em;
    }
    .markdown-body p { margin: 0.75em 0; }
    .markdown-body ul, .markdown-body ol { padding-left: 1.5em; }
    .markdown-body code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.9em;
      background: rgba(110, 118, 129, 0.2);
      padding: 0.15em 0.4em;
      border-radius: 4px;
    }
    .markdown-body pre {
      overflow-x: auto;
      padding: 12px 14px;
      border-radius: 8px;
      background: rgba(110, 118, 129, 0.15);
      border: 1px solid #30363d;
    }
    .markdown-body pre code {
      background: transparent;
      padding: 0;
    }
    .markdown-body table {
      border-collapse: collapse;
      width: 100%;
      margin: 1em 0;
      font-size: 14px;
    }
    .markdown-body th, .markdown-body td {
      border: 1px solid #30363d;
      padding: 6px 10px;
      text-align: left;
    }
    .markdown-body a { color: #58a6ff; }
    .markdown-body blockquote {
      margin: 0.75em 0;
      padding: 0 1em;
      border-left: 3px solid #30363d;
      color: #8b949e;
    }
    @media (prefers-color-scheme: light) {
      .markdown-body { color: #1f2328; }
      .markdown-body h1, .markdown-body h2, .markdown-body h3,
      .markdown-body th, .markdown-body td,
      .markdown-body pre, .markdown-body blockquote {
        border-color: #d0d7de;
      }
      .markdown-body blockquote { color: #656d76; }
    }
"""


def build_markdown_viewer_page(
    file_name: str,
    text: str,
    *,
    topbar_right_html: str = "",
) -> str:
    """Full HTML document for markdown preview (CSP-safe)."""
    title = html.escape(file_name)
    body_inner = markdown_to_safe_html(text)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{
      margin: 0;
      background: #0d1117;
      color: #e6edf3;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    }}
    .topbar {{
      position: sticky; top: 0; z-index: 2;
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      padding: 10px 20px;
      border-bottom: 1px solid #30363d;
      background: rgba(13, 17, 23, 0.92);
      backdrop-filter: blur(8px);
    }}
    .topbar h1 {{
      margin: 0; font-size: 14px; font-weight: 600;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }}
    .topbar a.raw {{
      color: #58a6ff; text-decoration: none; font-size: 13px; white-space: nowrap;
    }}
    .wrap {{
      box-sizing: border-box;
      max-width: 980px;
      margin: 0 auto;
      padding: 24px 20px 64px;
    }}
    {_MARKDOWN_BODY_CSS}
    @media (prefers-color-scheme: light) {{
      body {{ background: #ffffff; color: #1f2328; }}
      .topbar {{ background: rgba(255,255,255,0.92); border-bottom-color: #d0d7de; }}
    }}
  </style>
</head>
<body>
  <div class="topbar">
    <h1>{title}</h1>
    {topbar_right_html}
  </div>
  <div class="wrap">
    <article class="markdown-body">{body_inner}</article>
  </div>
</body>
</html>
"""


def build_text_viewer_page(
    file_name: str,
    text: str,
    *,
    as_markdown: bool,
    download_href: str,
) -> str:
    """CSP-safe text/markdown viewer used by Load-files ``/api/files/view``."""
    title = html.escape(file_name)
    download_link = (
        f'<a class="raw" href="{html.escape(download_href, quote=True)}">Download</a>'
    )
    if as_markdown:
        return build_markdown_viewer_page(
            file_name, text, topbar_right_html=download_link
        )

    body_inner = f'<pre class="code">{html.escape(text)}</pre>'
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{
      margin: 0;
      background: #0d1117;
      color: #e6edf3;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    }}
    .topbar {{
      position: sticky; top: 0; z-index: 2;
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      padding: 10px 20px;
      border-bottom: 1px solid #30363d;
      background: rgba(13, 17, 23, 0.92);
      backdrop-filter: blur(8px);
    }}
    .topbar h1 {{
      margin: 0; font-size: 14px; font-weight: 600;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }}
    .topbar a.raw {{
      color: #58a6ff; text-decoration: none; font-size: 13px; white-space: nowrap;
    }}
    .wrap {{
      box-sizing: border-box;
      max-width: 980px;
      margin: 0 auto;
      padding: 24px 20px 64px;
    }}
    pre.code {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 13px;
      line-height: 1.5;
    }}
    @media (prefers-color-scheme: light) {{
      body {{ background: #ffffff; color: #1f2328; }}
      .topbar {{ background: rgba(255,255,255,0.92); border-bottom-color: #d0d7de; }}
    }}
  </style>
</head>
<body>
  <div class="topbar">
    <h1>{title}</h1>
    {download_link}
  </div>
  <div class="wrap">
    <article>{body_inner}</article>
  </div>
</body>
</html>
"""
