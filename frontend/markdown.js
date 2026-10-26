'use strict';

// Build only known DOM elements. Model output is never interpreted as HTML.
function renderMarkdown(container, markdown = '') {
  const create = (tag, text) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function inline(parent, text, depth = 0) {
    if (depth > 16) { parent.append(document.createTextNode(text)); return; }
    const pattern = /\\([\\`*_~\[\]])|(`+)([^`]*?)\2|\[([^\]\n]+)\]\(([^\s)]+)\)|(\*\*|__)(?=\S)([\s\S]*?\S)\6|(~~)(?=\S)([\s\S]*?\S)\8|(\*|_)(?=\S)([^\n]*?\S)\10/g;
    let offset = 0;
    for (const match of text.matchAll(pattern)) {
      parent.append(document.createTextNode(text.slice(offset, match.index)));
      if (match[1]) parent.append(document.createTextNode(match[1]));
      else if (match[2]) parent.append(create('code', match[3]));
      else if (match[4]) {
        // Only explicit web/mail links and same-origin paths are clickable.
        if (/^(https?:\/\/|mailto:|\/(?!\/)|#)/i.test(match[5]) && !/[\u0000-\u0020\u007f\\]/.test(match[5])) {
          const link = create('a');
          link.setAttribute('href', match[5]);
          link.setAttribute('rel', 'noopener noreferrer');
          inline(link, match[4], depth + 1); parent.append(link);
        } else parent.append(document.createTextNode(match[0]));
      } else {
        const node = create(match[6] ? 'strong' : match[8] ? 'del' : 'em');
        inline(node, match[7] || match[9] || match[11], depth + 1); parent.append(node);
      }
      offset = match.index + match[0].length;
    }
    parent.append(document.createTextNode(text.slice(offset)));
  }
  const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map(cell => cell.trim().replace(/\\\|/g, '|'));
  const listItem = line => /^(\s*)([-+*]|\d+[.)])\s+(.+)$/.exec(line);
  const tableDivider = line => line.includes('|') && cells(line).every(cell => /^:?-{3,}:?$/.test(cell));
  function blocks(parent, lines, depth = 0) {
    if (depth > 16) { parent.append(create('p', lines.join('\n'))); return; }
    let i = 0;
    const startsBlock = index => /^( {0,3})(#{1,6}\s|`{3,}|~{3,}|>|(?:[-*_]\s*){3,}$)/.test(lines[index]) || listItem(lines[index]) || (index + 1 < lines.length && tableDivider(lines[index + 1]));
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      const fence = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
      if (fence) {
        const code = []; i++;
        const closing = new RegExp('^ {0,3}' + fence[1][0] + '{' + fence[1].length + ',}\\s*$');
        while (i < lines.length && !closing.test(lines[i])) code.push(lines[i++]);
        if (i < lines.length) i++;
        const pre = create('pre'); pre.append(create('code', code.join('\n'))); parent.append(pre); continue;
      }
      const heading = /^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
      if (heading) {
        const node = create('h' + heading[1].length); inline(node, heading[2]); parent.append(node); i++; continue;
      }
      if (/^ {0,3}(?:\*\s*){3,}$|^ {0,3}(?:-\s*){3,}$|^ {0,3}(?:_\s*){3,}$/.test(line)) { parent.append(create('hr')); i++; continue; }
      if (/^ {0,3}>/.test(line)) {
        const quote = create('blockquote'); const content = [];
        while (i < lines.length && /^ {0,3}>/.test(lines[i])) content.push(lines[i++].replace(/^ {0,3}> ?/, ''));
        blocks(quote, content, depth + 1); parent.append(quote); continue;
      }
      if (i + 1 < lines.length && line.includes('|') && tableDivider(lines[i + 1])) {
        const wrapper = create('div'); wrapper.className = 'markdown-table';
        wrapper.setAttribute('tabindex', '0'); wrapper.setAttribute('role', 'region'); wrapper.setAttribute('aria-label', 'Tabela da resposta');
        const table = create('table'); const head = create('thead'); const body = create('tbody');
        const header = cells(line); const alignment = cells(lines[i + 1]);
        const row = (values, tag) => {
          const tr = create('tr');
          header.forEach((_, column) => {
            const td = create(tag); inline(td, values[column] || '');
            if (tag === 'th') td.setAttribute('scope', 'col');
            const align = alignment[column] || '';
            if (align.endsWith(':')) td.style.textAlign = align.startsWith(':') ? 'center' : 'right';
            tr.append(td);
          }); return tr;
        };
        head.append(row(header, 'th')); i += 2;
        while (i < lines.length && lines[i].trim() && lines[i].includes('|')) body.append(row(cells(lines[i++]), 'td'));
        table.append(head, body); wrapper.append(table); parent.append(wrapper); continue;
      }
      const first = listItem(line);
      if (first) {
        const ordered = /^\d/.test(first[2]); const indent = first[1].length;
        const list = create(ordered ? 'ol' : 'ul');
        if (ordered) list.setAttribute('start', String(parseInt(first[2], 10)));
        while (i < lines.length) {
          const item = listItem(lines[i]);
          if (!item || item[1].length !== indent || /^\d/.test(item[2]) !== ordered) break;
          const li = create('li'); const content = [item[3]]; i++;
          const contentIndent = item[0].length - item[3].length;
          while (i < lines.length) {
            if (!lines[i].trim()) {
              if (i + 1 < lines.length && /^\s+\S/.test(lines[i + 1]) && lines[i + 1].search(/\S/) >= contentIndent) { content.push(''); i++; continue; }
              break;
            }
            if (lines[i].search(/\S/) < contentIndent) break;
            content.push(lines[i++].slice(contentIndent));
          }
          blocks(li, content, depth + 1); list.append(li);
        }
        parent.append(list); continue;
      }
      const paragraph = [line]; i++;
      while (i < lines.length && lines[i].trim() && !startsBlock(i)) paragraph.push(lines[i++]);
      const p = create('p');
      paragraph.forEach((part, index) => { if (index) p.append(create('br')); inline(p, part); });
      parent.append(p);
    }
  }
  container.replaceChildren();
  blocks(container, String(markdown || '').replace(/\r\n?/g, '\n').replace(/\t/g, '    ').split('\n'));
}
