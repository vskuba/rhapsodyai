    let allComponents = [];
    let activeId = null;

    async function loadComponents() {
        const res = await fetch('/design/ui-components');
        const data = await res.json();
        allComponents = data.result || [];
        document.getElementById('compCount').textContent = allComponents.length;
        renderList(allComponents);
    }

    function renderList(items) {
        const el = document.getElementById('compList');
        el.innerHTML = items.map(c => `
        <div class="ui-comp-item ${c.id === activeId ? 'active' : ''}"
             onclick="selectComponent(${c.id})">
            <span>${c.name}</span>
            <span class="comp-tags">${(c.tags || '').split(',').filter(Boolean).join(' ')}</span>
        </div>
    `).join('');
    }

    function filterComponents() {
        const q = document.getElementById('compSearch').value.toLowerCase();
        renderList(q ? allComponents.filter(c =>
            c.name.toLowerCase().includes(q) ||
            (c.tags || '').toLowerCase().includes(q) ||
            (c.description || '').toLowerCase().includes(q)
        ) : allComponents);
    }

    function selectComponent(id) {
        activeId = id;
        const comp = allComponents.find(c => c.id === id);
        if (!comp) return;

        document.getElementById('formTitle').textContent = comp.name;
        document.getElementById('compId').value = comp.id;
        document.getElementById('compName').value = comp.name || '';
        document.getElementById('compDesc').value = comp.description || '';
        document.getElementById('compVariants').value = comp.variants || '';
        document.getElementById('compSizes').value = comp.sizes || '';
        document.getElementById('compStates').value = comp.states || '';
        document.getElementById('compTags').value = comp.tags || '';
        document.getElementById('compTailwind').value = comp.tailwind_example || '';

        document.getElementById('emptyPlaceholder').style.display = 'none';
        document.getElementById('compForm').style.display = 'flex';
        document.getElementById('deleteBtn').style.display = '';

        renderList(allComponents.filter(c => {
            const q = document.getElementById('compSearch').value.toLowerCase();
            return !q || c.name.toLowerCase().includes(q) || (c.tags || '').toLowerCase().includes(q);
        }));
    }

    function createNew() {
        activeId = null;
        document.getElementById('formTitle').textContent = 'Новый компонент';
        document.getElementById('compId').value = '';
        document.getElementById('compName').value = '';
        document.getElementById('compDesc').value = '';
        document.getElementById('compVariants').value = '';
        document.getElementById('compSizes').value = '';
        document.getElementById('compStates').value = '';
        document.getElementById('compTags').value = '';
        document.getElementById('compTailwind').value = '';

        document.getElementById('emptyPlaceholder').style.display = 'none';
        document.getElementById('compForm').style.display = 'flex';
        document.getElementById('deleteBtn').style.display = 'none';

        renderList(allComponents);
        document.getElementById('compName').focus();
    }

    async function saveComponent(e) {
        e.preventDefault();
        const id = document.getElementById('compId').value;
        const payload = {
            name: document.getElementById('compName').value.trim(),
            description: document.getElementById('compDesc').value.trim(),
            variants: document.getElementById('compVariants').value.trim(),
            sizes: document.getElementById('compSizes').value.trim(),
            states: document.getElementById('compStates').value.trim(),
            tags: document.getElementById('compTags').value.trim(),
            tailwind_example: document.getElementById('compTailwind').value.trim(),
        };

        let res;
        if (id) {
            res = await fetch(`/design/ui-components/${id}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
        } else {
            res = await fetch('/design/ui-components', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
            const data = await res.json();
            if (data.result) {
                document.getElementById('compId').value = data.result;
                activeId = data.result;
            }
        }

        showStatus('Сохранено', false);
        await loadComponents();
        if (activeId) selectComponent(activeId);
    }

    async function deleteComponent() {
        const id = document.getElementById('compId').value;
        if (!id || !confirm('Удалить компонент?')) return;
        await fetch(`/design/ui-components/${id}`, {method: 'DELETE'});
        activeId = null;
        document.getElementById('emptyPlaceholder').style.display = '';
        document.getElementById('compForm').style.display = 'none';
        document.getElementById('formTitle').textContent = 'Выберите компонент';
        await loadComponents();
    }

    function showStatus(msg, isError) {
        const el = document.getElementById('statusMsg');
        el.textContent = msg;
        el.className = 'status-msg visible' + (isError ? ' error' : '');
        setTimeout(() => el.className = 'status-msg', 2000);
    }

    // Переключение вкладок
    document.querySelectorAll('.page-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.page-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
            localStorage.setItem('design_active_tab', tab.dataset.tab);
            onProjectChange();
        });
    });

    loadComponents();

    // ═══════════════════════════════════════════════
    // БЛОКИ / ВИДЖЕТЫ (объединённая вкладка)
    // ═══════════════════════════════════════════════

    let _allProjects = [];
    let _bwProjectId = null;

    async function planningFetch(url, opts = {}) {
        return fetch(url, {
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', ...(opts.headers || {})},
            ...opts,
        }).then(r => r.json());
    }

    function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    async function loadBlocksWidgets() {
        const pid = document.getElementById('globalProjectSel').value;
        _bwProjectId = pid ? parseInt(pid) : null;
        const footer = document.getElementById('bwBlockFooter');
        if (footer) footer.style.display = pid ? '' : 'none';
    }

    function resetBwRight() {
        document.getElementById('bwPreviewContent').innerHTML = '<span class="bw-placeholder">Выберите блок</span>';
    }

    const _BW_ALL_ZONES = ['header','hero','section','sidebar','card','form','cta','media','footer','overlay','utility'];

    function _bwParseTags(raw) {
        if (!raw) return [];
        return raw.split(',').map(t => t.trim()).filter(Boolean);
    }

    function _bwTagsBarHtml(blockId, tagsRaw) {
        const tags = _bwParseTags(tagsRaw);
        const chipsHtml = tags.map(t =>
            `<span class="bw-default-preview-tag">${esc(t)}<span class="bw-default-preview-tag-del" onclick="bwTagRemove(${blockId},'${esc(t)}')">×</span></span>`
        ).join('');
        return `<div class="bw-default-preview-tags" id="bwpt-${blockId}">${chipsHtml}<input class="bwpt-input" id="bwpt-inp-${blockId}" placeholder="тег…" onkeydown="if(event.key==='Enter')bwTagAdd(${blockId})"><button class="bwpt-add-btn" onclick="bwTagAdd(${blockId})">+</button></div>`;
    }

    function _bwTagsBarRerender(blockId, tags) {
        const container = document.getElementById(`bwpt-${blockId}`);
        if (!container) return;
        const tmp = document.createElement('div');
        tmp.innerHTML = _bwTagsBarHtml(blockId, tags.join(','));
        container.replaceWith(tmp.firstElementChild);
    }

    async function bwTagAdd(blockId) {
        const inp = document.getElementById(`bwpt-inp-${blockId}`);
        const tag = inp ? inp.value.trim() : '';
        if (!tag) return;
        const block = _defaultBlocks.find(b => b.id === blockId);
        const tags = _bwParseTags(block ? block.tags : null);
        if (tags.includes(tag)) { inp.value = ''; return; }
        tags.push(tag);
        const tagsStr = tags.join(', ');
        await planningFetch(`/design/block/${blockId}`, {method: 'PUT', body: JSON.stringify({tags: tagsStr})});
        if (block) block.tags = tagsStr;
        _bwTagsBarRerender(blockId, tags);
    }

    async function bwTagRemove(blockId, tag) {
        const block = _defaultBlocks.find(b => b.id === blockId);
        const tags = _bwParseTags(block ? block.tags : null).filter(t => t !== tag);
        const tagsStr = tags.join(', ') || null;
        await planningFetch(`/design/block/${blockId}`, {method: 'PUT', body: JSON.stringify({tags: tagsStr})});
        if (block) block.tags = tagsStr;
        _bwTagsBarRerender(blockId, tags);
    }

    function _bwSectionsBarHtml(blockId, sectionRaw) {
        const _ZONE_TITLES = {
            header: 'Шапка: навигация, логотип, топ-бар',
            hero: 'Главный экран / баннер',
            section: 'Контентная секция: фичи, услуги, о нас',
            sidebar: 'Боковая панель',
            card: 'Карточки, листинги, грид-элементы',
            form: 'Формы: регистрация, контакт, checkout',
            cta: 'Call-to-action блоки',
            media: 'Галерея, видео, слайдер',
            footer: 'Подвал страницы',
            overlay: 'Модалки, тосты, попапы',
            utility: 'Утилиты: разделители, пагинация, теги',
        };
        const zones = _bwParseSections(sectionRaw);
        const chipsHtml = zones.map(z =>
            `<span class="bwps-chip" title="${_ZONE_TITLES[z] || ''}">${esc(z)}<span class="bwps-chip-del" onclick="bwpsRemove(${blockId},'${z}')">×</span></span>`
        ).join('');
        const options = _BW_ALL_ZONES
            .filter(z => !zones.includes(z))
            .map(z => `<option value="${z}" title="${_ZONE_TITLES[z] || ''}">${z}</option>`)
            .join('');
        const addHtml = options
            ? `<select class="bwps-select" id="bwps-sel-${blockId}"><option value="">зона…</option>${options}</select><button class="bwps-add-btn" onclick="bwpsAdd(${blockId})" title="Добавить зону">+</button>`
            : '';
        return `<div class="bw-default-preview-sections" id="bwps-${blockId}">${chipsHtml}${addHtml}</div>`;
    }

    function _bwSectionsBarRerender(blockId, zones) {
        const container = document.getElementById(`bwps-${blockId}`);
        if (!container) return;
        const tmp = document.createElement('div');
        tmp.innerHTML = _bwSectionsBarHtml(blockId, zones);
        container.replaceWith(tmp.firstElementChild);
    }

    async function bwpsAdd(blockId) {
        const sel = document.getElementById(`bwps-sel-${blockId}`);
        const zone = sel ? sel.value : '';
        if (!zone) return;
        const block = _defaultBlocks.find(b => b.id === blockId);
        const zones = _bwParseSections(block ? block.section : null);
        if (zones.includes(zone)) return;
        zones.push(zone);
        const section = JSON.stringify(zones);
        await planningFetch(`/design/block/${blockId}`, {method: 'PUT', body: JSON.stringify({section})});
        if (block) block.section = section;
        _bwSectionsBarRerender(blockId, zones);
    }

    async function bwpsRemove(blockId, zone) {
        const block = _defaultBlocks.find(b => b.id === blockId);
        const zones = _bwParseSections(block ? block.section : null).filter(z => z !== zone);
        const section = zones.length ? JSON.stringify(zones) : null;
        await planningFetch(`/design/block/${blockId}`, {method: 'PUT', body: JSON.stringify({section})});
        if (block) block.section = section;
        _bwSectionsBarRerender(blockId, zones);
    }

    function _bwParseSections(raw) {
        if (!raw) return [];
        if (Array.isArray(raw)) return raw;
        try { const p = JSON.parse(raw); return Array.isArray(p) ? p : []; } catch(e) {}
        return raw ? [raw] : [];
    }

    async function selectBwBlock(blockId) {
        selectDefaultUiBlock(blockId);
    }

    // ── Default UI blocks ─────────────────────────────────────────────────────────
    let _defaultBlocks = [];
    let _defaultBlockActive = null;

    async function loadDefaultUiBlocks() {
        try {
            const data = await planningFetch('/design/ui-blocks');
            _defaultBlocks = data.result || [];
            _renderDefaultList(_defaultBlocks);
            if (_defaultBlocks.length) {
                const savedId = parseInt(localStorage.getItem('bw_active_default_block_id'), 10);
                const target = (savedId && _defaultBlocks.find(b => b.id === savedId)) ? savedId : _defaultBlocks[0].id;
                selectDefaultUiBlock(target);
            }
        } catch (e) {
            document.getElementById('bwDefaultList').innerHTML =
                '<div style="padding:12px;color:#ef4444;font-size:12px">Ошибка загрузки</div>';
        }
    }

    function _renderDefaultList(blocks) {
        const el = document.getElementById('bwDefaultList');
        if (!blocks.length) {
            el.innerHTML = '<div style="padding:12px;color:#94a3b8;font-size:12px">Нет блоков</div>';
            return;
        }
        el.innerHTML = blocks.map(b => {
            const isContainer = b.slots && b.slots !== 'null';
            return `<div class="bw-default-item${_defaultBlockActive === b.id ? ' active' : ''}"
                     onclick="selectDefaultUiBlock(${b.id})">
            <span class="bw-default-item-name" title="${esc(b.name)}">${esc(b.name)}</span>
            <span class="bw-default-item-badge${isContainer ? ' is-container' : ''}">${isContainer ? 'cnt' : 'item'}</span>
            <button class="bw-default-item-del" onclick="event.stopPropagation();deleteDefaultUiBlock(${b.id})" title="Удалить">✕</button>
        </div>`;
        }).join('');
    }

    async function deleteDefaultUiBlock(id) {
        if (!confirm('Удалить блок из библиотеки?')) return;
        try {
            await planningFetch(`/design/ui-blocks/${id}`, {method: 'DELETE'});
            _defaultBlocks = _defaultBlocks.filter(b => b.id !== id);
            _renderDefaultList(_defaultBlocks);
            if (_defaultBlockActive === id) {
                _defaultBlockActive = null;
                document.getElementById('bwPreviewContent').innerHTML = '<span class="bw-placeholder">Выберите виджет</span>';
            }
        } catch (e) {
            alert('Ошибка удаления: ' + (e.message || e));
        }
    }

    function filterDefaultBlocks(q) {
        q = q.toLowerCase().trim();
        const filtered = q
            ? _defaultBlocks.filter(b =>
                b.name.toLowerCase().includes(q) ||
                (b.tags && b.tags.toLowerCase().includes(q))
            )
            : _defaultBlocks;
        _renderDefaultList(filtered);
    }

    async function selectDefaultUiBlock(id) {
        _defaultBlockActive = id;
        localStorage.setItem('bw_active_default_block_id', id);
        document.querySelectorAll('.bw-default-item').forEach(el => {
            el.classList.toggle('active', parseInt(el.getAttribute('onclick').match(/\d+/)[0]) === id);
        });

        const container = document.getElementById('bwPreviewContent');
        container.innerHTML = '<div class="bw-placeholder" style="padding:12px">Загрузка…</div>';

        try {
            const data = await planningFetch(`/design/ui-blocks/${id}`);
            const b = data.result;
            _renderDefaultBlockPreview(b);
        } catch (e) {
            container.innerHTML = '<div style="padding:12px;color:#ef4444;font-size:12px">Ошибка загрузки блока</div>';
        }
    }

    function _renderDefaultBlockPreview(b) {
        const container = document.getElementById('bwPreviewContent');

        container.innerHTML = `
        <div class="bw-preview-name">project_design_ui_block #${b.id} ${esc(b.name)}</div>
        <div class="bw-preview-meta-row">
            ${_bwTagsBarHtml(b.id, b.tags)}
            ${_bwSectionsBarHtml(b.id, b.section)}
        </div>
        ${_bwPreviewSectionLabelHtml(b.id)}
        <div class="bw-iframe-wrap" id="bwdiw-${b.id}"></div>
        ${b.vars && b.vars !== '{}' ? `
        <details class="bw-css-details" style="margin-top:8px">
            <summary class="bw-css-summary">Переменные (vars)</summary>
            <textarea class="bw-css-textarea" readonly style="min-height:80px">${esc(JSON.stringify(JSON.parse(b.vars), null, 2))}</textarea>
        </details>` : ''}`;

        if (b.html) {
            const rendered = _fillTestData(b.html, b.vars, b.slots);
            // If still has unfilled slot placeholders — show vars table instead of blank iframe
            if (rendered.includes('[[slot:')) {
                const wrap = document.getElementById(`bwdiw-${b.id}`);
                wrap.style.padding = '8px 0';
                let varsObj = {};
                try {
                    varsObj = JSON.parse(b.vars || '{}');
                } catch {
                }
                const keys = Object.keys(varsObj);
                if (keys.length) {
                    wrap.innerHTML = `<div style="font-size:11px;color:#64748b;margin-bottom:6px">Переменные блока:</div>` +
                        keys.map(k => `<div style="display:flex;gap:6px;margin-bottom:3px;font-size:12px">
                        <span style="color:#6366f1;font-weight:600;min-width:140px">${esc(k)}</span>
                        <span style="color:#1e293b">${esc(String(varsObj[k]))}</span>
                    </div>`).join('');
                } else {
                    wrap.innerHTML = `<div style="color:#94a3b8;font-size:12px;font-style:italic">Блок-контейнер (слоты без шаблона)</div>`;
                }
            } else {
                document.getElementById(`bwdiw-${b.id}`).appendChild(_bwMakeIframe(_injectCdn(rendered), b.id));
            }
        }
    }

    function _injectCdn(html) {
        let result = html
            .replace(
                /<link[^>]+href=["']\/component\.css["'][^>]*>/gi,
                '<script src="https://cdn.tailwindcss.com"><\/script>'
            )
            .replace(
                /<script[^>]+src=["']\/component\.js["'][^>]*><\/script>/gi,
                '<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3/dist/cdn.min.js"><\/script>'
            )
            .replace(
                /<script[^>]+src=["']https?:\/\/[^"']*chart[^"']*["'][^>]*><\/script>/gi,
                '<script src="/static/js/chart.umd.min.js"><\/script>'
            );
        if (/new Chart\s*\(/.test(result) && !result.includes('chart.umd.min.js')) {
            result = '<script src="/static/js/chart.umd.min.js"><\/script>\n' + result;
        }
        return result;
    }

    function _fillVars(html, vars) {
        if (!vars) return html;
        return html.replace(/\[\[([\w]+)\]\]/g, (_, key) =>
            vars[key] !== undefined ? String(vars[key]) : '[[' + key + ']]'
        );
    }

    function _fillTestData(html, varsJson, slotsJson) {
        let result = html;

        // 1. Fill slot placeholders with N copies of child template
        if (slotsJson) {
            let slots;
            try {
                slots = JSON.parse(slotsJson);
            } catch {
                slots = [];
            }
            for (const slot of slots) {
                const placeholder = '[[slot:' + slot.name + ']]';
                if (!result.includes(placeholder)) continue;
                const tpl = slot.template;
                if (!tpl) continue;  // no template — leave placeholder visible
                const childVars = slot.vars || {};
                const count = Math.min(slot.max || 3, 3);
                const children = Array.from({length: count}, (_, i) => {
                    const indexed = {};
                    for (const [k, v] of Object.entries(childVars)) {
                        if (i === 0 || typeof v !== 'string') {
                            indexed[k] = v;
                        } else {
                            indexed[k] = v.replace(/\d+(\.\d+)?/, match => {
                                const n = parseFloat(match);
                                const step = n < 10 ? 1 : n < 100 ? Math.round(n * 0.5) : Math.round(n * 0.3);
                                return String(Math.round(n + i * step));
                            });
                        }
                    }
                    return _fillVars(tpl, indexed);
                }).join('\n');
                result = result.replace(placeholder, children);
            }
        }

        // 2. Fill remaining var placeholders with defaults from vars
        if (varsJson) {
            let vars;
            try {
                vars = JSON.parse(varsJson);
            } catch {
                vars = {};
            }
            result = _fillVars(result, vars);
        }

        return result;
    }

    document.addEventListener('DOMContentLoaded', loadDefaultUiBlocks);

    // ── Design tokens ─────────────────────────────────────────────────────────────
    let _bwDesignTokens = [];
    let _activeTokenId = null;
    let _bwActiveShell = null;

    async function _bwLoadTokens() {
        try {
            const data = await planningFetch('/design/tokens');
            _bwDesignTokens = data.result || [];
            if (_bwDesignTokens.length && _activeTokenId === null) _activeTokenId = _bwDesignTokens[0].id;
            // Replace token pills in any already-rendered section label
            const chipsHtml = _bwTokenChipsHtml();
            document.querySelectorAll('.bw-token-pills').forEach(container => {
                const tpl = document.createElement('template');
                tpl.innerHTML = chipsHtml;
                container.replaceWith(tpl.content.firstElementChild);
            });
            document.querySelectorAll('.bw-preview-iframe').forEach(iframe => _bwApplyTokenToIframe(iframe));
        } catch (e) {}
    }

    function _bwFlattenTokens(obj, prefix) {
        const result = {};
        for (const [k, v] of Object.entries(obj || {})) {
            const key = prefix ? prefix + '-' + k : k;
            if (v && typeof v === 'object' && !Array.isArray(v)) {
                // nested token format: {value: "#hex", description: "..."} → use value directly
                if ('value' in v) result[key] = v.value;
                else Object.assign(result, _bwFlattenTokens(v, key));
            } else {
                result[key] = v;
            }
        }
        return result;
    }

    function _bwApplyTokenToIframe(iframe) {
        const token = _bwDesignTokens.find(t => t.id === _activeTokenId);
        if (!token) return;
        try {
            const doc = iframe.contentDocument || iframe.contentWindow?.document;
            if (!doc || !doc.body) return;

            const flat = _bwFlattenTokens(token.tokens || {});
            const t = token.tokens || {};
            const c = t.colors || {};
            const typo = t.typography || {};
            const primary    = c.primary    || '';
            const secondary  = c.secondary  || primary;
            const background = c.background || '';
            const surface    = c.surface    || c.background || '';
            const textColor  = c.text       || '';
            const textMuted  = c.textMuted  || c.neutral    || '';
            const borderColor = c.border    || '';
            const accent     = c.accent     || primary;
            const errorColor = c.error      || '';
            const successColor = c.success  || '';
            const warningColor = c.warning  || '';
            const fontFamily = typo.fontFamily || flat['typography-fontFamily'] || '';
            const fontSize   = typo.fontSize   || flat['typography-fontSize']   || '';
            const borderRadius = t.borderRadius || flat['borderRadius'] || '';

            // CSS variables for project blocks that use --bw-*
            const cssVars = ':root{' + Object.entries(flat).map(([k, v]) => `--bw-${k}:${v}`).join(';') + '}';

            // Tailwind override rules — map token semantic colors onto Tailwind utility classes
            const rules = [];

            if (background) rules.push(`body{background-color:${background}!important;}`);
            if (textColor)  rules.push(`body{color:${textColor}!important;}`);
            if (fontFamily) rules.push(`body{font-family:'${fontFamily}',system-ui,sans-serif!important;}`);
            if (fontSize)   rules.push(`body{font-size:${fontSize}!important;}`);

            // Surface: white backgrounds
            if (surface)    rules.push(`[class*="bg-white"]{background-color:${surface}!important;}`);

            // Primary action colors (Tailwind blue/indigo are default action palette)
            if (primary) {
                rules.push(
                    `[class*="bg-blue-5"],[class*="bg-blue-6"],[class*="bg-indigo-5"],[class*="bg-indigo-6"],[class*="bg-violet-6"],[class*="bg-purple-6"]{background-color:${primary}!important;}`,
                    `[class*="text-blue-5"],[class*="text-blue-6"],[class*="text-indigo-5"],[class*="text-indigo-6"]{color:${primary}!important;}`,
                    `[class*="ring-blue-"],[class*="ring-indigo-"]{--tw-ring-color:${primary}!important;}`,
                    `a:not([class]){color:${primary}!important;}`
                );
            }
            if (secondary) {
                rules.push(`[class*="bg-blue-7"],[class*="bg-indigo-7"],[class*="bg-violet-7"]{background-color:${secondary}!important;}`);
            }

            // Border tokens
            if (borderColor) {
                rules.push(`[class*="border-gray-1"],[class*="border-gray-2"],[class*="divide-gray-2"]{border-color:${borderColor}!important;}`);
            }

            // Muted text
            if (textMuted) {
                rules.push(`[class*="text-gray-4"],[class*="text-gray-5"],[class*="text-gray-6"]{color:${textMuted}!important;}`);
            }

            // Status colors
            if (errorColor)   rules.push(`[class*="bg-red-5"],[class*="bg-red-6"]{background-color:${errorColor}!important;}[class*="text-red-"]{color:${errorColor}!important;}`);
            if (successColor) rules.push(`[class*="bg-green-5"],[class*="bg-green-6"]{background-color:${successColor}!important;}[class*="text-green-"]{color:${successColor}!important;}`);
            if (warningColor) rules.push(`[class*="bg-yellow-4"],[class*="bg-amber-4"],[class*="bg-yellow-5"],[class*="bg-amber-5"]{background-color:${warningColor}!important;}[class*="text-yellow-"],[class*="text-amber-"]{color:${warningColor}!important;}`);

            // Border radius
            if (borderRadius) {
                rules.push(`.rounded,.rounded-sm,.rounded-md,.rounded-lg{border-radius:${borderRadius}!important;}`);
            }

            let styleEl = doc.getElementById('_bw-token');
            if (!styleEl) {
                styleEl = doc.createElement('style');
                styleEl.id = '_bw-token';
                (doc.head || doc.documentElement).appendChild(styleEl);
            }
            styleEl.textContent = cssVars + rules.join('');

            // Google Font
            if (fontFamily) {
                const fontHref = 'https://fonts.googleapis.com/css2?family=' + encodeURIComponent(fontFamily) + ':wght@400;500;600;700&display=swap';
                let linkEl = doc.getElementById('_bw-font');
                if (!linkEl) {
                    linkEl = doc.createElement('link');
                    linkEl.id = '_bw-font';
                    linkEl.rel = 'stylesheet';
                    (doc.head || doc.documentElement).appendChild(linkEl);
                }
                if (linkEl.href !== fontHref) linkEl.href = fontHref;
            }
        } catch (e) {}
    }

    function _bwTokenChipsHtml() {
        if (!_bwDesignTokens.length) return '';
        return '<span class="bw-token-pills">' +
            _bwDesignTokens.map(t =>
                `<button class="bw-token-chip${_activeTokenId === t.id ? ' active' : ''}" onclick="_bwTokenToggle(${t.id})">${esc(t.title || t.name)}</button>`
            ).join('') + '</span>';
    }

    function _bwTokenToggle(tokenId) {
        if (_activeTokenId === tokenId) return;
        _activeTokenId = tokenId;
        document.querySelectorAll('.bw-token-chip').forEach(el => {
            const id = parseInt(el.getAttribute('onclick').match(/\d+/)?.[0]);
            el.classList.toggle('active', id === _activeTokenId);
        });
        document.querySelectorAll('.bw-preview-iframe').forEach(iframe => _bwApplyTokenToIframe(iframe));
    }

    function _bwSetPreviewWidth(w) {
        if (!_bwActiveShell) return;
        _bwActiveShell.style.width = w + 'px';
        const badge = _bwActiveShell.querySelector('.bw-size-badge');
        const iframe = _bwActiveShell.querySelector('.bw-preview-iframe');
        if (badge) badge.textContent = w + ' × ' + (iframe?.offsetHeight || 0);
        _bwUpdateBpButtons(w);
    }

    function _bwUpdateBpButtons(w) {
        document.querySelectorAll('.bw-bp-btn').forEach(btn => btn.classList.toggle('active', parseInt(btn.dataset.w) === w));
    }

    function _bwPreviewSectionLabelHtml(blockId = null) {
        const bpBtns = [375, 768, 1280, 1920].map(w =>
            `<button class="bw-bp-btn" data-w="${w}" onclick="_bwSetPreviewWidth(${w})">${w}</button>`
        ).join('');
        const saveChip = blockId
            ? `<button class="bw-save-size-chip" onclick="_bwSaveCurrentSize(${blockId})" title="Сохранить текущий размер как минимальный">Save min w&h</button>`
            : '';
        return `<div class="bw-preview-section-label">Превью${_bwTokenChipsHtml()}<span class="bw-bp-pills">${bpBtns}</span>${saveChip}</div>`;
    }

    // ── Iframe helper ─────────────────────────────────────────────────────────────
    async function _bwSaveCurrentSize(blockId) {
        if (!_bwActiveShell) return;
        const iframe = _bwActiveShell.querySelector('.bw-preview-iframe');
        const w = _bwActiveShell.offsetWidth;
        const h = iframe ? iframe.offsetHeight : 0;
        const chip = document.querySelector('.bw-save-size-chip');
        try {
            await planningFetch(`/design/block/${blockId}`, {
                method: 'PUT',
                body: JSON.stringify({width_min: w, height_min: h}),
            });
            if (chip) {
                const orig = chip.textContent;
                chip.textContent = '✓ Сохранено';
                chip.style.background = '#16a34a';
                chip.style.color = '#fff';
                chip.style.borderColor = '#16a34a';
                setTimeout(() => { chip.textContent = orig; chip.style.background = ''; chip.style.color = ''; chip.style.borderColor = ''; }, 1400);
            }
        } catch (e) {}
    }

    function _bwMakeIframe(srcdoc, blockId = null) {
        const shell = document.createElement('div');
        shell.className = 'bw-resize-shell';
        shell.style.width = '1280px';
        shell.style.maxWidth = '100%';

        const iframe = document.createElement('iframe');
        iframe.className = 'bw-preview-iframe';
        iframe.setAttribute('sandbox', 'allow-same-origin allow-scripts');
        iframe.srcdoc = srcdoc;

        const _resize = (doc) => {
            try {
                doc.querySelectorAll('*').forEach(el => {
                    const pos = getComputedStyle(el).position;
                    if (pos === 'fixed' || pos === 'sticky') el.style.position = 'relative';
                });
                const h = doc.documentElement.scrollHeight || doc.body?.scrollHeight || 0;
                if (h > 50) iframe.style.height = h + 'px';
            } catch {}
        };

        iframe.addEventListener('load', () => {
            try {
                const doc = iframe.contentDocument || iframe.contentWindow?.document;
                if (!doc) return;
                _resize(doc);
                const badge = shell.querySelector('.bw-size-badge');
                if (badge) badge.textContent = shell.offsetWidth + ' × ' + iframe.offsetHeight;

                // Apply tokens — if not loaded yet, retry until they appear (max ~3s)
                let tokenTries = 0;
                const applyOrRetry = () => {
                    if (_bwDesignTokens.length) {
                        _bwApplyTokenToIframe(iframe);
                    } else if (tokenTries++ < 6) {
                        setTimeout(applyOrRetry, 500);
                    }
                };
                applyOrRetry();

                setTimeout(() => { _resize(doc); if (badge) badge.textContent = shell.offsetWidth + ' × ' + iframe.offsetHeight; }, 600);
                setTimeout(() => { _resize(doc); if (badge) badge.textContent = shell.offsetWidth + ' × ' + iframe.offsetHeight; }, 1500);
            } catch {}
        });

        const dragE = document.createElement('div');
        dragE.className = 'bw-drag-e';
        const dragS = document.createElement('div');
        dragS.className = 'bw-drag-s';
        const dragSE = document.createElement('div');
        dragSE.className = 'bw-drag-se';

        const badge = document.createElement('span');
        badge.className = 'bw-size-badge';
        badge.textContent = '1280 × …';

        shell.append(iframe, dragE, dragS, dragSE, badge);
        _bwActiveShell = shell;
        _bwUpdateBpButtons(1280);

        dragE.addEventListener('mousedown', e => {
            e.preventDefault();
            iframe.style.pointerEvents = 'none';
            document.body.style.userSelect = 'none';
            const startX = e.clientX, startW = shell.offsetWidth;
            const onMove = ev => {
                const w = Math.max(200, startW + ev.clientX - startX);
                shell.style.width = w + 'px';
                badge.textContent = w + ' × ' + iframe.offsetHeight;
                _bwUpdateBpButtons(w);
            };
            const onUp = () => {
                iframe.style.pointerEvents = '';
                document.body.style.userSelect = '';
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });

        dragS.addEventListener('mousedown', e => {
            e.preventDefault();
            iframe.style.pointerEvents = 'none';
            document.body.style.userSelect = 'none';
            const startY = e.clientY, startH = iframe.offsetHeight;
            const onMove = ev => {
                const h = Math.max(40, startH + ev.clientY - startY);
                iframe.style.height = h + 'px';
                badge.textContent = shell.offsetWidth + ' × ' + h;
            };
            const onUp = () => {
                iframe.style.pointerEvents = '';
                document.body.style.userSelect = '';
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });

        dragSE.addEventListener('mousedown', e => {
            e.preventDefault();
            iframe.style.pointerEvents = 'none';
            document.body.style.userSelect = 'none';
            const startX = e.clientX, startY = e.clientY, startW = shell.offsetWidth, startH = iframe.offsetHeight;
            const onMove = ev => {
                const w = Math.max(200, startW + ev.clientX - startX);
                const h = Math.max(40, startH + ev.clientY - startY);
                shell.style.width = w + 'px';
                iframe.style.height = h + 'px';
                badge.textContent = w + ' × ' + h;
                _bwUpdateBpButtons(w);
            };
            const onUp = () => {
                iframe.style.pointerEvents = '';
                document.body.style.userSelect = '';
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });

        return shell;
    }

    function toggleBwGenForm() {
        const form = document.getElementById('bwGenForm');
        const open = form.classList.toggle('open');
        if (open) document.getElementById('bwgName').focus();
    }

    let _bwMicRecognition = null;
    let _bwMicActive = false;

    function toggleBwMic() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            alert('Ваш браузер не поддерживает распознавание речи');
            return;
        }
        if (_bwMicActive) {
            _bwMicRecognition && _bwMicRecognition.stop();
            return;
        }
        _bwMicRecognition = new SpeechRecognition();
        _bwMicRecognition.lang = 'ru-RU';
        _bwMicRecognition.continuous = true;
        _bwMicRecognition.interimResults = false;
        _bwMicRecognition.onstart = () => {
            _bwMicActive = true;
            const btn = document.getElementById('bwMicBtn');
            if (btn) btn.classList.add('recording');
        };
        _bwMicRecognition.onend = () => {
            _bwMicActive = false;
            const btn = document.getElementById('bwMicBtn');
            if (btn) btn.classList.remove('recording');
        };
        _bwMicRecognition.onresult = (e) => {
            const transcript = Array.from(e.results).map(r => r[0].transcript).join(' ');
            const ta = document.getElementById('bwgDesc');
            if (ta) ta.value = (ta.value ? ta.value + ' ' : '') + transcript;
        };
        _bwMicRecognition.start();
    }

    async function generateBwBlock() {
        const name = (document.getElementById('bwgName')?.value || '').trim();
        const desc = (document.getElementById('bwgDesc')?.value || '').trim();
        if (!name) {
            alert('Укажите название блока');
            return;
        }
        if (!desc) {
            alert('Опишите блок');
            return;
        }
        if (!_bwProjectId) {
            alert('Выберите проект');
            return;
        }

        const btn = document.getElementById('bwgSubmitBtn');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Генерация…';
        }

        try {
            const data = await planningFetch(`/design/${_bwProjectId}/block/generate`, {
                method: 'POST',
                body: JSON.stringify({name, description: desc}),
            });
            if (data.error) {
                alert(data.error);
                return;
            }
            _defaultBlocks.push(data.result);
            _renderDefaultList(_defaultBlocks);
            // Close form and clear
            document.getElementById('bwGenForm').classList.remove('open');
            document.getElementById('bwgName').value = '';
            document.getElementById('bwgDesc').value = '';
            selectDefaultUiBlock(data.result.id);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Сгенерировать';
            }
        }
    }

    /* Page preview */
    function renderPagePreview() {
        const wrap = document.getElementById('pagePreviewWrap');
        if (!wrap) return;

        if (!_selectedPageId || !_wfBlocks.length) {
            wrap.innerHTML = '<div class="pages-preview-placeholder">' + (_selectedPageId ? 'Нет блоков на странице' : 'Выберите страницу') + '</div>';
            return;
        }

        let allCss = '';
        const levelDivs = _gridLayout.map((level, levelIdx) => {
            const levelFlatStart = _gridLayout.slice(0, levelIdx).reduce((a, l) => a + l.w.length, 0);
            const sectionDivs = level.w.map((width, col) => {
                const flatIdx = levelFlatStart + col;
                const blocksInSection = _wfBlocks
                    .filter(b => (b.section || 0) === flatIdx)
                    .sort((a, b2) => (a.order_index || 0) - (b2.order_index || 0));

                let secHtml = '';
                for (const item of blocksInSection) {
                    // All blocks live in project_design_ui_block and have html directly.
                    // Check cache first (full data), then _defaultBlocks (metadata only, triggers loading…).
                    const uiBlock = _uiBlockCache[item.block_id] || _defaultBlocks.find(b => b.id === item.block_id);

                    if (uiBlock) {
                        if (uiBlock.html) {
                            const rendered = _fillTestData(uiBlock.html, uiBlock.vars, uiBlock.slots);
                            secHtml += `<div style="overflow:hidden">${_injectCdn(rendered)}</div>`;
                        } else {
                            secHtml += `<div style="padding:10px;border:1px dashed #e2e8f0;color:#94a3b8;font-size:11px;margin-bottom:4px">${esc(uiBlock.name)} (загрузка…)</div>`;
                        }
                        continue;
                    }

                    // Fallback: legacy project blocks with widgets
                    const projBlock = _allBlocks.find(b => b.id === item.block_id);
                    if (!projBlock) continue;
                    const widget = (projBlock.widgets || []).find(w =>
                        (item.widget_id && w.id === item.widget_id) || w.name === item.widget_name
                    ) || (projBlock.widgets || [])[0];
                    if (!widget) {
                        secHtml += `<div style="padding:10px;border:1px dashed #e2e8f0;color:#94a3b8;font-size:11px;margin-bottom:4px">${esc(projBlock.title || projBlock.name)} (нет HTML)</div>`;
                        continue;
                    }
                    if (widget.css) allCss += widget.css + '\n';
                    secHtml += widget.html
                        ? widget.html
                        : `<div style="padding:10px;border:1px dashed #e2e8f0;color:#94a3b8;font-size:11px;margin-bottom:4px">${esc(projBlock.title || projBlock.name)}: ${esc(widget.name)}</div>`;
                }
                return `<div style="width:${width}%;box-sizing:border-box;overflow:hidden;flex-shrink:0">${secHtml}</div>`;
            }).join('');

            return `<div style="display:flex;width:100%;min-height:${level.h}px">${sectionDivs}</div>`;
        }).join('');

        const hasContent = allCss || levelDivs.replace(/<[^>]*>/g, '').trim();
        if (!hasContent) {
            wrap.innerHTML = '<div class="pages-preview-placeholder">Блоки без HTML/CSS — добавьте виджеты</div>';
            return;
        }

        const srcdoc = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>*,*::before,*::after{box-sizing:border-box}html,body{margin:0;padding:0;font-family:system-ui,-apple-system,sans-serif}${allCss}</style></head><body>${levelDivs}</body></html>`;
        const iframe = document.createElement('iframe');
        iframe.style.cssText = 'width:100%;height:100%;border:none;display:block';
        iframe.setAttribute('sandbox', 'allow-same-origin allow-scripts');
        iframe.srcdoc = srcdoc;
        wrap.innerHTML = '';
        wrap.appendChild(iframe);
    }

    /* Pages horizontal splitter */
    (function initPagesHSplitter() {
        function ready(fn) {
            if (document.readyState !== 'loading') fn(); else document.addEventListener('DOMContentLoaded', fn);
        }

        ready(() => {
            const splitter = document.getElementById('pagesHSplitter');
            const topRow = document.getElementById('pagesTopRow');
            if (!splitter || !topRow) return;

            let dragging = false, startY = 0, startH = 0;

            splitter.addEventListener('mousedown', e => {
                dragging = true;
                startY = e.clientY;
                startH = topRow.offsetHeight;
                splitter.classList.add('active');
                document.body.style.cursor = 'row-resize';
                document.body.style.userSelect = 'none';
                e.preventDefault();
            });

            document.addEventListener('mousemove', e => {
                if (!dragging) return;
                const newH = Math.max(120, Math.min(startH + e.clientY - startY, window.innerHeight * 0.85));
                topRow.style.height = newH + 'px';
                topRow.style.flex = 'none';
            });

            document.addEventListener('mouseup', () => {
                if (!dragging) return;
                dragging = false;
                splitter.classList.remove('active');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            });
        });
    })();

    /* Splitters */
    document.addEventListener('DOMContentLoaded', function () {
        initSidebarResizer('bwVSplitter', 'design_bw_left_w', document.getElementById('bwColLeft'), 140, 600);
        initSidebarResizer('pagesVSplitter', 'design_pages_tree_w', document.querySelector('.pages-tree-col'), 140, 500);
        initSidebarResizer('uiCompVSplitter', 'design_ui_comp_list_w', document.querySelector('.ui-comp-list-col'), 180, 600);

        /* Right-side panel: dragging right shrinks, dragging left grows */
        (function () {
            const splitter = document.getElementById('pagesEditorVSplitter');
            const panel = document.getElementById('blockLibraryCol');
            if (!splitter || !panel) return;
            const minW = 140, maxW = 500;
            const saved = parseInt(localStorage.getItem('design_block_lib_w'), 10);
            if (saved && saved >= minW && saved <= maxW) panel.style.width = saved + 'px';
            splitter.addEventListener('mousedown', e => {
                const startX = e.clientX, startW = panel.getBoundingClientRect().width;
                splitter.classList.add('dragging');
                document.body.style.cursor = 'col-resize';
                document.body.style.userSelect = 'none';

                function onMove(e) {
                    const w = Math.min(maxW, Math.max(minW, startW - (e.clientX - startX)));
                    panel.style.width = w + 'px';
                }

                function onUp() {
                    splitter.classList.remove('dragging');
                    document.body.style.cursor = '';
                    document.body.style.userSelect = '';
                    localStorage.setItem('design_block_lib_w', parseInt(panel.style.width, 10));
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onUp);
                }

                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
                e.preventDefault();
            });
        })();

    });

    function onProjectChange() {
        const currentTab = document.querySelector('.page-tab.active')?.dataset?.tab;
        if (currentTab === 'prototype') {
            loadDesignTokens();
            loadDesignStates();
            loadProjectChips();
        } else if (currentTab === 'blocks-widgets') loadBlocksWidgets();
        else if (currentTab === 'pages') loadPagesTab();
    }

    async function initProjectSelects() {
        const data = await planningFetch('/planning/project/list');
        _allProjects = data.result || [];
        const sel = document.getElementById('globalProjectSel');
        if (sel) {
            _allProjects.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = `#${p.id} ${p.title || (p.idea || '').slice(0, 55)}`;
                sel.appendChild(opt);
            });
        }

        const params = new URLSearchParams(location.search);
        const hash = location.hash.replace('#', '');
        const pid = params.get('project_id') || (_allProjects[0] ? String(_allProjects[0].id) : '');

        if (pid && sel) sel.value = pid;

        // map old hash aliases
        const hashMap = {blocks: 'blocks-widgets', widgets: 'blocks-widgets'};
        const normalizedHash = hashMap[hash] || hash;
        const validHashes = ['prototype', 'blocks-widgets', 'pages', 'ui-components'];
        const savedTab = localStorage.getItem('design_active_tab');
        const activeHash = validHashes.includes(normalizedHash) ? normalizedHash
            : validHashes.includes(savedTab) ? savedTab
                : null;
        const activeTabEl = document.querySelector('.page-tab.active');
        const currentTab = activeHash || activeTabEl?.dataset?.tab;

        if (activeHash) {
            document.querySelectorAll('.page-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            const tab = document.querySelector(`.page-tab[data-tab="${activeHash}"]`);
            if (tab) tab.classList.add('active');
            const panel = document.getElementById(`tab-${activeHash}`);
            if (panel) panel.classList.add('active');
        }

        if (pid) {
            if (currentTab === 'prototype') {
                loadDesignTokens();
                loadDesignStates();
                loadProjectChips();
            }
            if (currentTab === 'blocks-widgets') loadBlocksWidgets();
            if (currentTab === 'pages') loadPagesTab();
        }
    }

    // ═══════════════════════════════════════════════
    // СТРАНИЦЫ — wireframe drag-and-drop builder
    // ═══════════════════════════════════════════════

    let _allBlocks = [];          // все блоки проекта с виджетами
    let _allPagesFull = [];       // все страницы проекта с блоками
    let _selectedPageId = null;
    let _wfBlocks = [];           // текущие блоки в вайрфрейме выбранной страницы
    // [{w:[%,...], h:px}, ...] — уровни с шириной секций и высотой
    let _gridLayout = [{w: [33, 33, 34], h: 300}, {w: [33, 33, 34], h: 300}, {w: [33, 33, 34], h: 300}];
    let _libActiveId = null;
    let _libDefaultActiveId = null;

    async function loadPagesTab() {
        const pid = document.getElementById('globalProjectSel').value;
        if (!pid) {
            document.getElementById('pagesTree').innerHTML = '<div class="no-blocks-msg">Выберите проект</div>';
            return;
        }

        document.getElementById('pagesTree').innerHTML = '<div class="no-blocks-msg">Загрузка…</div>';
        document.getElementById('blockLibrary').innerHTML = '<div class="no-blocks-msg" style="padding:20px;font-size:12px">Загрузка…</div>';

        const fetches = [
            planningFetch(`/design/${pid}/blocks`),
            planningFetch(`/design/${pid}/wireframe-pages`),
        ];
        if (!_defaultBlocks.length) fetches.push(planningFetch('/design/ui-blocks'));
        const [blocksData, pagesData, defaultData] = await Promise.all(fetches);

        _allBlocks = blocksData.result || [];
        _allPagesFull = pagesData.result || [];
        if (defaultData) _defaultBlocks = defaultData.result || [];
        _selectedPageId = null;
        _wfBlocks = [];
        _gridLayout = [{w: [33, 33, 34], h: 300}, {w: [33, 33, 34], h: 300}, {w: [33, 33, 34], h: 300}];

        renderPageTree();
        renderBlockLibrary('');


        // Reset editor
        document.getElementById('wfPlaceholder').style.display = '';
        document.getElementById('wfDropZone').innerHTML = `<div class="wf-placeholder" id="wfPlaceholder">
        <div style="font-size:32px">🗂️</div>
        <div>Выберите страницу из дерева слева</div>
        <div style="font-size:12px;color:#cbd5e1">Перетаскивайте блоки из библиотеки справа</div>
    </div>`;
        document.getElementById('btnAutoWireframe').style.display = 'none';
        document.getElementById('btnSaveWireframe').style.display = 'none';
    }

    function renderPageTree() {
        const tree = document.getElementById('pagesTree');
        if (!_allPagesFull.length) {
            tree.innerHTML = '<div class="no-blocks-msg">Страницы не сгенерированы</div>';
            return;
        }

        // Group into parent/child
        const roots = _allPagesFull.filter(p => !p.parent_id);
        const childrenOf = {};
        _allPagesFull.filter(p => p.parent_id).forEach(p => {
            (childrenOf[p.parent_id] = childrenOf[p.parent_id] || []).push(p);
        });

        tree.innerHTML = '';

        function addPageItem(p, isChild) {
            const blockCount = (p.blocks || []).length;
            const div = document.createElement('div');
            div.className = `page-tree-item${isChild ? ' child' : ''}${_selectedPageId === p.id ? ' active' : ''}`;
            div.dataset.pageId = p.id;
            div.onclick = () => selectWfPage(p.id);
            div.innerHTML = `
            <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.name)}</span>
            ${blockCount ? `<span class="block-cnt">${blockCount}</span>` : ''}
            <span class="ptype-badge">${esc(p.page_type || 'page')}</span>
        `;
            tree.appendChild(div);
            (childrenOf[p.id] || []).forEach(c => addPageItem(c, true));
        }

        roots.forEach(p => addPageItem(p, false));
    }

    function renderBlockLibrary(filter) {
        const lib = document.getElementById('blockLibrary');
        const q = (filter || '').toLowerCase();

        let html = '';

        // Section 1: project blocks
        const projectItems = q
            ? _allBlocks.filter(b => b.name.toLowerCase().includes(q) || (b.description || '').toLowerCase().includes(q))
            : _allBlocks;
        if (projectItems.length) {
            html += '<div class="lib-section-label">Блоки проекта</div>';
            html += projectItems.map(b => `
            <div class="lib-block-item${_libActiveId === b.id ? ' active' : ''}"
                 draggable="true"
                 ondragstart="onLibDragStart(event, ${b.id}, 'project')"
                 onclick="selectLibBlock(${b.id})"
                 title="${esc(b.description || b.name)}">
                <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px">${esc(b.name)}</span>
            </div>`).join('');
        }

        // Section 2: default UI blocks
        const defItems = q
            ? _defaultBlocks.filter(b => b.name.toLowerCase().includes(q) || (b.tags || '').toLowerCase().includes(q))
            : _defaultBlocks;
        if (defItems.length) {
            html += '<div class="lib-section-label">Блоки по умолчанию</div>';
            html += defItems.map(b => {
                const isContainer = !!b.slots;
                return `<div class="lib-block-item${_libDefaultActiveId === b.id ? ' active' : ''}"
                 draggable="true"
                 ondragstart="onLibDragStart(event, ${b.id}, 'default')"
                 onclick="selectLibDefaultBlock(${b.id})"
                 title="${esc(b.name)}">
                <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px">${esc(b.name)}</span>
                <span class="bw-default-item-badge${isContainer ? ' is-container' : ''}">${isContainer ? 'cnt' : 'item'}</span>
            </div>`;
            }).join('');
        }

        if (!html) {
            lib.innerHTML = '<div class="no-blocks-msg" style="padding:20px;font-size:12px">Нет блоков</div>';
        } else {
            lib.innerHTML = html;
        }
    }

    function filterLibBlocks() {
        renderBlockLibrary(document.getElementById('libSearch').value);
    }

    function selectLibBlock(id) {
        _libActiveId = id;
        _libDefaultActiveId = null;
        renderBlockLibrary(document.getElementById('libSearch').value);
        const b = _allBlocks.find(b => b.id === id);
        if (!b) return;
        const wrap = document.getElementById('libBlockPreview');
        wrap.innerHTML = '<div style="padding:12px">' +
            '<div style="font-weight:700;font-size:13px;margin-bottom:4px">' + esc(b.name) + '</div>' +
            (b.description ? '<div style="color:#64748b;font-size:12px;line-height:1.5">' + esc(b.description) + '</div>' : '') +
            '</div>';
    }

    async function selectLibDefaultBlock(id) {
        _libActiveId = null;
        _libDefaultActiveId = id;
        renderBlockLibrary(document.getElementById('libSearch').value);
        const data = await planningFetch('/design/ui-blocks/' + id);
        const b = data.result;
        if (!b) return;
        const wrap = document.getElementById('libBlockPreview');
        wrap.innerHTML = '<div style="padding:12px 14px">' +
            '<div class="bw-preview-name">project_design_ui_block #' + b.id + ' ' + esc(b.name) + '</div>' +
            '<div class="bw-preview-meta-row">' +
            _bwTagsBarHtml(b.id, b.tags) +
            _bwSectionsBarHtml(b.id, b.section) +
            '</div>' +
            _bwPreviewSectionLabelHtml(b.id) +
            '<div class="bw-iframe-wrap" id="libprev-' + b.id + '"></div>' +
            '</div>';
        if (b.html) {
            const rendered = _fillTestData(b.html, b.vars, b.slots);
            const prevWrap = document.getElementById('libprev-' + b.id);
            if (!rendered.includes('[[slot:')) {
                prevWrap.appendChild(_bwMakeIframe(_injectCdn(rendered), b.id));
            } else {
                let varsObj = {};
                try {
                    varsObj = JSON.parse(b.vars || '{}');
                } catch (e) {
                }
                const keys = Object.keys(varsObj);
                prevWrap.style.padding = '8px 0';
                if (keys.length) {
                    prevWrap.innerHTML = '<div style="font-size:11px;color:#64748b;margin-bottom:6px">Переменные блока:</div>' +
                        keys.map(k => '<div style="font-size:12px;margin-bottom:3px"><span style="color:#6366f1;font-weight:600;min-width:120px;display:inline-block">' + esc(k) + '</span> ' + esc(String(varsObj[k])) + '</div>').join('');
                } else {
                    prevWrap.innerHTML = '<div style="color:#94a3b8;font-size:12px;font-style:italic">Блок-контейнер (слоты без шаблона)</div>';
                }
            }
        }
    }

    function selectWfPage(pageId) {
        _selectedPageId = pageId;
        _dragSrcBlockIdx = null;

        // Update tree active state
        document.querySelectorAll('.page-tree-item').forEach(el => {
            el.classList.toggle('active', parseInt(el.dataset.pageId) === pageId);
        });

        const page = _allPagesFull.find(p => p.id === pageId);
        if (!page) return;

        _gridLayout = _normalizeGridLayout(page.grid_layout);

        // Build current wireframe blocks
        _wfBlocks = (page.blocks || [])
            .sort((a, b) => (a.section || 0) - (b.section || 0) || a.order_index - b.order_index)
            .map(pb => ({
                block_id: pb.block_id,
                block_name: pb.block_name,
                widget_name: pb.widget_name || '',
                widget_id: pb.widget_id || null,
                section: pb.section || 0,
                order_index: pb.order_index || 0,
            }));

        renderWireframeEditor();
        document.getElementById('btnAutoWireframe').style.display = '';
        document.getElementById('btnSaveWireframe').style.display = '';
        document.getElementById('btnSavePage').style.display = '';

        // Fill page property fields
        const nameInput = document.getElementById('pageNameInput');
        const typeSelect = document.getElementById('pageTypeSelect');
        const sep = document.querySelector('.pages-prop-sep');
        if (nameInput) { nameInput.value = page.name || ''; nameInput.style.display = ''; }
        if (typeSelect) { typeSelect.value = page.page_type || 'feature'; typeSelect.style.display = ''; }
        if (sep) sep.style.display = '';

        // Prefetch full html/vars/slots for all blocks not yet cached
        const uiBlockIds = [...new Set(_wfBlocks.map(b => b.block_id))];
        uiBlockIds.forEach(bid => {
            if (!_uiBlockCache[bid]) {
                planningFetch(`/design/ui-blocks/${bid}`).then(data => {
                    if (data && data.result) {
                        _uiBlockCache[bid] = data.result;
                        renderPagePreview();
                    }
                });
            }
        });
    }

    let _dragSrcBlockIdx = null;
    let _dragLibBlockId = null;
    let _dragLibBlockType = null; // 'project' | 'default'
    const _uiBlockCache = {}; // id → full block data with html/vars/slots

    function onLibDragStart(event, id, type) {
        _dragLibBlockId = id;
        _dragLibBlockType = type;
        _dragSrcBlockIdx = null;
        event.dataTransfer.effectAllowed = 'copy';
    }

    function onBlockDragStart(event, idx) {
        _dragSrcBlockIdx = idx;
        _dragLibBlockId = null;
        _dragLibBlockType = null;
        event.dataTransfer.effectAllowed = 'move';
        event.currentTarget.classList.add('dragging');
    }

    function onBlockDragEnd(event) {
        event.currentTarget.classList.remove('dragging');
    }

    function onSectionDragOver(event) {
        event.preventDefault();
        event.currentTarget.classList.add('drag-over-section');
    }

    function onSectionDragLeave(event) {
        if (!event.currentTarget.contains(event.relatedTarget)) {
            event.currentTarget.classList.remove('drag-over-section');
        }
    }

    function onSectionDrop(event, flatIdx) {
        event.preventDefault();
        event.currentTarget.classList.remove('drag-over-section');

        if (_dragSrcBlockIdx !== null) {
            const block = _wfBlocks[_dragSrcBlockIdx];
            if (block) {
                block.section = flatIdx;
                const secBlocks = _wfBlocks.filter(b => (b.section || 0) === flatIdx && b !== block);
                block.order_index = secBlocks.length;
            }
            _dragSrcBlockIdx = null;
            renderWireframeEditor();
        } else if (_dragLibBlockId !== null) {
            const isDefault = _dragLibBlockType === 'default';
            const pool = isDefault ? _defaultBlocks : _allBlocks;
            const b = pool.find(b => b.id === _dragLibBlockId);
            if (b) {
                const secBlocks = _wfBlocks.filter(wb => (wb.section || 0) === flatIdx);
                _wfBlocks.push({
                    block_id: b.id,
                    block_name: b.name,
                    widget_name: '',
                    widget_id: null,
                    section: flatIdx,
                    order_index: secBlocks.length,
                });
                renderWireframeEditor();
                if (!_uiBlockCache[b.id]) {
                    planningFetch(`/design/ui-blocks/${b.id}`).then(data => {
                        if (data && data.result) {
                            _uiBlockCache[b.id] = data.result;
                            renderPagePreview();
                        }
                    });
                }
            }
            _dragLibBlockId = null;
            _dragLibBlockType = null;
        }
    }

    // ── Layout helpers ──────────────────────────────────────────────────────────
    function _normalizeGridLayout(raw) {
        const def = [{w: [33, 33, 34], h: 300}, {w: [33, 33, 34], h: 300}, {w: [33, 33, 34], h: 300}];
        if (!Array.isArray(raw) || !raw.length) return def;
        if (typeof raw[0] === 'number') {
            // Old format [3, 3, 3]
            return raw.map(cols => {
                cols = Math.max(1, cols);
                const each = Math.floor(100 / cols);
                const ws = Array(cols).fill(each);
                ws[0] += 100 - ws.reduce((a, b) => a + b, 0);
                return {w: ws, h: 300};
            });
        }
        return raw.map(lvl => ({
            w: Array.isArray(lvl.w) && lvl.w.length ? lvl.w.map(Number) : [100],
            h: parseInt(lvl.h) || 300,
        }));
    }

    function _firstFlatIdxOfLevel(levelIdx) {
        return _gridLayout.slice(0, levelIdx).reduce((a, lvl) => a + lvl.w.length, 0);
    }

    function _totalSections() {
        return _gridLayout.reduce((a, lvl) => a + lvl.w.length, 0);
    }

    // ── Renderer ─────────────────────────────────────────────────────────────────
    function renderWireframeEditor() {
        const zone = document.getElementById('wfDropZone');
        zone.innerHTML = '';

        _gridLayout.forEach((level, levelIdx) => {
            const levelCols = level.w.length;
            const levelEl = document.createElement('div');
            levelEl.className = 'wf-level';
            levelEl.dataset.level = levelIdx;

            // Level control bar
            const bar = document.createElement('div');
            bar.className = 'wf-level-bar';
            bar.innerHTML = `
            <span class="wf-level-label">Уровень ${levelIdx + 1}
                <span style="font-weight:400;color:#94a3b8">(${levelCols} ${levelCols === 1 ? 'секция' : levelCols < 5 ? 'секции' : 'секций'})</span>
            </span>
            <span class="wf-level-height">
                h: <input class="wf-size-input" type="number" min="40" max="2000" step="10"
                    value="${level.h}" onchange="setLevelHeight(${levelIdx}, this.value)"
                    onclick="event.stopPropagation()" title="Высота уровня (px)">px
            </span>
            <span class="wf-level-actions">
                <button class="wf-level-btn" onclick="addSectionToLevel(${levelIdx})" title="Добавить секцию">+ Секция</button>
                <button class="wf-level-btn wf-level-btn-danger" onclick="removeSectionFromLevel(${levelIdx})"
                    title="Удалить последнюю секцию" ${levelCols <= 1 ? 'disabled' : ''}>− Секция</button>
                <button class="wf-level-btn" onclick="addLevel(${levelIdx})" title="Добавить уровень ниже">+ Уровень ↓</button>
                <button class="wf-level-btn wf-level-btn-danger" onclick="removeLevel(${levelIdx})"
                    title="Удалить уровень" ${_gridLayout.length <= 1 ? 'disabled' : ''}>✕</button>
            </span>
        `;
            levelEl.appendChild(bar);

            // Sections row
            const sectionsRow = document.createElement('div');
            sectionsRow.className = 'wf-level-sections';
            sectionsRow.style.gridTemplateColumns = level.w.map(w => w + '%').join(' ');

            const levelFlatStart = _firstFlatIdxOfLevel(levelIdx);

            for (let col = 0; col < levelCols; col++) {
                const flatIdx = levelFlatStart + col;
                const cell = document.createElement('div');
                cell.className = 'wf-section';
                cell.dataset.section = flatIdx;
                cell.addEventListener('dragover', onSectionDragOver);
                cell.addEventListener('dragleave', onSectionDragLeave);
                cell.addEventListener('drop', e => onSectionDrop(e, flatIdx));

                const secLabel = document.createElement('div');
                secLabel.className = 'wf-section-label';
                secLabel.innerHTML = `
                <span>${levelIdx + 1}.${col + 1}</span>
                <input class="wf-size-input" type="number" min="5" max="95" step="5"
                    value="${level.w[col]}" onchange="setSectionWidth(${levelIdx}, ${col}, this.value)"
                    onclick="event.stopPropagation()" title="Ширина секции (%)">%`;
                cell.appendChild(secLabel);

                // Render blocks in this section
                _wfBlocks
                    .map((b, i) => ({...b, _idx: i}))
                    .filter(b => (b.section || 0) === flatIdx)
                    .sort((a, b) => (a.order_index || 0) - (b.order_index || 0))
                    .forEach(item => {
                        const block = _allBlocks.find(b => b.id === item.block_id);
                        const widgets = block?.widgets || [];
                        const widgetOpts = widgets.map(w =>
                            `<option value="${esc(w.name)}" ${item.widget_name === w.name ? 'selected' : ''}>${esc(w.name)}</option>`
                        ).join('');
                        const row = document.createElement('div');
                        row.className = 'wf-block-row';
                        row.draggable = true;
                        row.addEventListener('dragstart', e => onBlockDragStart(e, item._idx));
                        row.addEventListener('dragend', onBlockDragEnd);
                        row.innerHTML = `
                        <span class="wf-drag-handle" title="Перетащить">⠿</span>
                        <span class="wf-block-name">${esc(item.block_name)}</span>
                        ${widgets.length
                            ? `<select class="wf-widget-select" onchange="onWidgetChange(${item._idx}, this.value)">
                                   <option value="">—</option>${widgetOpts}</select>`
                            : `<input type="text" class="wf-widget-select" placeholder="виджет"
                                      value="${esc(item.widget_name)}" oninput="onWidgetChange(${item._idx}, this.value)">`}                        <button class="btn-remove-wf-block" onclick="removeWfBlock(${item._idx})" title="Убрать">✕</button>
                    `;
                        cell.appendChild(row);
                    });

                sectionsRow.appendChild(cell);
            }

            levelEl.appendChild(sectionsRow);
            zone.appendChild(levelEl);
        });

        // Wireframe text
        const wfText = document.createElement('div');
        wfText.className = 'wireframe-text';
        wfText.id = 'wfText';
        wfText.textContent = buildWireframeText();
        zone.appendChild(wfText);

        renderPagePreview();
    }

    // ── Level management ─────────────────────────────────────────────────────────
    function _redistributeWidths(cols) {
        const each = Math.floor(100 / cols);
        const ws = Array(cols).fill(each);
        ws[0] += 100 - ws.reduce((a, b) => a + b, 0);
        return ws;
    }

    function addLevel(afterIdx) {
        const insertAt = afterIdx !== undefined ? afterIdx + 1 : _gridLayout.length;
        const insertFlat = _gridLayout.slice(0, insertAt).reduce((a, lvl) => a + lvl.w.length, 0);
        _wfBlocks.forEach(b => {
            if (b.section >= insertFlat) b.section++;
        });
        _gridLayout.splice(insertAt, 0, {w: [100], h: 300});
        renderWireframeEditor();
    }

    function removeLevel(levelIdx) {
        if (_gridLayout.length <= 1) return;
        const flatStart = _firstFlatIdxOfLevel(levelIdx);
        const levelCols = _gridLayout[levelIdx].w.length;
        _wfBlocks.forEach(b => {
            if (b.section >= flatStart && b.section < flatStart + levelCols) b.section = 0;
            else if (b.section >= flatStart + levelCols) b.section -= levelCols;
        });
        _gridLayout.splice(levelIdx, 1);
        _wfRenumberSection();
        renderWireframeEditor();
    }

    function addSectionToLevel(levelIdx) {
        const level = _gridLayout[levelIdx];
        const afterFlat = _firstFlatIdxOfLevel(levelIdx) + level.w.length;
        _wfBlocks.forEach(b => {
            if (b.section >= afterFlat) b.section++;
        });
        level.w = _redistributeWidths(level.w.length + 1);
        renderWireframeEditor();
    }

    function removeSectionFromLevel(levelIdx) {
        const level = _gridLayout[levelIdx];
        if (level.w.length <= 1) return;
        const lastFlat = _firstFlatIdxOfLevel(levelIdx) + level.w.length - 1;
        const prevFlat = lastFlat - 1;
        _wfBlocks.forEach(b => {
            if (b.section === lastFlat) b.section = prevFlat;
            else if (b.section > lastFlat) b.section--;
        });
        level.w = _redistributeWidths(level.w.length - 1);
        _wfRenumberSection();
        renderWireframeEditor();
    }

    function setSectionWidth(levelIdx, colIdx, val) {
        _gridLayout[levelIdx].w[colIdx] = Math.max(5, Math.min(95, parseInt(val) || 10));
        const sectionsRow = document.querySelector(`.wf-level[data-level="${levelIdx}"] .wf-level-sections`);
        if (sectionsRow) sectionsRow.style.gridTemplateColumns = _gridLayout[levelIdx].w.map(w => w + '%').join(' ');
    }

    function setLevelHeight(levelIdx, val) {
        _gridLayout[levelIdx].h = Math.max(40, parseInt(val) || 100);
        const sectionsRow = document.querySelector(`.wf-level[data-level="${levelIdx}"] .wf-level-sections`);
        if (sectionsRow) sectionsRow.style.minHeight = _gridLayout[levelIdx].h + 'px';
    }

    function _wfRenumberSection() {
        const total = Math.max(_totalSections(), 9);
        for (let s = 0; s < total; s++) {
            let pos = 0;
            _wfBlocks.forEach(b => {
                if ((b.section || 0) === s) b.order_index = pos++;
            });
        }
    }

    function _updateWfText() {
        const el = document.getElementById('wfText');
        if (el) el.textContent = buildWireframeText();
    }

    function buildWireframeText() {
        if (!_wfBlocks.length) return '(пусто)';
        return [..._wfBlocks]
            .sort((a, b) => (a.section || 0) - (b.section || 0) || (a.order_index || 0) - (b.order_index || 0))
            .map(b => `${b.block_name} [${b.widget_name || '?'}]`)
            .join(' → ');
    }

    function onWidgetChange(idx, val) {
        if (_wfBlocks[idx]) {
            _wfBlocks[idx].widget_name = val;
            _updateWfText();
        }
    }

    function removeWfBlock(idx) {
        _wfBlocks.splice(idx, 1);
        _wfRenumberSection();
        renderWireframeEditor();
    }


    async function savePage() {
        if (!_selectedPageId) return;
        const btn = document.getElementById('btnSavePage');
        btn.disabled = true;
        btn.textContent = 'Сохранение…';

        const name = (document.getElementById('pageNameInput')?.value || '').trim();
        const page_type = document.getElementById('pageTypeSelect')?.value || 'feature';

        try {
            const res = await planningFetch(`/design/prototype/page/${_selectedPageId}`, {
                method: 'PUT',
                body: JSON.stringify({name, page_type}),
            });
            // Update local cache
            const page = _allPagesFull.find(p => p.id === _selectedPageId);
            if (page && res?.result) {
                page.name = res.result.name;
                page.page_type = res.result.page_type;
            }
            // Update tree item label
            const treeItem = document.querySelector(`.page-tree-item[data-page-id="${_selectedPageId}"]`);
            if (treeItem && name) {
                const nameSpan = treeItem.querySelector('.pname');
                if (nameSpan) nameSpan.textContent = name;
            }
            const status = document.getElementById('wfSaveStatus');
            status.style.display = '';
            setTimeout(() => status.style.display = 'none', 2000);
        } catch (e) {
            alert('Ошибка сохранения: ' + e.message);
        }

        btn.disabled = false;
        btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 16 16" fill="none">
            <path d="M2 2h9l3 3v9a1 1 0 01-1 1H2a1 1 0 01-1-1V3a1 1 0 011-1z" stroke="currentColor" stroke-width="1.5"/>
            <path d="M4 2v4h7V2M4 9h8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg> Сохранить страницу`;
    }

    async function saveWireframe() {
        if (!_selectedPageId) return;
        const btn = document.getElementById('btnSaveWireframe');
        btn.disabled = true;
        btn.textContent = 'Сохранение…';

        // Save page blocks + grid layout
        _wfRenumberSection();
        const blocksPayload = _wfBlocks.map(b => ({
            block_id: b.block_id,
            widget_name: b.widget_name || '',
            order_index: b.order_index || 0,
            section: b.section || 0,
        }));

        await planningFetch(`/design/page/${_selectedPageId}/blocks`, {
            method: 'PUT',
            body: JSON.stringify({blocks: blocksPayload, grid_layout: _gridLayout}),
        });

        // Update local cache
        const page = _allPagesFull.find(p => p.id === _selectedPageId);
        if (page) {
            page.grid_layout = _gridLayout;
            page.blocks = _wfBlocks.map(b => ({
                block_id: b.block_id,
                block_name: b.block_name,
                widget_name: b.widget_name,
                widget_id: b.widget_id,
                order_index: b.order_index || 0,
                section: b.section || 0,
            }));
        }

        // Update tree block count
        const treeItem = document.querySelector(`.page-tree-item[data-page-id="${_selectedPageId}"]`);
        if (treeItem) {
            let cnt = treeItem.querySelector('.block-cnt');
            if (_wfBlocks.length) {
                if (!cnt) {
                    treeItem.querySelector('span:first-child').insertAdjacentHTML('afterend', `<span class="block-cnt">${_wfBlocks.length}</span>`);
                } else {
                    cnt.textContent = _wfBlocks.length;
                }
            }
        }

        btn.disabled = false;
        btn.textContent = 'Сгенерировать Wireframe';
        const status = document.getElementById('wfSaveStatus');
        status.style.display = '';
        setTimeout(() => status.style.display = 'none', 2000);

        // Reload readiness
    }


    async function autoWireframe() {
        const pid = document.getElementById('globalProjectSel').value;
        if (!pid || !_selectedPageId) return;
        const btn = document.getElementById('btnAutoWireframe');
        btn.disabled = true;
        btn.innerHTML = `<svg class="spinning" width="13" height="13" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5" stroke-dasharray="12 26"/></svg> Генерация…`;

        try {
            const data = await planningFetch(`/design/prototype/page/${_selectedPageId}/auto-blocks`, {
                method: 'POST',
                body: JSON.stringify({project_id: parseInt(pid)}),
            });
            _wfBlocks = (data.result || []).map(b => ({
                block_id: b.block_id,
                block_name: b.block_name,
                widget_name: b.widget_name || '',
                widget_id: b.widget_id || null,
                section: b.section || 0,
                order_index: b.order_index || 0,
            }));
            renderWireframeEditor();
            renderPagePreview();
            const status = document.getElementById('wfSaveStatus');
            status.textContent = '✓ Автоблоки применены';
            status.style.display = '';
            setTimeout(() => {
                status.style.display = 'none';
            }, 3000);
        } catch (e) {
            alert('Ошибка автоблоков: ' + e.message);
        } finally {
            btn.disabled = false;
            btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 16 16" fill="none"><rect x="1" y="1" width="14" height="10" rx="1.5" stroke="currentColor" stroke-width="1.5"/><line x1="4" y1="14" x2="12" y2="14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><line x1="8" y1="11" x2="8" y2="14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg> Автоблоки`;
        }
    }


    // ═══════════════════════════════════════════════
    // PROTOTYPE — Design Tokens
    // ═══════════════════════════════════════════════

    let _protoSelectedTokenId = null;
    let _protoSelectedTokenName = null;

    function _updateProtoBtn() {
        const pid = document.getElementById('globalProjectSel')?.value;
        const btn = document.getElementById('btnCreateProto');
        const btnUi = document.getElementById('btnGenerateUiBlocks');
        if (btnUi) btnUi.disabled = !pid;
        const btnPages = document.getElementById('btnGeneratePages');
        if (btnPages) btnPages.disabled = !pid;
        if (!btn) return;
        if (btn.classList.contains('proto-btn-stop')) return; // running — don't reset
        btn.disabled = !(pid && _protoSelectedTokenId);
        if (!btn.innerHTML.includes('svg')) btn.innerHTML = `${_ICON_CREATE}Создать прototип`;
        const chip = document.getElementById('protoChipTokens');
        const chipText = document.getElementById('protoChipTokensText');
        if (chip && chipText) {
            if (_protoSelectedTokenName) {
                chipText.textContent = `Токены: ${_protoSelectedTokenName}`;
                chip.style.background = '#eff6ff';
                chip.style.borderColor = '#bfdbfe';
                chip.style.color = '#1d4ed8';
                chip.querySelectorAll('circle,rect').forEach(el => el.setAttribute('fill', '#3b82f6'));
            } else {
                chipText.textContent = 'Токены';
                chip.style.background = '#f1f5f9';
                chip.style.borderColor = '#e2e8f0';
                chip.style.color = '#94a3b8';
                chip.querySelectorAll('circle,rect').forEach(el => el.setAttribute('fill', '#94a3b8'));
            }
        }
        _updateStatesBadge();
    }

    let _allStates = [];

    function _getSelectedStateIds() {
        return _allStates
            .map(s => document.getElementById(`proto-state-${s.id}`))
            .filter(el => el && el.checked)
            .map(el => parseInt(el.value));
    }

    function _updateStatesBadge() {
        const chip = document.getElementById('protoChipStates');
        const chipText = document.getElementById('protoChipStatesText');
        if (!chip || !chipText) return;
        const selected = _allStates.filter(s => {
            const el = document.getElementById(`proto-state-${s.id}`);
            return el && el.checked;
        });
        if (selected.length) {
            chipText.textContent = `Стейты: ${selected.map(s => s.description || s.name).join(', ')}`;
            chip.style.background = '#f0fdf4';
            chip.style.borderColor = '#bbf7d0';
            chip.style.color = '#15803d';
            chip.querySelectorAll('rect').forEach(el => el.setAttribute('fill', '#22c55e'));
        } else {
            chipText.textContent = 'Стейты';
            chip.style.background = '#f1f5f9';
            chip.style.borderColor = '#e2e8f0';
            chip.style.color = '#94a3b8';
            chip.querySelectorAll('rect').forEach(el => el.setAttribute('fill', '#94a3b8'));
        }
    }

    let _pagesViewportWidth = 1440;
    let _pagesViewportHeight = 900;

    function pagesViewportChipToggle(e) {
        e.stopPropagation();
        const dd = document.getElementById('pagesViewportDropdown');
        if (!dd) return;
        const isOpen = dd.classList.contains('open');
        document.querySelectorAll('.proto-chip-dropdown.open').forEach(el => el.classList.remove('open'));
        if (!isOpen) dd.classList.add('open');
    }

    function pagesViewportSelect(e, width, height, label) {
        e.stopPropagation();
        _pagesViewportWidth = width;
        _pagesViewportHeight = height;
        const chipText = document.getElementById('pagesChipViewportText');
        if (chipText) chipText.textContent = `${width}×${height}`;
        const chip = document.getElementById('pagesChipViewport');
        if (chip) {
            chip.style.background = '#eff6ff';
            chip.style.borderColor = '#bfdbfe';
            chip.style.color = '#1d4ed8';
            chip.querySelectorAll('rect,line').forEach(el => {
                el.getAttribute('stroke') ? el.setAttribute('stroke', '#3b82f6') : el.setAttribute('fill', '#3b82f6');
            });
        }
        document.querySelectorAll('#pagesViewportDropdown .proto-chip-dropdown-item').forEach(el => {
            el.classList.toggle('active', parseInt(el.dataset.w) === width);
        });
        document.getElementById('pagesViewportDropdown')?.classList.remove('open');
    }

    let _protoViewportWidth = 1440;
    let _protoViewportHeight = 900;

    function protoViewportChipToggle(e) {
        e.stopPropagation();
        const dd = document.getElementById('protoViewportDropdown');
        if (!dd) return;
        const isOpen = dd.classList.contains('open');
        document.querySelectorAll('.proto-chip-dropdown.open').forEach(el => el.classList.remove('open'));
        if (!isOpen) dd.classList.add('open');
    }

    function protoViewportSelect(e, width, height, label) {
        e.stopPropagation();
        _protoViewportWidth = width;
        _protoViewportHeight = height;
        const chipText = document.getElementById('protoChipViewportText');
        if (chipText) chipText.textContent = `${width}×${height}`;
        const chip = document.getElementById('protoChipViewport');
        if (chip) {
            chip.style.background = '#eff6ff';
            chip.style.borderColor = '#bfdbfe';
            chip.style.color = '#1d4ed8';
            chip.querySelectorAll('rect,line').forEach(el => {
                el.getAttribute('stroke') ? el.setAttribute('stroke', '#3b82f6') : el.setAttribute('fill', '#3b82f6');
            });
        }
        document.querySelectorAll('#protoViewportDropdown .proto-chip-dropdown-item').forEach(el => {
            el.classList.toggle('active', parseInt(el.dataset.w) === width);
        });
        document.getElementById('protoViewportDropdown')?.classList.remove('open');
    }

    document.addEventListener('click', () => {
        document.querySelectorAll('.proto-chip-dropdown.open').forEach(el => el.classList.remove('open'));
    });

    async function loadDesignStates() {
        const container = document.getElementById('protoStatesList');
        if (!container) return;
        try {
            const data = await planningFetch('/design/states');
            _allStates = data.result || [];
            container.innerHTML = '';
            _allStates.forEach(st => {
                const label = document.createElement('label');
                label.className = 'proto-state-label';
                label.innerHTML = `<input type="checkbox" class="proto-state-cb" id="proto-state-${st.id}" value="${st.id}" checked>
                <span>${st.description || st.name}</span>`;
                label.querySelector('input').addEventListener('change', _updateStatesBadge);
                container.appendChild(label);
            });
            _updateStatesBadge();
        } catch (e) {
            if (container) container.innerHTML = '<span style="font-size:11px;color:#94a3b8">—</span>';
        }
    }

    async function loadDesignTokens() {
        const list = document.getElementById('protoTokensList');
        const palette = document.getElementById('protoTokensPalette');
        const counter = document.getElementById('protoTokensCount');
        if (!list) return;
        list.innerHTML = '<div style="padding:10px 12px;font-size:12px;color:#94a3b8">Загрузка...</div>';
        try {
            const data = await planningFetch('/design/tokens');
            const tokens = data.result || [];
            counter.textContent = tokens.length ? `(${tokens.length})` : '';
            list.innerHTML = '';
            if (!tokens.length) {
                list.innerHTML = '<div style="padding:10px 12px;font-size:12px;color:#94a3b8">Нет наборов</div>';
                palette.innerHTML = '<div style="font-size:12px;color:#94a3b8">Нет токенов</div>';
                return;
            }
            tokens.forEach(t => {
                const item = document.createElement('div');
                item.style.cssText = 'padding:7px 10px;cursor:pointer;font-size:12px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;gap:6px';
                item.dataset.tokenId = t.id;
                item.innerHTML = `<span style="flex:1;color:#334155;font-weight:500">${t.title || t.name}</span>
                <button onclick="event.stopPropagation();deleteDesignToken(${t.id})" style="background:none;border:none;cursor:pointer;color:#ef4444;font-size:11px;padding:0 2px" title="Удалить">✕</button>`;
                item.addEventListener('click', () => {
                    list.querySelectorAll('[data-token-id]').forEach(el => el.style.background = '');
                    item.style.background = '#eff6ff';
                    _protoSelectedTokenId = t.id;
                    _protoSelectedTokenName = t.title || t.name;
                    renderTokenPalette(t.tokens || {});
                    _updateProtoBtn();
                });
                if (_protoSelectedTokenId === t.id) {
                    item.style.background = '#eff6ff';
                    _protoSelectedTokenName = t.title || t.name;
                    renderTokenPalette(t.tokens || {});
                }
                list.appendChild(item);
            });
            if (_protoSelectedTokenId === null && tokens.length) {
                renderTokenPalette(tokens[0].tokens || {});
                _protoSelectedTokenId = tokens[0].id;
                _protoSelectedTokenName = tokens[0].title || tokens[0].name;
                list.querySelector('[data-token-id]').style.background = '#eff6ff';
            }
            _updateProtoBtn();
        } catch (e) {
            list.innerHTML = '<div style="padding:10px 12px;font-size:12px;color:#ef4444">Ошибка загрузки</div>';
        }
    }

    function renderTokenPalette(tokens) {
        const palette = document.getElementById('protoTokensPalette');
        if (!palette) return;

        function v(x) {
            return (x && typeof x === 'object' && x.value !== undefined) ? String(x.value) : String(x || '');
        }

        function lum(hex) {
            if (!hex || !hex.startsWith('#') || hex.length < 7) return 0.5;
            return (parseInt(hex.slice(1, 3), 16) * 0.299 + parseInt(hex.slice(3, 5), 16) * 0.587 + parseInt(hex.slice(5, 7), 16) * 0.114) / 255;
        }

        function on(hex) {
            return lum(hex) > 0.55 ? '#1e293b' : '#ffffff';
        }

        const c = tokens.colors || {};
        const P = v(c.primary) || '#3b82f6';
        const SEC = v(c.secondary) || '#64748b';
        const ACC = v(c.accent) || '';
        const BG = v(c.background) || '#ffffff';
        const SRF = v(c.surface) || '#f8fafc';
        const TXT = v(c.text) || '#1e293b';
        const MUT = v(c.textMuted || c.muted) || '#94a3b8';
        const BRD = v(c.border) || '#e2e8f0';
        const ERR = v(c.error) || '#ef4444';
        const WRN = v(c.warning) || '#f59e0b';
        const OK = v(c.success) || '#22c55e';
        const ff = tokens.typography?.fontFamily ? v(tokens.typography.fontFamily) : null;
        const ffs = ff ? `font-family:${ff};` : '';
        const BR = v(tokens.borderRadius) || '6px';
        const FS = v(tokens.typography?.fontSize) || '14px';
        const FSn = parseFloat(FS) || 14;
        const FSbody = `${Math.max(10, Math.round(FSn * 0.8))}px`;
        const FSsm = `${Math.max(9, Math.round(FSn * 0.7))}px`;

        if (ff) {
            const fname = ff.replace(/['"]/g, '').split(',')[0].trim();
            const webSafe = ['arial', 'helvetica', 'georgia', 'times new roman', 'courier', 'verdana', 'trebuchet ms', 'tahoma'];
            if (!webSafe.includes(fname.toLowerCase())) {
                const gfId = `gf-${fname.replace(/\s+/g, '-').toLowerCase()}`;
                if (!document.getElementById(gfId)) {
                    const lnk = document.createElement('link');
                    lnk.id = gfId;
                    lnk.rel = 'stylesheet';
                    lnk.href = `https://fonts.googleapis.com/css2?family=${fname.replace(/\s+/g, '+')}:wght@400;600;700&display=swap`;
                    document.head.appendChild(lnk);
                }
            }
        }

        // compact color strip
        const chips = Object.entries(c).map(([k, val]) => {
            const hex = v(val);
            return `<div title="${k}: ${hex}" style="display:flex;flex-direction:column;align-items:center;gap:2px;flex-shrink:0">
            <div style="width:24px;height:24px;border-radius:5px;background:${hex};border:1px solid rgba(0,0,0,.08)"></div>
            <span style="font-size:8px;color:#94a3b8;max-width:30px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:center">${k}</span>
        </div>`;
        }).join('');

        const btnBase = `border:none;border-radius:${BR};font-size:12px;cursor:default;padding:5px 12px;${ffs}`;
        const accentBtn = ACC ? `<button style="${btnBase}background:${ACC};color:${on(ACC)}">Accent</button>` : '';

        palette.innerHTML = `<div style="${ffs}color:${TXT};display:flex;flex-direction:column;gap:12px;font-size:${FS};background:${BG};padding:10px;border-radius:${BR};margin:-4px">

        <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:flex-start">${chips}</div>

        <div style="border-top:1px solid ${BRD}"></div>

        <div>
            <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;margin-bottom:6px">Кнопки</div>
            <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">
                <button style="${btnBase}background:${P};color:${on(P)}">Primary</button>
                <button style="${btnBase}background:${SEC};color:${on(SEC)}">Secondary</button>
                ${accentBtn}
                <button style="${btnBase}background:transparent;color:${P};border:1.5px solid ${P}">Outline</button>
                <button style="${btnBase}background:transparent;color:${MUT};border:1px solid ${BRD}">Ghost</button>
            </div>
        </div>

        <div>
            <div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;margin-bottom:6px">Карточка</div>
            <div style="background:${SRF};border:1px solid ${BRD};border-radius:${BR};padding:10px 12px;max-width:360px">
                <div style="font-size:${FS};font-weight:600;color:${TXT};margin-bottom:3px">Заголовок блока</div>
                <div style="font-size:${FSbody};color:${MUT};line-height:1.5;margin-bottom:8px">Основной текст. <span style="color:${MUT}">Вспомогательный контент.</span></div>
                <div style="border-top:1px solid ${BRD};margin-bottom:8px"></div>
                <div style="display:flex;gap:6px">
                    <button style="${btnBase}background:${P};color:${on(P)};font-size:${FSbody};padding:4px 10px">Действие</button>
                    <button style="${btnBase}background:transparent;color:${MUT};border:1px solid ${BRD};font-size:${FSbody};padding:4px 10px">Отмена</button>
                </div>
            </div>
        </div>

        <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">
            <span style="padding:2px 9px;background:${OK}22;color:${OK};border:1px solid ${OK}55;border-radius:20px;font-size:${FSsm};font-weight:600">● Успех</span>
            <span style="padding:2px 9px;background:${WRN}22;color:${WRN};border:1px solid ${WRN}55;border-radius:20px;font-size:${FSsm};font-weight:600">● Предупреждение</span>
            <span style="padding:2px 9px;background:${ERR}22;color:${ERR};border:1px solid ${ERR}55;border-radius:20px;font-size:${FSsm};font-weight:600">● Ошибка</span>
        </div>

        ${ff ? `<div style="border-top:1px solid ${BRD};padding-top:8px;font-size:${FSsm};color:${MUT}">
            Шрифт: <span style="font-family:${ff};font-size:${FS};font-weight:600;color:${TXT}">${ff.replace(/'/g, '').split(',')[0]}</span>
            <span style="font-family:${ff};font-size:${FS};color:${MUT}"> — Regular, </span>
            <span style="font-family:${ff};font-size:${FS};font-weight:700;color:${TXT}">Bold</span>
        </div>` : ''}
    </div>`;
    }

    async function generateDesignTokens() {
        const pid = document.getElementById('globalProjectSel').value;
        const nameInput = document.getElementById('protoTokenName');
        const btn = document.getElementById('btnGenerateTokens');
        const name = (nameInput?.value || '').trim() || `tokens-${Date.now()}`;

        const description = pid ? (document.getElementById('globalProjectSel')?.selectedOptions[0]?.textContent?.trim() || '') : '';

        btn.disabled = true;
        btn.textContent = 'Генерирую...';
        try {
            const data = await planningFetch('/design/tokens/generate', {
                method: 'POST',
                body: JSON.stringify({name, title: name, description}),
            });
            _protoSelectedTokenId = null;
            _protoSelectedTokenName = null;
            if (nameInput) nameInput.value = '';
            await loadDesignTokens();
        } catch (e) {
            alert('Ошибка генерации: ' + (e.message || e));
        } finally {
            btn.disabled = false;
            btn.textContent = 'Сгенерировать';
        }
    }

    async function deleteDesignToken(tokenId) {
        if (_protoSelectedTokenId === tokenId) {
            _protoSelectedTokenId = null;
            _protoSelectedTokenName = null;
        }
        await planningFetch(`/design/tokens/${tokenId}`, {method: 'DELETE'});
        await loadDesignTokens();
    }

    let _protoPollingTimer = null;

    function _protoSetStatus(text, color, pulse) {
        const el = document.getElementById('protoProtoStatus');
        if (!el) return;
        el.style.display = text ? '' : 'none';
        el.innerHTML = text ? `<span class="${pulse ? 'proto-pulse' : ''}" style="color:${color}">● ${text}</span>` : '';
    }

    const _ICON_CREATE = `<svg width="13" height="13" viewBox="0 0 16 16" fill="none" style="vertical-align:-1px;margin-right:5px"><path d="M3 2.5L13 8L3 13.5V2.5Z" fill="currentColor"/></svg>`;
    const _ICON_STOP = `<svg width="11" height="11" viewBox="0 0 16 16" fill="none" style="vertical-align:-1px;margin-right:5px"><rect x="3" y="3" width="10" height="10" rx="2" fill="currentColor"/></svg>`;

    function _protoSetBtn(mode) {
        const btn = document.getElementById('btnCreateProto');
        if (!btn) return;
        if (mode === 'run') {
            btn.className = 'proto-btn-stop';
            btn.innerHTML = `${_ICON_STOP}Стоп`;
            btn.onclick = stopPrototype;
            btn.disabled = false;
        } else if (mode === 'loading') {
            btn.className = 'btn-primary';
            btn.innerHTML = 'Запускаю...';
            btn.onclick = null;
            btn.disabled = true;
        } else {
            btn.className = 'btn-primary';
            btn.innerHTML = `${_ICON_CREATE}Создать прototип`;
            btn.onclick = createPrototype;
            btn.disabled = !(document.getElementById('globalProjectSel')?.value && _protoSelectedTokenId);
        }
    }

    async function _protoPollStatus(pid) {
        try {
            const data = await planningFetch(`/planning/project/${pid}/phases`);
            const phases = data.result || [];
            const ph = phases.find(p => p.phase === 'prototype');
            if (!ph) return;
            const s = ph.status;
            if (s === 'running' || s === 'pending') {
                _protoSetStatus('Processing', '#f59e0b', true);
            } else if (s === 'complete' || s === 'done') {
                _protoSetStatus('Done', '#22c55e', false);
                if (_protoPollingTimer) {
                    clearInterval(_protoPollingTimer);
                    _protoPollingTimer = null;
                }
                _protoSetBtn('idle');
            } else if (s === 'error') {
                const msg = ph.error ? `: ${ph.error.slice(0, 60)}` : '';
                _protoSetStatus(`Error${msg}`, '#ef4444', false);
                if (_protoPollingTimer) {
                    clearInterval(_protoPollingTimer);
                    _protoPollingTimer = null;
                }
                _protoSetBtn('idle');
            }
        } catch (e) { /* ignore poll errors */
        }
    }

    function stopPrototype() {
        if (_protoPollingTimer) {
            clearInterval(_protoPollingTimer);
            _protoPollingTimer = null;
        }
        _protoSetStatus('', '', false);
        _protoSetBtn('idle');
    }

    async function createPrototype() {
        const pid = document.getElementById('globalProjectSel').value;
        if (!pid) {
            alert('Выберите проект');
            return;
        }
        if (!_protoSelectedTokenId) {
            alert('Выберите набор токенов');
            return;
        }

        if (_protoPollingTimer) {
            clearInterval(_protoPollingTimer);
            _protoPollingTimer = null;
        }
        _protoSetBtn('loading');
        _protoSetStatus('Запускаю...', '#94a3b8', true);

        try {
            const data = await planningFetch(`/planning/project/${pid}/phase/prototype/approve`, {
                method: 'POST',
                body: JSON.stringify({
                    token_id: _protoSelectedTokenId,
                    state_ids: _getSelectedStateIds(),
                }),
            });
            if (data.error) {
                _protoSetStatus(`Error: ${data.error}`, '#ef4444', false);
                _protoSetBtn('idle');
                return;
            }
            _protoSetStatus('Processing', '#f59e0b', true);
            _protoSetBtn('run');
            _protoPollingTimer = setInterval(() => _protoPollStatus(pid), 4000);
        } catch (e) {
            _protoSetStatus(`Error: ${e.message || 'неизвестная ошибка'}`, '#ef4444', false);
            _protoSetBtn('idle');
        }
    }

    // Split-pane drag handlers with localStorage persistence
    (function () {
        function _initProtoDivider(dividerId, leftColId, storageKey, minLeft, minRight) {
            document.addEventListener('DOMContentLoaded', function () {
                const divider = document.getElementById(dividerId);
                const col = document.getElementById(leftColId);
                if (!divider || !col) return;

                // Restore saved position
                const saved = parseInt(localStorage.getItem(storageKey), 10);
                if (saved > minLeft) col.style.width = saved + 'px';

                let dragging = false, startX = 0, startW = 0;

                divider.addEventListener('mousedown', function (e) {
                    dragging = true;
                    startX = e.clientX;
                    startW = divider.previousElementSibling
                        ? divider.previousElementSibling.offsetWidth
                        : parseInt(col.style.width || col.offsetWidth, 10);
                    document.body.style.cursor = 'col-resize';
                    document.body.style.userSelect = 'none';
                    divider.classList.add('dragging');
                    e.preventDefault();
                });

                document.addEventListener('mousemove', function (e) {
                    if (!dragging) return;
                    const container = document.getElementById('protoConfigRow');
                    const maxW = container.offsetWidth - minRight - divider.offsetWidth;
                    const newW = Math.max(minLeft, Math.min(maxW, startW + e.clientX - startX));
                    col.style.width = newW + 'px';
                });

                document.addEventListener('mouseup', function () {
                    if (!dragging) return;
                    dragging = false;
                    document.body.style.cursor = '';
                    document.body.style.userSelect = '';
                    divider.classList.remove('dragging');
                    localStorage.setItem(storageKey, parseInt(col.style.width, 10));
                });
            });
        }

        _initProtoDivider('protoSplitDivider', 'protoColLeft', 'proto_col1_w', 180, 400);
        _initProtoDivider('protoSplitDivider2', 'protoColState', 'proto_col3_w', 100, 300);
        _initProtoDivider('protoSplitDivider3', 'protoColFunctionality', 'proto_col5_w', 100, 200);
    })();

    // ═══════════════════════════════════════════════
    // PROTOTYPE — Project Chips (cloud_tags / entities)
    // ═══════════════════════════════════════════════

    let _protoChipsCloudTags = [];
    let _protoChipsEntities = [];
    let _protoChipsSaveTimer = null;

    async function loadProjectChips() {
        const pid = document.getElementById('globalProjectSel')?.value;
        _renderChips('protoFunctionalityScroll', [], 'cloud_tags');
        _renderChips('protoEntitiesScroll', [], 'entities');
        if (!pid) return;
        try {
            const data = await planningFetch(`/design/project/${pid}/chips`);
            _protoChipsCloudTags = data.cloud_tags || [];
            _protoChipsEntities = data.entities || [];
            _renderChips('protoFunctionalityScroll', _protoChipsCloudTags, 'cloud_tags');
            _renderChips('protoEntitiesScroll', _protoChipsEntities, 'entities');
        } catch (e) {
            console.error('loadProjectChips', e);
        }
    }

    function _renderChips(scrollId, chips, field) {
        const scroll = document.getElementById(scrollId);
        if (!scroll) return;
        scroll.innerHTML = '';

        const wrap = document.createElement('div');
        wrap.className = 'proto-chips-wrap';

        if (!chips.length) {
            const empty = document.createElement('div');
            empty.className = 'proto-chips-empty';
            empty.textContent = 'Нет чипсов';
            wrap.appendChild(empty);
        } else {
            chips.forEach((chip, i) => {
                const tag = document.createElement('div');
                tag.className = 'proto-chip-tag';
                const label = document.createElement('span');
                label.textContent = chip;
                const delBtn = document.createElement('button');
                delBtn.textContent = '×';
                delBtn.title = 'Удалить';
                delBtn.onclick = () => _removeChip(field, i);
                tag.appendChild(label);
                tag.appendChild(delBtn);
                wrap.appendChild(tag);
            });
        }

        scroll.appendChild(wrap);
    }

    function _addChip(field) {
        const input = document.getElementById(`proto-chip-input-${field}`);
        if (!input) return;
        const val = input.value.trim();
        if (!val) return;
        if (field === 'cloud_tags') {
            if (!_protoChipsCloudTags.includes(val)) _protoChipsCloudTags.push(val);
            _renderChips('protoFunctionalityScroll', _protoChipsCloudTags, 'cloud_tags');
        } else {
            if (!_protoChipsEntities.includes(val)) _protoChipsEntities.push(val);
            _renderChips('protoEntitiesScroll', _protoChipsEntities, 'entities');
        }
        _saveChipsDebounced(field);
    }

    function _removeChip(field, index) {
        if (field === 'cloud_tags') {
            _protoChipsCloudTags.splice(index, 1);
            _renderChips('protoFunctionalityScroll', _protoChipsCloudTags, 'cloud_tags');
        } else {
            _protoChipsEntities.splice(index, 1);
            _renderChips('protoEntitiesScroll', _protoChipsEntities, 'entities');
        }
        _saveChipsDebounced(field);
    }


    function _saveChipsDebounced(field) {
        if (_protoChipsSaveTimer) clearTimeout(_protoChipsSaveTimer);
        _protoChipsSaveTimer = setTimeout(() => _saveChips(field), 600);
    }

    async function _saveChips(field) {
        const pid = document.getElementById('globalProjectSel')?.value;
        if (!pid) return;
        const body = field === 'cloud_tags'
            ? {cloud_tags: _protoChipsCloudTags}
            : {entities: _protoChipsEntities};
        try {
            await planningFetch(`/design/project/${pid}/chips`, {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            });
        } catch (e) {
            console.error('saveChips', e);
        }
    }

    const _ICON_UI_BLOCKS = `<svg width="13" height="13" viewBox="0 0 16 16" fill="none"><rect x="1" y="1" width="6" height="6" rx="1.5" fill="currentColor" opacity=".7"/><rect x="9" y="1" width="6" height="6" rx="1.5" fill="currentColor"/><rect x="1" y="9" width="6" height="6" rx="1.5" fill="currentColor"/><rect x="9" y="9" width="6" height="6" rx="1.5" fill="currentColor" opacity=".7"/></svg>`;
    const _ICON_PAGES = `<svg width="13" height="13" viewBox="0 0 16 16" fill="none"><rect x="2" y="1" width="12" height="14" rx="1.5" stroke="currentColor" stroke-width="1.5" fill="none"/><line x1="5" y1="5" x2="11" y2="5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><line x1="5" y1="8" x2="11" y2="8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><line x1="5" y1="11" x2="9" y2="11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`;

    async function generateUiBlocks() {
        const pid = document.getElementById('globalProjectSel')?.value;
        if (!pid) return;
        const btn = document.getElementById('btnGenerateUiBlocks');
        btn.disabled = true;
        btn.innerHTML = 'Генерация...';
        try {
            await planningFetch(`/design/project/${pid}/generate-ui-blocks`, {method: 'POST'});
        } finally {
            btn.disabled = false;
            btn.innerHTML = `${_ICON_UI_BLOCKS} Сгенерировать UI-блоки`;
        }
    }

    async function generatePages() {
        const pid = document.getElementById('globalProjectSel')?.value;
        if (!pid) return;
        const btn = document.getElementById('btnGeneratePages');
        btn.disabled = true;
        btn.innerHTML = 'Генерация...';
        try {
            await planningFetch(`/design/project/${pid}/generate-pages`, {method: 'POST'});
        } finally {
            btn.disabled = false;
            btn.innerHTML = `${_ICON_PAGES} Сгенерировать страницы`;
        }
    }

    _bwLoadTokens();
    initProjectSelects();
