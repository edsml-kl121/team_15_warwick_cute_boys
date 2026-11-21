(() => {
  // Small, safe Markdown subset for chat replies. Builds DOM nodes; never uses innerHTML.
  // Supports paragraphs, headings, bullet and numbered lists, pipe tables, fenced code,
  // **bold**, *italic*, `code` and [links](https://…).
  const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+?\*\*|__[^_\n]+?__)|(\*[^*\s][^*\n]*?\*|_[^_\s][^_\n]*?_)|(\[[^\]\n]+\]\([^)\s]+\))/;
  const HEADING = /^(#{1,6})\s+(.*)$/;
  const BULLET = /^\s*[-*+•]\s+(.*)$/;
  const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
  const TABLE_ROW = /^(\s*\|.*\|\s*)$/;
  const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
  const FENCE = /^\s*```/;

  function inline(text) {
    const parts = [];
    let rest = text;
    while (rest) {
      const match = INLINE.exec(rest);
      if (!match) {
        parts.push({ type: 'text', text: rest });
        break;
      }
      if (match.index) parts.push({ type: 'text', text: rest.slice(0, match.index) });
      const [token, code, strong, em] = match;
      if (code) parts.push({ type: 'code', text: token.slice(1, -1) });
      else if (strong) parts.push({ type: 'strong', children: inline(token.slice(2, -2)) });
      else if (em) parts.push({ type: 'em', children: inline(token.slice(1, -1)) });
      else {
        const split = token.indexOf('](');
        parts.push({ type: 'link', href: token.slice(split + 2, -1), children: inline(token.slice(1, split)) });
      }
      rest = rest.slice(match.index + token.length);
    }
    return parts;
  }

  const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => inline(cell.trim()));

  function collect(lines, start, pattern) {
    const items = [];
    let index = start;
    while (index < lines.length && pattern.test(lines[index])) {
      items.push(lines[index].match(pattern)[1]);
      index += 1;
    }
    return [items, index];
  }

  const isTable = (line, next) => TABLE_ROW.test(line) && TABLE_RULE.test(next || '');
  const isBlockStart = (line, next) => HEADING.test(line) || BULLET.test(line) || NUMBERED.test(line)
    || FENCE.test(line) || isTable(line, next);

  function parse(text) {
    const lines = String(text).replace(/\r\n?/g, '\n').split('\n');
    const blocks = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
      } else if (FENCE.test(line)) {
        const end = lines.findIndex((item, at) => at > index && FENCE.test(item));
        const stop = end === -1 ? lines.length : end;
        blocks.push({ type: 'code', text: lines.slice(index + 1, stop).join('\n') });
        index = stop + 1;
      } else if (HEADING.test(line)) {
        const [, hashes, body] = line.match(HEADING);
        blocks.push({ type: 'heading', level: hashes.length, children: inline(body) });
        index += 1;
      } else if (isTable(line, lines[index + 1])) {
        const [rows, next] = collect(lines, index + 2, TABLE_ROW);
        blocks.push({ type: 'table', head: cells(line), rows: rows.map(cells) });
        index = next;
      } else if (BULLET.test(line) || NUMBERED.test(line)) {
        const ordered = !BULLET.test(line);
        const [items, next] = collect(lines, index, ordered ? NUMBERED : BULLET);
        blocks.push({ type: ordered ? 'ol' : 'ul', items: items.map(inline) });
        index = next;
      } else {
        const paragraph = [line];
        index += 1;
        while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index], lines[index + 1])) {
          paragraph.push(lines[index]);
          index += 1;
        }
        blocks.push({ type: 'paragraph', children: inline(paragraph.join('\n')) });
      }
    }
    return blocks;
  }

  function safeHref(href) {
    try {
      const url = new URL(href);
      return url.protocol === 'https:' ? url.href : null;
    } catch {
      return null;
    }
  }

  function el(tag, children) {
    const element = document.createElement(tag);
    element.append(...children);
    return element;
  }

  function renderInline(parts) {
    return parts.map(part => {
      if (part.type === 'text') return document.createTextNode(part.text);
      if (part.type === 'code') return el('code', [part.text]);
      if (part.type === 'strong') return el('strong', renderInline(part.children));
      if (part.type === 'em') return el('em', renderInline(part.children));
      const href = safeHref(part.href);
      if (!href) return el('span', renderInline(part.children));
      const link = el('a', renderInline(part.children));
      link.href = href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      return link;
    });
  }

  function renderBlock(block) {
    switch (block.type) {
      case 'heading': return el(block.level <= 2 ? 'h3' : 'h4', renderInline(block.children));
      case 'code': return el('pre', [el('code', [block.text])]);
      case 'ul':
      case 'ol': return el(block.type, block.items.map(item => el('li', renderInline(item))));
      case 'table': {
        const head = el('thead', [el('tr', block.head.map(cell => el('th', renderInline(cell))))]);
        const body = el('tbody', block.rows.map(row => el('tr', row.map(cell => el('td', renderInline(cell))))));
        const wrap = el('div', [el('table', [head, body])]);
        wrap.className = 'md-table';
        wrap.tabIndex = 0;
        return wrap;
      }
      default: return el('p', renderInline(block.children));
    }
  }

  function render(text) {
    const fragment = document.createDocumentFragment();
    fragment.append(...parse(text).map(renderBlock));
    return fragment;
  }

  window.zippyMarkdown = { parse, render };
})();
