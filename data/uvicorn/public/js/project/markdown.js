// Markdown / JSON rendering for phase result viewer

function renderPhaseResult(text) {
    if (!text || text === '—') return '<span style="color:#94a3b8">—</span>';

    let parsed = null;
    try { parsed = JSON.parse(text); } catch (_) {}

    // Handle Python dict repr: {'key': 'value'} → saved by str(dict) before the fix
    if (!parsed && text.trimStart().startsWith('{') && text.includes("': ")) {
        try {
            // Replace Python single-quote delimiters with JSON double quotes (best-effort)
            const jsonLike = text
                .replace(/'/g, '"')
                .replace(/\bTrue\b/g, 'true')
                .replace(/\bFalse\b/g, 'false')
                .replace(/\bNone\b/g, 'null');
            parsed = JSON.parse(jsonLike);
        } catch (_) {}
    }

    if (parsed && typeof parsed === 'object') {
        const mdField = parsed.markdown || parsed.content || parsed.text || parsed.result || parsed.report || null;
        if (typeof mdField === 'string' && mdField.length > 20) {
            return simpleMarkdown(mdField);
        }
        if (!Array.isArray(parsed)) {
            return renderJsonDict(parsed);
        }
        const pre = document.createElement('pre');
        pre.textContent = JSON.stringify(parsed, null, 2);
        return pre.outerHTML;
    }

    return simpleMarkdown(text);
}

function renderJsonDict(obj, depth) {
    depth = depth || 0;
    const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    let html = '';
    for (const [key, val] of Object.entries(obj)) {
        const title = key.replace(/_/g,' ').replace(/\b\w/g, c => c.toUpperCase());
        html += depth === 0 ? `<h2>${esc(title)}</h2>` : `<h3>${esc(title)}</h3>`;
        if (typeof val === 'string') {
            html += simpleMarkdown(val);
        } else if (Array.isArray(val)) {
            html += '<ul>' + val.map(item => {
                if (typeof item === 'object' && item !== null) {
                    return '<li>' + Object.entries(item).map(([k,v]) =>
                        `<strong>${esc(k)}:</strong> ${esc(String(v))}`).join(' · ') + '</li>';
                }
                return `<li>${esc(String(item))}</li>`;
            }).join('') + '</ul>';
        } else if (typeof val === 'object' && val !== null) {
            html += renderJsonDict(val, depth + 1);
        } else {
            html += `<p>${esc(String(val))}</p>`;
        }
    }
    return html;
}

function simpleMarkdown(text) {
    const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const inline = s => s
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>');

    const lines = text.split('\n');
    let html = '';
    let inUl = false, inOl = false, inPre = false, inTable = false;

    const closeList = () => {
        if (inUl) { html += '</ul>'; inUl = false; }
        if (inOl) { html += '</ol>'; inOl = false; }
    };
    const closeTable = () => { if (inTable) { html += '</tbody></table>'; inTable = false; } };

    for (let i = 0; i < lines.length; i++) {
        const raw = lines[i];
        const line = raw.trimEnd();

        if (inPre) {
            if (line.startsWith('```')) { html += '</code></pre>'; inPre = false; }
            else html += esc(raw) + '\n';
            continue;
        }
        if (line.startsWith('```')) { closeList(); closeTable(); html += '<pre><code>'; inPre = true; continue; }
        if (/^#{1}\s/.test(line)) { closeList(); closeTable(); html += `<h1>${inline(esc(line.replace(/^#+\s/,'')))}</h1>`; continue; }
        if (/^#{2}\s/.test(line)) { closeList(); closeTable(); html += `<h2>${inline(esc(line.replace(/^#+\s/,'')))}</h2>`; continue; }
        if (/^#{3}\s/.test(line)) { closeList(); closeTable(); html += `<h3>${inline(esc(line.replace(/^#+\s/,'')))}</h3>`; continue; }
        if (/^#{4,}\s/.test(line)) { closeList(); closeTable(); html += `<h3>${inline(esc(line.replace(/^#+\s/,'')))}</h3>`; continue; }
        if (/^---+$/.test(line.trim())) { closeList(); closeTable(); html += '<hr>'; continue; }

        if (line.startsWith('|')) {
            const cells = line.split('|').slice(1,-1).map(c => c.trim());
            const isSep = cells.every(c => /^[-: ]+$/.test(c));
            if (isSep) continue;
            if (!inTable) { closeList(); html += '<table><tbody>'; inTable = true; }
            html += '<tr>' + cells.map(c => `<td>${inline(esc(c))}</td>`).join('') + '</tr>';
            continue;
        }
        closeTable();

        if (/^[-*+]\s/.test(line)) {
            if (!inUl) { closeList(); html += '<ul>'; inUl = true; }
            html += `<li>${inline(esc(line.replace(/^[-*+]\s/,'')))}</li>`; continue;
        }
        if (/^\d+\.\s/.test(line)) {
            if (!inOl) { closeList(); html += '<ol>'; inOl = true; }
            html += `<li>${inline(esc(line.replace(/^\d+\.\s/,'')))}</li>`; continue;
        }
        closeList();

        if (line.trim() === '') { html += '<br>'; continue; }
        html += `<p>${inline(esc(line))}</p>`;
    }
    if (inPre) html += '</code></pre>';
    closeList();
    closeTable();
    return html;
}

async function showPhaseResult(label, projectId, phase) {
    const data = await fetch(`/planning/project/${projectId}/phases`).then(r => r.json());
    const ph = (data.result || []).find(p => p.phase === phase);
    if (!ph) return;
    document.getElementById('modalTitle').textContent = label;
    document.getElementById('modalContent').innerHTML = renderPhaseResult(ph.result || '');
    document.getElementById('resultModal').classList.add('visible');
}

async function showDocumentContent(label, docId) {
    const data = await fetch(`/planning/document/${docId}`).then(r => r.json());
    const doc = data.result;
    if (!doc) return;
    document.getElementById('modalTitle').textContent = label;
    document.getElementById('modalContent').innerHTML = renderPhaseResult(doc.content || '');
    document.getElementById('resultModal').classList.add('visible');
}
