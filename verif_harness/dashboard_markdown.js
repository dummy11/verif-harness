/* Read-only Markdown presentation. Governance continues to use ProjectStore. */
(function (root) {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[c]));
  const slug = text => text.trim().toLowerCase().replace(/[^\p{L}\p{N}\p{M}_\-\s]/gu, '').replace(/\s/g, '-') || 'section';
  const plain = tokens => (tokens || []).map(t => t.type === 'image' ? plain(t.children)
    : ['text', 'code_inline'].includes(t.type) ? t.content : '').join('');

  function destination(href, options) {
    // Decode for classification too: encoded schemes, separators and controls
    // must never turn a document-relative path into an arbitrary browser URL.
    let decoded;
    try { decoded = decodeURIComponent(href); } catch { return {reason:'链接编码无效'}; }
    if (/[\u0000-\u0020\u007f\\]/.test(decoded.replace(/ /g, ''))) return {reason:'链接包含无效字符'};
    if (/^(https?:|mailto:)/i.test(href)) {
      try {
        const url = new URL(href);
        if (url.username || url.password) return {reason:'不支持带登录信息的链接'};
        return {href:url.toString(), external:true};
      } catch { return {reason:'链接地址无效'}; }
    }
    if (/^[a-z][a-z\d+.-]*:/i.test(decoded) || decoded.startsWith('/') || decoded.includes('?')) {
      return {reason:'仅支持已登记文档、章节和 HTTP/HTTPS 链接'};
    }
    const hash = href.indexOf('#');
    const path = decodeURIComponent(hash < 0 ? href : href.slice(0, hash));
    const fragment = hash < 0 ? '' : decodeURIComponent(href.slice(hash + 1));
    let target = options.document;
    if (path) {
      const parts = options.document.path.split('/').slice(0, -1);
      for (const part of path.split('/')) {
        if (part === '..') {
          if (!parts.length) return {reason:'链接超出当前项目'};
          parts.pop();
        } else if (part && part !== '.') parts.push(part);
      }
      target = options.documents.find(doc => doc.path === parts.join('/') && doc.exists);
      if (!target) return {reason:'当前项目未登记这份文档，或文件不存在'};
    }
    const url = options.urlForDocument(target.id);
    if (fragment) url.hash = 'md-' + fragment;
    return {href:url.toString(), internal:true};
  }

  function render(content, options) {
    const source = `<details class="document-source"><summary>查看 Markdown 源码</summary><pre>${escape(content)}</pre></details>`;
    try {
      // Raw HTML is escaped. No highlighting callback or HTML-producing plugin
      // is allowed here; only the parser's built-in, escaped output is inserted.
      const md = new root.markdownit({html:false, linkify:false, typographer:false});
      const tokens = md.parse(content, {});
      const used = new Set();
      const headings = new Set();
      for (let i = 0; i < tokens.length; i++) {
        if (tokens[i].type !== 'heading_open') continue;
        const base = slug(plain(tokens[i + 1]?.children));
        let id = base, suffix = 0;
        while (used.has(id)) id = `${base}-${++suffix}`;
        used.add(id); headings.add('md-' + id);
        tokens[i].attrSet('id', 'md-' + id);
      }
      for (const block of tokens) {
        let closeTag = 'a';
        for (const token of block.children || []) {
          if (token.type === 'link_open') {
            const link = destination(token.attrGet('href') || '', options);
            const url = link.href && new URL(link.href);
            if (link.internal && url.searchParams.get('document') === options.document.id && url.hash
                && !headings.has(decodeURIComponent(url.hash.slice(1)))) link.reason = '当前文档中找不到这个章节';
            if (link.reason) {
              token.tag = closeTag = 'span';
              token.attrs = [['class','document-link-unavailable'], ['title',link.reason], ['aria-disabled','true']];
            } else {
              closeTag = 'a';
              token.attrSet('href', link.href);
              if (link.external) {
                token.attrSet('target', '_blank'); token.attrSet('rel', 'noopener noreferrer');
                token.attrSet('referrerpolicy', 'no-referrer');
              } else token.attrSet('data-document-link', '');
            }
          } else if (token.type === 'link_close') token.tag = closeTag;
        }
      }
      // Images stay visible as descriptions until there is a project-scoped
      // attachment API. Never cause implicit network or arbitrary file reads.
      md.renderer.rules.image = (items, i) => `<span class="document-image-note">[图片：${escape(plain(items[i].children) || '未命名')} · 暂未提供预览]</span>`;
      md.renderer.rules.table_open = () => '<div class="document-table"><table>\n';
      md.renderer.rules.table_close = () => '</table></div>\n';
      return `<article class="document-preview markdown-body">${md.renderer.render(tokens, md.options, {})}</article>${source}`;
    } catch {
      return `<div class="notice">文档排版暂不可用，请展开 Markdown 源码阅读。</div>${source.replace('<details ', '<details open ')}`;
    }
  }
  root.VerifMarkdown = {render};
})(globalThis);
