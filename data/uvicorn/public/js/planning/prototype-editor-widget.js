/* prototype-editor-widget.js — виджет редактора прототипа с вкладками.
 * window.__PROTO_WIDGET__ = { projectId, pageName } задаётся инлайн-скриптом перед загрузкой.
 */
(function () {
    'use strict';

    var cfg = window.__PROTO_WIDGET__ || {};
    var projectId = cfg.projectId;
    var pageName  = cfg.pageName || 'index.html';
    if (!projectId) return;
    /* Не инициализируем виджет внутри iframe split-screen */
    if (location.search.indexOf('__rw_embed=1') !== -1) return;
    /* Защита от двойной инициализации */
    if (window.__PROTO_WIDGET_ACTIVE__) return;
    window.__PROTO_WIDGET_ACTIVE__ = true;
    /* Удаляем виджет-элементы и стили, которые могли запечься в HTML при предыдущем сохранении */
    var _WIDGET_IDS = [
        '__rw_tabbar', '__rw_breadbar', '__rw_overlay_container',
        '__rw_edit_overlay', '__rw_edit_hl', '__rw_edit_actions',
        '__rw_edit_drop_line', '__rw_text_bar', '__rw_ai_panel',
        '__rw_split', '__rw_apply_status', '__rw_style',
    ];
    _WIDGET_IDS.forEach(function(id) {
        var el = document.getElementById(id);
        if (el && el.parentNode) el.parentNode.removeChild(el);
    });
    /* Убираем старые style-теги виджета без id (например body{margin-top:66px!important}) */
    var _allStyles = document.querySelectorAll('style:not(#__rw_style)');
    _allStyles.forEach(function(s) {
        if (s.textContent.indexOf('#__rw_tabbar') !== -1) {
            if (s.parentNode) s.parentNode.removeChild(s);
        }
    });

    /* ── CSS ─────────────────────────────────────────────────────────────────── */
    var css = [
        /* Таб-панель — static, первым в body; смещает контент сама, не перекрывает */
        '#__rw_tabbar{position:sticky;top:0;left:0;right:0;z-index:2147483647;',
        'display:flex;align-items:center;gap:0;height:36px;',
        'background:#0a0f1a;border-bottom:2px solid #1e293b;',
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px;}',
        /* Логотип */
        '#__rw_logo{display:flex;align-items:center;gap:8px;padding:0 14px;height:100%;',
        'text-decoration:none;border-right:1px solid #1e293b;flex-shrink:0;',
        'background:#111827;transition:background .15s;}',
        '#__rw_logo:hover{background:#1e293b;}',
        '#__rw_logo img{width:22px;height:22px;border-radius:5px;display:block;}',
        '#__rw_logo span{font-size:12px;font-weight:700;color:#e2e8f0;letter-spacing:0.5px;',
        'text-transform:uppercase;white-space:nowrap;}',
        '#__rw_tabbar .rw-tab{padding:0 18px;height:100%;display:flex;align-items:center;',
        'color:#64748b;cursor:pointer;border-right:1px solid #1e293b;',
        'white-space:nowrap;user-select:none;transition:color .15s,background .15s;',
        'flex-shrink:0;position:relative;z-index:1;pointer-events:auto;}',
        '#__rw_tabbar .rw-tab:hover{color:#94a3b8;background:#0f172a;}',
        '#__rw_tabbar .rw-tab.active{color:#e2e8f0;background:#0f172a;border-bottom:2px solid #3b82f6;}',
        /* Хлебные крошки навигации — inline внутри tabbar, справа от табов */
        '#__rw_breadbar{display:flex;align-items:center;flex:1;padding:0 12px;min-width:0;',
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:12px;',
        'color:#64748b;overflow:hidden;white-space:nowrap;border-left:1px solid #1e293b;',
        'pointer-events:none;}',
        '#__rw_breadbar .rw-bc{color:#e2e8f0;font-weight:600;}',
        '#__rw_breadbar .rw-bc.rw-bc-link{color:#93c5fd;cursor:pointer;font-weight:400;',
        'text-decoration:underline;pointer-events:auto;}',
        '#__rw_breadbar .rw-bc.rw-bc-link:hover{color:#bfdbfe;}',
        '#__rw_breadbar .rw-bc-sep{color:#334155;margin:0 5px;}',
        /* ── Прото-вкладка: нет оверлея, нормальный скролл страницы */

        /* ── Редактирование-вкладка: фикс. оверлей над страницей (не iframe) */
        '#__rw_edit_overlay{position:fixed;top:0;left:0;right:0;bottom:0;',
        'z-index:2147483640;display:none;cursor:crosshair;}',
        '#__rw_edit_overlay.on{display:block;}',
        /* Подсветка блока */
        '#__rw_edit_hl{position:fixed;pointer-events:none;border:2px solid #f59e0b;',
        'background:rgba(245,158,11,0.08);border-radius:3px;z-index:2147483641;display:none;}',
        '#__rw_edit_hl.hover{border:2px dashed #3b82f6;background:rgba(59,130,246,0.07);}',
        /* Быстрые действия над блоком */
        '#__rw_edit_actions{position:fixed;display:none;gap:3px;z-index:2147483642;',
        'padding:3px;background:#0f172a;border-radius:6px;border:1px solid #334155;',
        'box-shadow:0 2px 8px rgba(0,0,0,.5);}',
        '#__rw_edit_actions.on{display:flex;}',
        '#__rw_edit_actions button{width:28px;height:28px;border-radius:4px;border:none;',
        'background:transparent;color:#94a3b8;cursor:pointer;font-size:13px;',
        'display:flex;align-items:center;justify-content:center;padding:0;transition:background .1s;}',
        '#__rw_edit_actions button:hover{background:#1e293b;color:#e2e8f0;}',
        '#__rw_edit_actions button.danger:hover{background:#7f1d1d;color:#fca5a5;}',
        '#__rw_edit_actions button.ai-btn{color:#60a5fa;}',
        '#__rw_edit_actions button.ai-btn:hover{background:#1e3a5f;color:#93c5fd;}',
        '#__rw_edit_actions button.text-btn{color:#4ade80;}',
        '#__rw_edit_actions button.text-btn:hover{background:#14532d;color:#86efac;}',
        '#__rw_edit_actions button.move-btn{cursor:grab;}',
        '#__rw_edit_actions button.move-btn:active{cursor:grabbing;}',
        /* Бар текстового редактирования (поверх страницы, под хлебными крошками) */
        '#__rw_text_bar{position:fixed;top:66px;left:50%;transform:translateX(-50%);',
        'z-index:2147483648;display:none;gap:8px;align-items:center;',
        'background:#0a0f1a;border:1px solid #22c55e;border-radius:8px;padding:6px 14px;',
        'box-shadow:0 4px 16px rgba(0,0,0,.5);',
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px;color:#e2e8f0;}',
        '#__rw_text_bar.on{display:flex;}',
        '#__rw_text_bar_hint{color:#86efac;font-size:12px;}',
        '#__rw_text_bar_done{padding:4px 14px;border-radius:5px;border:none;background:#16a34a;',
        'color:#fff;cursor:pointer;font-size:12px;font-weight:600;}',
        '#__rw_text_bar_done:hover{background:#15803d;}',
        '#__rw_text_bar_cancel{padding:4px 10px;border-radius:5px;border:1px solid #334155;',
        'background:transparent;color:#94a3b8;cursor:pointer;font-size:12px;}',
        '#__rw_text_bar_cancel:hover{background:#1e293b;}',
        /* Линия-вставки при drag */
        '#__rw_edit_drop_line{position:fixed;height:3px;background:#3b82f6;border-radius:2px;',
        'display:none;pointer-events:none;z-index:2147483643;box-shadow:0 0 6px #3b82f6;}',

        /* AI-панель (всплывающая, над блоком) */
        '#__rw_ai_panel{position:fixed;width:340px;z-index:2147483645;display:none;',
        'background:#fff;border-radius:10px;box-shadow:0 8px 32px rgba(0,0,0,.2);',
        'flex-direction:column;overflow:hidden;',
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px;color:#111827;}',
        '#__rw_ai_panel.on{display:flex;}',
        '#__rw_ai_head{display:flex;align-items:center;gap:8px;padding:10px 12px 8px;',
        'border-bottom:1px solid #e5e7eb;background:#f9fafb;}',
        '#__rw_ai_head_title{font-weight:700;font-size:13px;color:#111827;flex:1;}',
        '#__rw_ai_close{background:none;border:none;cursor:pointer;color:#9ca3af;font-size:17px;line-height:1;padding:0 2px;}',
        '#__rw_ai_close:hover{color:#374151;}',
        '#__rw_ai_body{padding:10px 12px 12px;display:flex;flex-direction:column;gap:8px;}',
        '#__rw_ai_ta{width:100%;box-sizing:border-box;height:80px;border:1px solid #d1d5db;border-radius:7px;',
        'padding:8px 10px;font-size:13px;font-family:inherit;resize:vertical;outline:none;',
        'color:#111827;background:#fff;transition:border-color .15s;}',
        '#__rw_ai_ta:focus{border-color:#2563eb;}',
        '#__rw_ai_ta::placeholder{color:#9ca3af;}',
        '#__rw_ai_row{display:flex;gap:7px;}',
        '#__rw_ai_mic{flex:0 0 auto;padding:7px 12px;border-radius:6px;border:1px solid #d1d5db;',
        'background:#f9fafb;color:#374151;cursor:pointer;font-size:13px;',
        'display:flex;align-items:center;gap:5px;transition:all .15s;white-space:nowrap;}',
        '#__rw_ai_mic:hover{background:#f3f4f6;border-color:#9ca3af;}',
        '#__rw_ai_mic.recording{background:#fee2e2;border-color:#ef4444;color:#dc2626;}',
        '#__rw_ai_mic.processing{background:#fef3c7;border-color:#f59e0b;color:#92400e;}',
        '#__rw_ai_submit{flex:1;padding:7px 14px;border-radius:6px;border:none;',
        'background:#2563eb;color:#fff;cursor:pointer;font-size:13px;font-weight:600;transition:background .15s;}',
        '#__rw_ai_submit:hover:not(:disabled){background:#1d4ed8;}',
        '#__rw_ai_submit:disabled{background:#93c5fd;cursor:not-allowed;}',
        '#__rw_ai_status{font-size:11px;text-align:center;min-height:14px;color:#6b7280;}',
        '#__rw_ai_status.ok{color:#16a34a;}',
        '#__rw_ai_status.err{color:#dc2626;}',
        '@keyframes __rw_pulse{0%,100%{opacity:1}50%{opacity:.4}}',
        '#__rw_ai_mic.recording #__rw_ai_mic_icon{animation:__rw_pulse 1s infinite;}',

        /* ── Браузер-вкладка (split-screen) */
        '#__rw_split{position:fixed;top:0;left:0;width:100%;bottom:0;z-index:2147483640;',
        'display:none;background:#1e293b;flex-direction:column;}',
        '#__rw_split.on{display:flex;}',

        '#__rw_split_content{display:flex;flex:1;overflow:hidden;}',

        /* Левая сторона — прототип */
        '#__rw_proto_side{flex:1;display:flex;flex-direction:column;border-right:2px solid #1e293b;position:relative;}',
        '#__rw_proto_bar{display:flex;align-items:center;gap:8px;padding:7px 12px;',
        'background:#0f172a;color:#94a3b8;font-size:12px;font-family:inherit;flex-shrink:0;}',
        '#__rw_proto_breadcrumbs{font-size:12px;flex:1;overflow:hidden;white-space:nowrap;',
        'text-overflow:ellipsis;display:flex;align-items:center;gap:2px;min-width:0;}',
        '#__rw_proto_breadcrumbs .rw-crumb{color:#e2e8f0;font-weight:600;}',
        '#__rw_proto_breadcrumbs .rw-crumb.rw-link{color:#93c5fd;cursor:pointer;text-decoration:underline;font-weight:400;}',
        '#__rw_proto_breadcrumbs .rw-crumb.rw-link:hover{color:#bfdbfe;}',
        '#__rw_proto_breadcrumbs .rw-sep{color:#475569;flex-shrink:0;margin:0 2px;}',
        '#__rw_proto_add_btn{padding:4px 10px;border-radius:5px;border:1px solid #334155;',
        'background:transparent;color:#94a3b8;cursor:pointer;font-size:11px;font-family:inherit;white-space:nowrap;}',
        '#__rw_proto_add_btn:hover{background:#1e293b;}',
        '#__rw_proto_add_btn.active{background:#14532d;border-color:#22c55e;color:#86efac;}',
        '#__rw_proto_frame{flex:1;border:none;background:#fff;}',
        '#__rw_proto_overlay{position:absolute;left:0;right:0;bottom:0;',
        'display:none;cursor:crosshair;z-index:10;}',
        '#__rw_proto_overlay.active{display:block;}',
        '#__rw_proto_highlight{position:absolute;pointer-events:none;border:2px solid #f59e0b;',
        'background:rgba(245,158,11,0.08);border-radius:3px;display:none;z-index:11;transition:none;}',
        '#__rw_proto_highlight.hover{border:2px dashed #3b82f6;background:rgba(59,130,246,0.07);}',
        '#__rw_proto_actions{position:absolute;display:none;gap:3px;z-index:14;',
        'padding:3px;background:#0f172a;border-radius:6px;border:1px solid #334155;',
        'box-shadow:0 2px 8px rgba(0,0,0,.5);}',
        '#__rw_proto_actions.on{display:flex;}',
        '#__rw_proto_actions button{width:26px;height:26px;border-radius:4px;border:none;',
        'background:transparent;color:#94a3b8;cursor:pointer;font-size:14px;',
        'display:flex;align-items:center;justify-content:center;padding:0;transition:background .1s;}',
        '#__rw_proto_actions button:hover{background:#1e293b;color:#e2e8f0;}',
        '#__rw_proto_actions button.danger:hover{background:#7f1d1d;color:#fca5a5;}',
        '#__rw_proto_actions button.move-btn{cursor:grab;}',
        '#__rw_proto_actions button.move-btn:active{cursor:grabbing;}',
        '#__rw_proto_drop_line{position:absolute;left:4px;right:4px;height:3px;',
        'background:#3b82f6;border-radius:2px;display:none;pointer-events:none;z-index:15;',
        'box-shadow:0 0 6px #3b82f6;}',

        /* Правая сторона — браузер */
        '#__rw_browser_side{flex:1;display:flex;flex-direction:column;}',
        '#__rw_browser_bar{display:flex;align-items:center;gap:6px;padding:7px 12px;',
        'background:#0f172a;flex-shrink:0;}',
        '#__rw_url_wrap{flex:1;position:relative;}',
        '#__rw_browser_url{width:100%;box-sizing:border-box;padding:5px 10px;border-radius:6px;border:1px solid #334155;',
        'background:#1e293b;color:#e2e8f0;font-size:13px;font-family:inherit;outline:none;}',
        '#__rw_browser_url:focus{border-color:#3b82f6;}',
        '#__rw_url_history{position:absolute;top:calc(100% + 4px);left:0;right:0;',
        'background:#1e293b;border:1px solid #334155;border-radius:7px;',
        'box-shadow:0 6px 20px rgba(0,0,0,.5);z-index:200;overflow:hidden;display:none;}',
        '#__rw_url_history.on{display:block;}',
        '#__rw_url_history div{padding:7px 12px;font-size:12px;color:#94a3b8;',
        'cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:inherit;}',
        '#__rw_url_history div:hover{background:#334155;color:#e2e8f0;}',
        '#__rw_browser_go{padding:5px 12px;border-radius:6px;border:none;background:#2563eb;',
        'color:#fff;cursor:pointer;font-size:13px;font-weight:600;white-space:nowrap;}',
        '#__rw_browser_go:hover{background:#1d4ed8;}',
        '#__rw_browser_back{padding:5px 10px;border-radius:6px;border:1px solid #334155;',
        'background:#1e293b;color:#94a3b8;cursor:pointer;font-size:14px;}',
        '#__rw_browser_back:hover{background:#334155;}',
        '#__rw_browser_title{color:#64748b;font-size:11px;max-width:120px;',
        'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:inherit;}',
        '#__rw_browser_view{flex:1;position:relative;overflow:hidden;background:#f8fafc;cursor:crosshair;}',
        '#__rw_browser_img{display:block;width:100%;height:100%;object-fit:contain;object-position:top left;user-select:none;}',
        '#__rw_browser_canvas{position:absolute;top:0;left:0;width:100%;height:100%;cursor:crosshair;}',
        '#__rw_browser_loader{position:absolute;inset:0;display:none;align-items:center;justify-content:center;',
        'background:rgba(15,23,42,.75);color:#e2e8f0;font-size:14px;font-family:inherit;}',
        '#__rw_browser_loader.on{display:flex;}',
        '#__rw_hscroll{height:10px;background:#1e293b;flex-shrink:0;position:relative;display:none;}',
        '#__rw_hscroll.on{display:block;}',
        '#__rw_hscroll_thumb{position:absolute;top:2px;height:6px;border-radius:3px;',
        'background:#475569;cursor:pointer;transition:background .15s;}',
        '#__rw_hscroll_thumb:hover{background:#64748b;}',

        /* Нижние панели браузерной вкладки */
        '#__rw_pick_bar{padding:8px 12px;background:#0a0f1a;border-top:2px solid #1e293b;',
        'display:flex;gap:8px;flex-shrink:0;flex-direction:column;visibility:hidden;}',
        '#__rw_pick_bar.on{visibility:visible;}',
        '#__rw_pick_slots{display:flex;gap:8px;align-items:flex-start;}',
        '#__rw_pick_slot_ref,#__rw_pick_slot_tgt{flex:1;padding:7px 10px;border-radius:6px;',
        'border:1px solid #334155;background:#1e293b;font-size:11px;font-family:inherit;color:#94a3b8;',
        'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
        '#__rw_pick_slot_ref.set{border-color:#3b82f6;color:#93c5fd;}',
        '#__rw_pick_slot_tgt.set{border-color:#f59e0b;color:#fcd34d;}',
        '#__rw_pick_arrow{color:#475569;font-size:16px;line-height:1;padding-top:6px;flex-shrink:0;}',
        '#__rw_pick_actions{display:flex;gap:8px;align-items:center;}',
        '#__rw_pick_note{flex:1;padding:5px 8px;border-radius:5px;border:1px solid #334155;',
        'background:#1e293b;color:#e2e8f0;font-size:12px;font-family:inherit;outline:none;}',
        '#__rw_pick_note::placeholder{color:#475569;}',
        '#__rw_pick_apply{padding:6px 14px;border-radius:6px;border:none;background:#16a34a;',
        'color:#fff;cursor:pointer;font-size:12px;font-weight:600;white-space:nowrap;}',
        '#__rw_pick_apply:hover:not(:disabled){background:#15803d;}',
        '#__rw_pick_apply:disabled{background:#374151;cursor:not-allowed;}',
        '#__rw_pick_apply.transform{background:#b45309;}',
        '#__rw_pick_apply.transform:hover:not(:disabled){background:#92400e;}',
        '#__rw_pick_cancel{padding:6px 10px;border-radius:6px;border:1px solid #334155;',
        'background:transparent;color:#94a3b8;cursor:pointer;font-size:12px;white-space:nowrap;}',
        '#__rw_pick_cancel:hover{background:#1e293b;}',

        '#__rw_add_bar{padding:8px 12px;background:#0a0f1a;border-top:2px solid #166534;',
        'display:flex;gap:6px;flex-shrink:0;flex-direction:column;visibility:hidden;}',
        '#__rw_add_bar.on{visibility:visible;}',
        '#__rw_add_hint{font-size:11px;color:#4ade80;}',
        '#__rw_add_row{display:flex;gap:8px;align-items:center;}',
        '#__rw_add_desc{flex:1;padding:5px 8px;border-radius:5px;border:1px solid #334155;',
        'background:#1e293b;color:#e2e8f0;font-size:12px;font-family:inherit;outline:none;}',
        '#__rw_add_desc:focus{border-color:#22c55e;}',
        '#__rw_add_desc::placeholder{color:#475569;}',
        '#__rw_add_submit{padding:6px 14px;border-radius:6px;border:none;background:#16a34a;',
        'color:#fff;cursor:pointer;font-size:12px;font-weight:600;white-space:nowrap;}',
        '#__rw_add_submit:hover:not(:disabled){background:#15803d;}',
        '#__rw_add_submit:disabled{background:#374151;cursor:not-allowed;}',
        '#__rw_add_cancel{padding:6px 10px;border-radius:6px;border:1px solid #334155;',
        'background:transparent;color:#94a3b8;cursor:pointer;font-size:12px;white-space:nowrap;}',
        '#__rw_add_cancel:hover{background:#1e293b;}',

        /* Toast */
        '#__rw_apply_status{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);',
        'padding:10px 36px 10px 22px;border-radius:8px;background:#1e293b;color:#e2e8f0;',
        'font-size:13px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;',
        'z-index:2147483649;display:none;box-shadow:0 4px 20px rgba(0,0,0,.4);',
        'max-width:600px;word-break:break-word;user-select:text;cursor:text;}',
        '#__rw_apply_status.on{display:block;}',
        '#__rw_apply_status.ok{background:#14532d;color:#86efac;}',
        '#__rw_apply_status.err{background:#7f1d1d;color:#fca5a5;}',
        '#__rw_apply_status_close{position:absolute;top:6px;right:8px;background:none;border:none;',
        'color:inherit;opacity:.6;cursor:pointer;font-size:16px;line-height:1;padding:2px 4px;}',
        '#__rw_apply_status_close:hover{opacity:1;}',
        '#__rw_apply_status_copy{display:none;margin-top:7px;padding:3px 12px;border-radius:4px;',
        'border:1px solid currentColor;background:none;color:inherit;opacity:.7;cursor:pointer;',
        'font-size:11px;font-family:inherit;}',
        '#__rw_apply_status_copy:hover{opacity:1;}',
        '#__rw_apply_status.err #__rw_apply_status_copy{display:inline-block;}',
    ].join('');

    var styleEl = document.createElement('style');
    styleEl.id = '__rw_style';
    styleEl.textContent = css;
    (document.head || document.documentElement).appendChild(styleEl);

    /* ── DOM ─────────────────────────────────────────────────────────────────── */

    /* Таб-бар */
    var tabbar = document.createElement('div');
    tabbar.id = '__rw_tabbar';
    tabbar.innerHTML = [
        '<a id="__rw_logo" href="/" title="RhapsodyAI Dashboard">',
        '  <img src="/static/assets/logo.png" alt="Logo">',
        '  <span>RhapsodyAI</span>',
        '</a>',
        '<span class="rw-tab active" id="__rw_tab_proto">📄 Прототип</span>',
        '<span class="rw-tab" id="__rw_tab_edit">✏ Редактирование</span>',
        '<span class="rw-tab" id="__rw_tab_browser">🖱 Браузер</span>',
    ].join('');

    /* Хлебные крошки навигации */
    var breadbar = document.createElement('div');
    breadbar.id = '__rw_breadbar';

    /* Оверлей режима редактирования (покрывает страницу) */
    var editOverlay = document.createElement('div');
    editOverlay.id = '__rw_edit_overlay';

    var editHighlight = document.createElement('div');
    editHighlight.id = '__rw_edit_hl';

    var editActions = document.createElement('div');
    editActions.id = '__rw_edit_actions';
    editActions.innerHTML = [
        '<button class="danger" id="__rw_ea_delete" title="Удалить блок">🗑</button>',
        '<button class="move-btn" id="__rw_ea_move" title="Переместить блок">⠿</button>',
        '<button class="text-btn" id="__rw_ea_text" title="Редактировать текст">T</button>',
        '<button class="ai-btn" id="__rw_ea_ai" title="AI: доработать блок">AI</button>',
    ].join('');

    var textEditBar = document.createElement('div');
    textEditBar.id = '__rw_text_bar';
    textEditBar.innerHTML = [
        '<span id="__rw_text_bar_hint">✏ Редактирование текста — кликайте и вводите текст</span>',
        '<button id="__rw_text_bar_done">Готово</button>',
        '<button id="__rw_text_bar_cancel">Отмена</button>',
    ].join('');

    var editDropLine = document.createElement('div');
    editDropLine.id = '__rw_edit_drop_line';

    /* AI-панель */
    var aiPanel = document.createElement('div');
    aiPanel.id = '__rw_ai_panel';
    aiPanel.innerHTML = [
        '<div id="__rw_ai_head">',
        '  <span id="__rw_ai_head_title">✨ AI: доработать блок</span>',
        '  <button id="__rw_ai_close">×</button>',
        '</div>',
        '<div id="__rw_ai_body">',
        '  <textarea id="__rw_ai_ta" placeholder="Опиши что изменить в этом блоке..."></textarea>',
        '  <div id="__rw_ai_row">',
        '    <button id="__rw_ai_mic"><span id="__rw_ai_mic_icon">🎤</span>&nbsp;<span id="__rw_ai_mic_lbl">Голос</span></button>',
        '    <button id="__rw_ai_submit">Применить →</button>',
        '  </div>',
        '  <div id="__rw_ai_status"></div>',
        '</div>',
    ].join('');

    /* Браузер (split-screen) */
    var split = document.createElement('div');
    split.id = '__rw_split';
    split.innerHTML = [
        '<div id="__rw_split_content">',
        /* Левая — прототип */
        '  <div id="__rw_proto_side">',
        '    <div id="__rw_proto_bar">',
        '      <div id="__rw_proto_breadcrumbs"></div>',
        '      <button id="__rw_proto_add_btn" title="Добавить новый блок в прототип">⊕ Добавить блок</button>',
        '    </div>',
        '    <iframe id="__rw_proto_frame" src="' + location.href + (location.href.indexOf('?') === -1 ? '?' : '&') + '__rw_embed=1"></iframe>',
        '    <div id="__rw_proto_overlay"></div>',
        '    <div id="__rw_proto_highlight"></div>',
        '    <div id="__rw_proto_actions">',
        '      <button class="danger" id="__rw_pa_delete" title="Удалить блок">🗑</button>',
        '      <button class="move-btn" id="__rw_pa_move" title="Переместить блок">⠿</button>',
        '    </div>',
        '    <div id="__rw_proto_drop_line"></div>',
        '  </div>',
        /* Правая — браузер */
        '  <div id="__rw_browser_side">',
        '    <div id="__rw_browser_bar">',
        '      <button id="__rw_browser_back">←</button>',
        '      <div id="__rw_url_wrap">',
        '        <input id="__rw_browser_url" type="text" placeholder="https://example.com" autocomplete="off" />',
        '        <div id="__rw_url_history"></div>',
        '      </div>',
        '      <button id="__rw_browser_go">Открыть</button>',
        '      <span id="__rw_browser_title"></span>',
        '    </div>',
        '    <div id="__rw_browser_view">',
        '      <img id="__rw_browser_img" src="" alt="" draggable="false" />',
        '      <canvas id="__rw_browser_canvas"></canvas>',
        '      <div id="__rw_browser_loader">Загрузка...</div>',
        '    </div>',
        '    <div id="__rw_hscroll"><div id="__rw_hscroll_thumb"></div></div>',
        '  </div>',
        '</div>',
        /* Нижние панели */
        '<div id="__rw_pick_bar">',
        '  <div id="__rw_pick_slots">',
        '    <div id="__rw_pick_slot_ref">Эталон: не выбран</div>',
        '    <span id="__rw_pick_arrow">→</span>',
        '    <div id="__rw_pick_slot_tgt">Цель: весь прототип</div>',
        '  </div>',
        '  <div id="__rw_pick_actions">',
        '    <input id="__rw_pick_note" type="text" placeholder="Комментарий (необязательно)" />',
        '    <button id="__rw_pick_cancel">Сбросить</button>',
        '    <button id="__rw_pick_apply">Применить →</button>',
        '  </div>',
        '</div>',
        '<div id="__rw_add_bar">',
        '  <div id="__rw_add_hint">⊕ Кликни в прототипе слева, чтобы выбрать место вставки</div>',
        '  <div id="__rw_add_row">',
        '    <input id="__rw_add_desc" type="text" placeholder="Опиши новый блок (напр. «карточка с ценой»)" />',
        '    <button id="__rw_add_cancel">Отмена</button>',
        '    <button id="__rw_add_submit" disabled>Создать →</button>',
        '  </div>',
        '</div>',
    ].join('');

    var applyStatus = document.createElement('div');
    applyStatus.id = '__rw_apply_status';

    /* Один контейнер для всех overlay-элементов — не засоряет DOM после <footer>.
       Дочерние элементы position:fixed позиционируются относительно viewport, не контейнера. */
    var overlayContainer = document.createElement('div');
    overlayContainer.id = '__rw_overlay_container';
    overlayContainer.appendChild(editOverlay);
    overlayContainer.appendChild(editHighlight);
    overlayContainer.appendChild(editActions);
    overlayContainer.appendChild(editDropLine);
    overlayContainer.appendChild(textEditBar);
    overlayContainer.appendChild(aiPanel);
    overlayContainer.appendChild(split);
    overlayContainer.appendChild(applyStatus);

    tabbar.appendChild(breadbar);
    /* Вставляем tabbar первым в body — смещает контент вниз без position:fixed */
    document.body.insertBefore(tabbar, document.body.firstChild);
    /* Контейнер сразу после tabbar, до контента прототипа */
    document.body.insertBefore(overlayContainer, tabbar.nextSibling);

    /* Сдвигаем элементы с position:fixed, которые LLM зафиксировала у top:0 —
       они иначе перекрывают наш tabbar (36px). Запускаем после layout. */
    requestAnimationFrame(function() {
        var tabH = tabbar.offsetHeight || 36;
        document.querySelectorAll('*').forEach(function(el) {
            if (el.id && el.id.startsWith('__rw_')) return;
            var s = window.getComputedStyle(el);
            if (s.position !== 'fixed') return;
            var topVal = parseFloat(s.top);
            if (!isNaN(topVal) && topVal < tabH) {
                el.style.top = (topVal + tabH) + 'px';
            }
        });
    });

    /* ── Refs ─────────────────────────────────────────────────────────────────── */
    var tabProto   = document.getElementById('__rw_tab_proto');
    var tabEdit    = document.getElementById('__rw_tab_edit');
    var tabBrowser = document.getElementById('__rw_tab_browser');

    /* Edit mode */
    var eaDeleteBtn  = document.getElementById('__rw_ea_delete');
    var eaMoveBtn    = document.getElementById('__rw_ea_move');
    var eaTextBtn    = document.getElementById('__rw_ea_text');
    var eaAiBtn      = document.getElementById('__rw_ea_ai');
    var textBarDone  = document.getElementById('__rw_text_bar_done');
    var textBarCancel = document.getElementById('__rw_text_bar_cancel');

    /* AI panel */
    var aiClose     = document.getElementById('__rw_ai_close');
    var aiTa        = document.getElementById('__rw_ai_ta');
    var aiMicBtn    = document.getElementById('__rw_ai_mic');
    var aiMicIcon   = document.getElementById('__rw_ai_mic_icon');
    var aiMicLbl    = document.getElementById('__rw_ai_mic_lbl');
    var aiSubmitBtn = document.getElementById('__rw_ai_submit');
    var aiStatusEl  = document.getElementById('__rw_ai_status');

    /* Browser split */
    var protoFrame          = document.getElementById('__rw_proto_frame');
    var protoOverlay        = document.getElementById('__rw_proto_overlay');
    var protoHighlight      = document.getElementById('__rw_proto_highlight');
    var protoBreadcrumbs    = document.getElementById('__rw_proto_breadcrumbs');
    var protoActions        = document.getElementById('__rw_proto_actions');
    var protoActDelete      = document.getElementById('__rw_pa_delete');
    var protoActMove        = document.getElementById('__rw_pa_move');
    var protoDropLine       = document.getElementById('__rw_proto_drop_line');

    var browserUrlIn    = document.getElementById('__rw_browser_url');
    var browserGoBtn    = document.getElementById('__rw_browser_go');
    var browserBackBtn  = document.getElementById('__rw_browser_back');
    var browserImg      = document.getElementById('__rw_browser_img');
    var browserCanvas   = document.getElementById('__rw_browser_canvas');
    var browserView     = document.getElementById('__rw_browser_view');
    var browserLoader   = document.getElementById('__rw_browser_loader');
    var browserTitle    = document.getElementById('__rw_browser_title');
    var urlHistoryDrop  = document.getElementById('__rw_url_history');
    var hscroll         = document.getElementById('__rw_hscroll');
    var hscrollThumb    = document.getElementById('__rw_hscroll_thumb');

    var pickBar         = document.getElementById('__rw_pick_bar');
    var pickSlotRef     = document.getElementById('__rw_pick_slot_ref');
    var pickSlotTgt     = document.getElementById('__rw_pick_slot_tgt');
    var pickNote        = document.getElementById('__rw_pick_note');
    var pickApplyBtn    = document.getElementById('__rw_pick_apply');
    var pickCancelBtn   = document.getElementById('__rw_pick_cancel');

    var addBar      = document.getElementById('__rw_add_bar');
    var addHint     = document.getElementById('__rw_add_hint');
    var addDesc     = document.getElementById('__rw_add_desc');
    var addSubmit   = document.getElementById('__rw_add_submit');
    var addCancel   = document.getElementById('__rw_add_cancel');
    var protoAddBtn = document.getElementById('__rw_proto_add_btn');

    /* ── State ─────────────────────────────────────────────────────────────────── */
    var currentTab      = 'proto';   /* 'proto' | 'edit' | 'browser' */
    var mediaRecorder   = null;
    var stream          = null;
    var audioChunks     = [];

    var browserScaleX   = 1;
    var browserScaleY   = 1;
    var browserDisplayW = 0;
    var browserDisplayH = 0;
    var browserLoaded   = false;

    var drag = { active: false, sx: 0, sy: 0, ex: 0, ey: 0 };
    var pickedRef       = null;
    var pickedTarget    = null;
    var _addMode        = false;
    var _addInsert      = null;

    /* Edit-mode state */
    var _editHoveredEl   = null;
    var _editPickedEl    = null;
    var _editMoveMode    = false;
    var _editMovingEl    = null;
    var _editDropTarget  = null;
    var _textEditActive  = false;
    var _textEditEl      = null;
    var _textEditOrigHtml = '';

    /* ── Tab switching ────────────────────────────────────────────────────────── */
    function activateTab(name) {
        currentTab = name;
        tabProto.classList[name === 'proto'   ? 'add' : 'remove']('active');
        tabEdit.classList[name === 'edit'     ? 'add' : 'remove']('active');
        tabBrowser.classList[name === 'browser' ? 'add' : 'remove']('active');

        /* Браузер */
        split.classList[name === 'browser' ? 'add' : 'remove']('on');

        /* Редактирование */
        if (name === 'edit') {
            editOverlay.classList.add('on');
        } else {
            /* Если был активен text edit — отменяем */
            if (_textEditActive) endTextEdit(false);
            editOverlay.classList.remove('on');
            editOverlay.style.pointerEvents = '';  /* сброс на случай незавершённого drag */
            _editHideActions();
            _editHoveredEl = null;
            _editPickedEl = null;
            if (_editMoveMode) _editMoveMode = false;
            editDropLine.style.display = 'none';
            closeAiPanel();
        }

        if (name !== 'browser') {
            disableAddMode();
            /* Деактивируем overlay прототипа при уходе из браузера */
            protoOverlay.classList.remove('active');
            pickedTarget = null;
            protoHighlight.style.display = 'none';
            protoActions.classList.remove('on');
        }

        if (name === 'browser') {
            requestAnimationFrame(resizeCanvas);
            /* Overlay прототипа активен всегда в браузерном режиме */
            _protoActivateOverlay();
        }
    }

    /* Event delegation на tabbar — надёжнее прямых listeners при сложной вёрстке */
    document.getElementById('__rw_tabbar').addEventListener('click', function(e) {
        var tab = e.target.closest ? e.target.closest('.rw-tab') : null;
        if (!tab) return;
        e.stopPropagation();
        if (tab === tabProto)   activateTab('proto');
        else if (tab === tabEdit)    activateTab('edit');
        else if (tab === tabBrowser) activateTab('browser');
    });

    /* ── Глобальные хлебные крошки (навигация по прототипу) ─────────────────── */
    var _NAV_KEY = '__rw_nav_' + projectId;

    function _pageLabel(href) {
        var path = href.split('?')[0].split('#')[0];
        var parts = path.split('/').filter(Boolean);
        return parts[parts.length - 1] || 'index.html';
    }

    /* Восстанавливаем историю из sessionStorage (переживает page reload) */
    function _navLoad() {
        try {
            var raw = sessionStorage.getItem(_NAV_KEY);
            if (raw) {
                var saved = JSON.parse(raw);
                /* Если текущий URL уже есть в истории — восстанавливаем позицию */
                var cur = location.href;
                var idx = saved.history.findIndex(function(h) { return h.href === cur; });
                if (idx !== -1) {
                    return { history: saved.history, pos: idx };
                }
                /* Новая страница (переход по ссылке) — добавляем в конец */
                var hist = saved.history.slice(0, saved.pos + 1);
                hist.push({ href: cur, label: _pageLabel(cur) });
                return { history: hist, pos: hist.length - 1 };
            }
        } catch(e) {}
        return { history: [{ href: location.href, label: pageName }], pos: 0 };
    }

    function _navSave() {
        try {
            sessionStorage.setItem(_NAV_KEY, JSON.stringify({ history: _navHistory, pos: _navPos }));
        } catch(e) {}
    }

    var _loaded = _navLoad();
    var _navHistory = _loaded.history;
    var _navPos     = _loaded.pos;
    _navSave();

    function _renderBreadbar() {
        breadbar.innerHTML = '';
        var crumbs = _navHistory.slice(0, _navPos + 1);
        crumbs.forEach(function(item, i) {
            if (i > 0) {
                var sep = document.createElement('span');
                sep.className = 'rw-bc-sep';
                sep.textContent = '›';
                breadbar.appendChild(sep);
            }
            var el = document.createElement('span');
            var isLink = i < _navPos;
            el.className = 'rw-bc' + (isLink ? ' rw-bc-link' : '');
            el.textContent = (i === 0 ? '🏠 ' : '') + item.label;
            if (isLink) {
                (function(pos) {
                    el.addEventListener('click', function() {
                        _navPos = pos;
                        _navSave();
                        location.href = _navHistory[pos].href;
                    });
                })(i);
            }
            breadbar.appendChild(el);
        });
    }
    _renderBreadbar();

    /* ── Edit mode — overlay over the real page ───────────────────────────────── */
    var EDIT_BLOCK_TAGS = ['DIV','SECTION','ARTICLE','HEADER','FOOTER','NAV','MAIN','ASIDE','LI','UL','FIGURE','FORM','TABLE'];

    function _editElementAt(clientX, clientY) {
        /* pointer-events:none позволяет elementFromPoint пропустить оверлей — не трогаем display */
        editOverlay.style.pointerEvents = 'none';
        var el = document.elementFromPoint(clientX, clientY);
        editOverlay.style.pointerEvents = '';
        if (!el || el === document.body || el === document.documentElement) return null;
        var candidate = el;
        while (candidate && candidate !== document.body) {
            if (EDIT_BLOCK_TAGS.indexOf(candidate.tagName) !== -1) break;
            candidate = candidate.parentElement;
        }
        if (!candidate || candidate === document.body) candidate = el;
        return candidate;
    }

    function _editShowHighlight(el, hover) {
        var r = el.getBoundingClientRect();
        Object.assign(editHighlight.style, {
            display: 'block',
            top:    r.top + 'px',
            left:   r.left + 'px',
            width:  r.width + 'px',
            height: r.height + 'px',
        });
        editHighlight.classList[hover ? 'add' : 'remove']('hover');
    }

    function _editShowActions(el) {
        var r = el.getBoundingClientRect();
        editActions.classList.add('on');
        requestAnimationFrame(function() {
            var w = editActions.offsetWidth  || 90;
            var h = editActions.offsetHeight || 30;
            var TOP_CLEARANCE = 8; /* минимальный отступ от верха */
            /* Пробуем разместить над блоком, иначе — под блоком */
            var top  = r.top - h - 6;
            var left = r.right - w;
            if (top < TOP_CLEARANCE) top = Math.min(r.bottom + 6, window.innerHeight - h - 8);
            if (left < 0) left = 0;
            if (left + w > window.innerWidth) left = window.innerWidth - w - 4;
            editActions.style.top  = top  + 'px';
            editActions.style.left = left + 'px';
        });
    }

    function _editHideActions() {
        editActions.classList.remove('on');
        editHighlight.style.display = 'none';
    }

    editOverlay.addEventListener('mousemove', function(e) {
        if (_editMoveMode) { _editHandleMoveDrag(e); return; }
        var el = _editElementAt(e.clientX, e.clientY);
        if (!el) { _editHoveredEl = null; editHighlight.style.display = 'none'; return; }
        _editHoveredEl = el;
        _editShowHighlight(el, true);
    });

    editOverlay.addEventListener('mouseleave', function() {
        if (_editPickedEl) return;
        _editHoveredEl = null;
        editHighlight.style.display = 'none';
    });

    editOverlay.addEventListener('click', function(e) {
        if (_editMoveMode) return;
        var el = _editElementAt(e.clientX, e.clientY);
        if (!el) { _editHideActions(); _editPickedEl = null; return; }
        _editPickedEl = el;
        _editShowHighlight(el, false);
        _editShowActions(el);
        closeAiPanel();
    });

    /* Удалить блок */
    eaDeleteBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (!_editPickedEl) return;
        _editPickedEl.remove();
        _editPickedEl = null;
        _editHideActions();
        _editSavePage();
    });

    /* Move (drag) */
    eaMoveBtn.addEventListener('mousedown', function(e) {
        e.preventDefault();
        e.stopPropagation();
        if (!_editPickedEl) return;
        _editMoveMode  = true;
        _editMovingEl  = _editPickedEl;
        editOverlay.style.cursor = 'grabbing';
        editHighlight.style.opacity = '0.35';
        editDropLine.style.display = 'block';
        editActions.classList.remove('on');
    });

    function _editHandleMoveDrag(e) {
        editOverlay.style.pointerEvents = 'none';
        _editMovingEl.style.visibility = 'hidden';
        var el = document.elementFromPoint(e.clientX, e.clientY);
        _editMovingEl.style.visibility = '';
        editOverlay.style.pointerEvents = '';
        if (!el || el === _editMovingEl || _editMovingEl.contains(el)) return;
        var parent = _editMovingEl.parentElement;
        var target = el;
        while (target && target.parentElement !== parent) target = target.parentElement;
        if (!target || target === _editMovingEl) return;
        var r = target.getBoundingClientRect();
        var before = e.clientY < (r.top + r.height / 2);
        _editDropTarget = { el: target, before: before };
        Object.assign(editDropLine.style, {
            display: 'block',
            top:   ((before ? r.top : r.bottom) - 2) + 'px',
            left:  r.left + 'px',
            width: r.width + 'px',
        });
    }

    document.addEventListener('mouseup', function(e) {
        if (!_editMoveMode) return;
        _editMoveMode = false;
        editOverlay.style.cursor = '';
        editDropLine.style.display = 'none';
        editHighlight.style.opacity = '';

        if (_editDropTarget && _editMovingEl) {
            var parent = _editDropTarget.el.parentElement;
            if (_editDropTarget.before) {
                parent.insertBefore(_editMovingEl, _editDropTarget.el);
            } else {
                parent.insertBefore(_editMovingEl, _editDropTarget.el.nextSibling);
            }
            _editSavePage();
        }
        _editDropTarget = null;
        _editMovingEl = null;
        _editPickedEl = null;
        _editHideActions();
    });

    /* AI кнопка */
    eaAiBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (!_editPickedEl) return;
        openAiPanel(_editPickedEl);
    });

    /* Захватывает outerHTML страницы без виджет-элементов */
    function _capturePageHtml() {
        var detached = [];
        /* Снимаем style и overlay-контейнер с tabbar из DOM перед снятием снапшота */
        [styleEl, tabbar, overlayContainer].forEach(function(el) {
            if (el && el.parentNode) {
                detached.push({ el: el, parent: el.parentNode, next: el.nextSibling });
                el.parentNode.removeChild(el);
            }
        });
        var html = '<!DOCTYPE html>\n' + document.documentElement.outerHTML;
        /* Восстанавливаем в обратном порядке */
        for (var i = detached.length - 1; i >= 0; i--) {
            var d = detached[i];
            if (d.next) d.parent.insertBefore(d.el, d.next);
            else d.parent.appendChild(d.el);
        }
        return html;
    }

    function _editSavePage() {
        try {
            var html = _capturePageHtml();
            fetch('/planning/prototype/' + projectId + '/patch', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ page_name: pageName, html: html }),
            }).then(function(r) { return r.json(); }).then(function(d) {
                if (d.error) showApplyStatus('Ошибка сохранения: ' + d.error, 'err');
                else showApplyStatus('✓ Сохранено', 'ok');
            }).catch(function(e) { showApplyStatus('Ошибка: ' + e.message, 'err'); });
        } catch(e) { showApplyStatus('Ошибка: ' + e.message, 'err'); }
    }

    /* ── AI Panel ─────────────────────────────────────────────────────────────── */
    var _aiTargetEl = null;

    function openAiPanel(el) {
        _aiTargetEl = el;
        aiTa.value = '';
        setAiStatus('');
        aiPanel.classList.add('on');
        /* Позиционируем рядом с кнопками действий */
        requestAnimationFrame(function() {
            var ar = editActions.getBoundingClientRect();
            var pw = 340;
            var ph = aiPanel.offsetHeight || 200;
            var left = ar.left;
            if (left + pw > window.innerWidth - 8) left = window.innerWidth - pw - 8;
            if (left < 8) left = 8;
            var top = ar.bottom + 6;
            if (top + ph > window.innerHeight - 8) top = ar.top - ph - 6;
            aiPanel.style.left = left + 'px';
            aiPanel.style.top  = top  + 'px';
        });
        aiTa.focus();
    }

    function closeAiPanel() {
        aiPanel.classList.remove('on');
        _aiTargetEl = null;
        stopRecording();
    }

    aiClose.addEventListener('click', closeAiPanel);

    function setAiStatus(msg, cls) {
        aiStatusEl.textContent = msg;
        aiStatusEl.className = cls || '';
    }

    aiSubmitBtn.addEventListener('click', async function() {
        var request = aiTa.value.trim();
        if (!request) { aiTa.focus(); return; }
        if (aiSubmitBtn.disabled) return;

        var targetHtml = _aiTargetEl ? (_aiTargetEl.outerHTML || '').slice(0, 800) : '';
        var fullRequest = targetHtml
            ? 'Доработай блок: "' + request + '". HTML блока: ' + targetHtml
            : request;

        aiSubmitBtn.disabled = true;
        setAiStatus('Отправляю в LLM...');

        try {
            var resp = await fetch('/planning/prototype/' + projectId + '/refine', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ page_name: pageName, request: fullRequest }),
            });
            var data = await resp.json();
            if (data.result === 'ok') {
                setAiStatus('✓ Применено', 'ok');
                closeAiPanel();
                _editHideActions();
                _editPickedEl = null;
                setTimeout(function() { window.location.reload(); }, 800);
            } else {
                setAiStatus('Ошибка: ' + (data.error || 'неизвестная'), 'err');
            }
        } catch(e) {
            setAiStatus('Ошибка: ' + e.message, 'err');
        } finally {
            aiSubmitBtn.disabled = false;
        }
    });

    aiTa.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) aiSubmitBtn.click();
    });

    /* ── Voice recording (для AI-панели) ────────────────────────────────────── */
    function stopRecording() {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
        if (stream) { stream.getTracks().forEach(function(t) { t.stop(); }); stream = null; }
        aiMicBtn.classList.remove('recording');
        aiMicIcon.textContent = '🎤';
        aiMicLbl.textContent  = 'Голос';
    }

    aiMicBtn.addEventListener('click', async function() {
        if (aiMicBtn.classList.contains('processing')) return;
        if (aiMicBtn.classList.contains('recording')) { stopRecording(); return; }
        try {
            stream = await navigator.mediaDevices.getUserMedia({audio: true});
        } catch(e) { setAiStatus('Нет доступа к микрофону', 'err'); return; }

        audioChunks = [];
        var mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/ogg';
        mediaRecorder = new MediaRecorder(stream, {mimeType: mimeType});

        mediaRecorder.ondataavailable = function(e) { if (e.data && e.data.size > 0) audioChunks.push(e.data); };
        mediaRecorder.onstop = async function() {
            var blob = new Blob(audioChunks, {type: mimeType});
            audioChunks = [];
            aiMicBtn.classList.add('processing');
            aiMicIcon.textContent = '⏳'; aiMicLbl.textContent = 'Обработка...';
            setAiStatus('Распознаю речь...');
            try {
                var ext = mimeType.includes('webm') ? 'webm' : 'ogg';
                var fd  = new FormData();
                fd.append('file', blob, 'voice.' + ext);
                var resp = await fetch('/chat/voice', {method: 'POST', credentials: 'include', body: fd});
                var data = await resp.json();
                var text = (data.result || '').trim();
                if (text) { aiTa.value = aiTa.value ? aiTa.value + ' ' + text : text; setAiStatus(''); }
                else setAiStatus('Не удалось распознать речь', 'err');
            } catch(e) { setAiStatus('Ошибка распознавания', 'err'); }
            finally {
                aiMicBtn.classList.remove('processing');
                aiMicIcon.textContent = '🎤'; aiMicLbl.textContent = 'Голос';
            }
        };

        mediaRecorder.start();
        aiMicBtn.classList.add('recording');
        aiMicIcon.textContent = '⏹'; aiMicLbl.textContent = 'Стоп';
        setAiStatus('Запись... нажми Стоп когда закончишь');
    });

    /* ── Text editing ─────────────────────────────────────────────────────────── */
    function startTextEdit(el) {
        _textEditActive  = true;
        _textEditEl      = el;
        _textEditOrigHtml = el.innerHTML;
        /* Скрываем оверлей, чтобы пользователь мог кликать по тексту */
        editOverlay.classList.remove('on');
        editOverlay.style.pointerEvents = 'none';
        _editHideActions();
        closeAiPanel();
        /* Делаем блок редактируемым */
        el.contentEditable = 'true';
        el.style.outline = '2px solid #22c55e';
        el.style.outlineOffset = '2px';
        el.focus();
        /* Ставим курсор в конец */
        try {
            var range = document.createRange();
            var sel   = window.getSelection();
            range.selectNodeContents(el);
            range.collapse(false);
            sel.removeAllRanges();
            sel.addRange(range);
        } catch(e) {}
        textEditBar.classList.add('on');
    }

    function endTextEdit(save) {
        if (!_textEditActive || !_textEditEl) return;
        var el = _textEditEl;
        if (!save) {
            el.innerHTML = _textEditOrigHtml;
        }
        el.contentEditable = 'false';
        el.style.outline   = '';
        el.style.outlineOffset = '';
        textEditBar.classList.remove('on');
        _textEditActive = false;
        _textEditEl     = null;
        /* Возвращаем оверлей */
        editOverlay.style.pointerEvents = '';
        editOverlay.classList.add('on');
        _editPickedEl = null;
        if (save) _editSavePage();
    }

    eaTextBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (!_editPickedEl) return;
        startTextEdit(_editPickedEl);
    });

    textBarDone.addEventListener('click', function() { endTextEdit(true); });
    textBarCancel.addEventListener('click', function() { endTextEdit(false); });

    /* ── ESC ─────────────────────────────────────────────────────────────────── */
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            if (_textEditActive) { endTextEdit(false); return; }
            if (aiPanel.classList.contains('on')) { closeAiPanel(); return; }
            if (currentTab === 'edit') { _editHideActions(); _editPickedEl = null; return; }
        }
    });

    /* ── Prototype breadcrumbs (для браузерного split) ───────────────────────── */
    var _embedParam = '__rw_embed=1';
    function _protoCleanHref(href) {
        return href.replace(/[?&]__rw_embed=1/, '').replace(/\?&/, '?').replace(/&&/, '&');
    }
    function _protoLabel(href) {
        var path = href.split('?')[0].split('#')[0];
        var parts = path.split('/').filter(Boolean);
        return parts[parts.length - 1] || 'index.html';
    }
    var _protoHistory    = [{ href: _protoCleanHref(location.href), label: pageName }];
    var _protoHistoryPos = 0;

    function _renderProtoBreadcrumbs() {
        protoBreadcrumbs.innerHTML = '';
        var crumbs = _protoHistory.slice(0, _protoHistoryPos + 1);
        crumbs.forEach(function(item, i) {
            if (i > 0) {
                var sep = document.createElement('span');
                sep.className = 'rw-sep';
                sep.textContent = '›';
                protoBreadcrumbs.appendChild(sep);
            }
            var el = document.createElement('span');
            el.className = 'rw-crumb' + (i < _protoHistoryPos ? ' rw-link' : '');
            el.textContent = (i === 0 ? '📄 ' : '') + item.label;
            if (i < _protoHistoryPos) {
                (function(pos) {
                    el.addEventListener('click', function() {
                        _protoHistoryPos = pos;
                        var src = _protoHistory[pos].href;
                        protoFrame.src = src + (src.indexOf('?') === -1 ? '?' : '&') + _embedParam;
                        _renderProtoBreadcrumbs();
                    });
                })(i);
            }
            protoBreadcrumbs.appendChild(el);
        });
    }
    _renderProtoBreadcrumbs();

    protoFrame.addEventListener('load', function() {
        try {
            var newHref = _protoCleanHref(protoFrame.contentWindow.location.href);
            if (!newHref || newHref === 'about:blank') return;
            var current = _protoHistory[_protoHistoryPos].href;
            if (newHref === current) return;
            if (_protoHistoryPos > 0 && _protoHistory[_protoHistoryPos - 1].href === newHref) {
                _protoHistoryPos--;
            } else {
                _protoHistory = _protoHistory.slice(0, _protoHistoryPos + 1);
                _protoHistory.push({ href: newHref, label: _protoLabel(newHref) });
                _protoHistoryPos++;
            }
            _renderProtoBreadcrumbs();
        } catch(e) {}
    });

    /* ── Split: Proto overlay (всегда активен в браузерном режиме) ─────────────── */
    function _protoActivateOverlay() {
        var barRect   = document.getElementById('__rw_proto_bar').getBoundingClientRect();
        var sideRect  = document.getElementById('__rw_proto_side').getBoundingClientRect();
        protoOverlay.style.top = (barRect.bottom - sideRect.top) + 'px';
        protoOverlay.classList.add('active');
    }

    /* ── Split: Proto add mode ─────────────────────────────────────────────────── */
    function enableAddMode() {
        _addMode = true;
        protoAddBtn.classList.add('active');
        protoAddBtn.textContent = '✕ Отмена';
        _protoActivateOverlay();
        protoDropLine.style.display = 'block';
        addBar.classList.add('on');
        addHint.textContent = '⊕ Кликни в прототипе, чтобы выбрать место вставки';
        addDesc.value = '';
        addSubmit.disabled = true;
    }
    function disableAddMode() {
        _addMode = false;
        _addInsert = null;
        protoAddBtn.classList.remove('active');
        protoAddBtn.textContent = '⊕ Добавить блок';
        /* Оверлей прототипа остаётся активным — восстанавливаем его после add mode */
        _protoActivateOverlay();
        protoDropLine.style.display = 'none';
        protoHighlight.style.display = 'none';
        addBar.classList.remove('on');
        addDesc.value = '';
        addSubmit.disabled = true;
    }
    protoAddBtn.addEventListener('click', function() {
        if (_addMode) { disableAddMode(); return; }
        enableAddMode();
    });

    /* ── Split: overlay interactions ──────────────────────────────────────────── */
    var PROTO_BLOCK_TAGS = ['DIV','SECTION','ARTICLE','HEADER','FOOTER','NAV','MAIN','ASIDE','LI','UL','FIGURE','FORM','TABLE'];

    function _protoElementAt(clientX, clientY) {
        try {
            var overlayRect = protoOverlay.getBoundingClientRect();
            var x = clientX - overlayRect.left;
            var y = clientY - overlayRect.top;
            var iframeDoc = protoFrame.contentDocument || protoFrame.contentWindow.document;
            var el = iframeDoc.elementFromPoint(x, y);
            if (!el || el.tagName === 'HTML') return null;
            var candidate = el;
            while (candidate && candidate.tagName !== 'BODY') {
                if (PROTO_BLOCK_TAGS.indexOf(candidate.tagName) !== -1) break;
                candidate = candidate.parentElement;
            }
            if (!candidate || candidate.tagName === 'BODY') candidate = el;
            var sel = candidate.id
                ? '#' + candidate.id
                : (candidate.className && typeof candidate.className === 'string'
                    ? '.' + candidate.className.trim().split(/\s+/)[0]
                    : candidate.tagName.toLowerCase());
            return { candidate: candidate, sel: sel, elRect: candidate.getBoundingClientRect() };
        } catch(e) { return null; }
    }

    function _protoShowHighlight(elRect, hover) {
        var iframeRect    = protoFrame.getBoundingClientRect();
        var protoSideRect = document.getElementById('__rw_proto_side').getBoundingClientRect();
        Object.assign(protoHighlight.style, {
            display: 'block',
            top:    ((iframeRect.top  - protoSideRect.top)  + elRect.top)  + 'px',
            left:   ((iframeRect.left - protoSideRect.left) + elRect.left) + 'px',
            width:  elRect.width  + 'px',
            height: elRect.height + 'px',
        });
        protoHighlight.classList[hover ? 'add' : 'remove']('hover');
    }

    var _hoveredEl = null;
    var _moveMode = false;
    var _movingEl = null;
    var _dropTarget = null;

    function _protoCurrentPageName() {
        var cur = _protoHistory[_protoHistoryPos];
        if (!cur) return pageName;
        var m = cur.href.match(/\/planning\/preview\/\d+\/(.+?)(\?.*)?$/);
        return m ? m[1] : pageName;
    }

    function _protoSave() {
        try {
            var iframeDoc = protoFrame.contentDocument || protoFrame.contentWindow.document;
            /* Убираем запечённые виджет-элементы из iframe перед сохранением */
            _WIDGET_IDS.forEach(function(id) {
                var el = iframeDoc.getElementById(id);
                if (el && el.parentNode) el.parentNode.removeChild(el);
            });
            var html = '<!DOCTYPE html>\n' + iframeDoc.documentElement.outerHTML;
            fetch('/planning/prototype/' + projectId + '/patch', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ page_name: _protoCurrentPageName(), html: html }),
            }).then(function(r) { return r.json(); }).then(function(d) {
                if (d.error) showApplyStatus('Ошибка сохранения: ' + d.error, 'err');
                else showApplyStatus('✓ Сохранено', 'ok');
            }).catch(function(e) { showApplyStatus('Ошибка: ' + e.message, 'err'); });
        } catch(e) { showApplyStatus('Ошибка: ' + e.message, 'err'); }
    }

    function _protoShowActions(elRect) {
        var iframeRect    = protoFrame.getBoundingClientRect();
        var protoSideRect = document.getElementById('__rw_proto_side').getBoundingClientRect();
        var top   = (iframeRect.top  - protoSideRect.top)  + elRect.top;
        var right = (iframeRect.left - protoSideRect.left) + elRect.left + elRect.width;
        protoActions.classList.add('on');
        requestAnimationFrame(function() {
            var h = protoActions.offsetHeight || 32;
            var w = protoActions.offsetWidth  || 60;
            var t = top - h - 4;
            if (t < 0) t = top + 4;
            protoActions.style.top  = t + 'px';
            protoActions.style.left = (right - w) + 'px';
        });
    }

    protoOverlay.addEventListener('mousemove', function(e) {
        if (_moveMode) { _handleMoveDrag(e); return; }
        if (!_addMode) {
            var found = _protoElementAt(e.clientX, e.clientY);
            if (found) {
                _hoveredEl = found.candidate;
                _protoShowHighlight(found.elRect, true);
            } else {
                _hoveredEl = null;
                protoHighlight.style.display = 'none';
            }
            return;
        }
        if (_addMode) {
            var overlayRect = protoOverlay.getBoundingClientRect();
            var x = e.clientX - overlayRect.left;
            var y = e.clientY - overlayRect.top;
            try {
                var iframeDoc = protoFrame.contentDocument || protoFrame.contentWindow.document;
                var el = iframeDoc.elementFromPoint(x, y);
                if (!el || el.tagName === 'HTML' || el.tagName === 'BODY') { protoDropLine.style.display = 'none'; return; }
                var candidate = el;
                while (candidate && candidate.tagName !== 'BODY') {
                    if (PROTO_BLOCK_TAGS.indexOf(candidate.tagName) !== -1) break;
                    candidate = candidate.parentElement;
                }
                if (!candidate || candidate.tagName === 'BODY') candidate = el;
                var targetRect = candidate.getBoundingClientRect();
                var before = y < (targetRect.top + targetRect.height / 2);
                var iframeRect    = protoFrame.getBoundingClientRect();
                var protoSideRect = document.getElementById('__rw_proto_side').getBoundingClientRect();
                var lineY = (iframeRect.top - protoSideRect.top) + (before ? targetRect.top : targetRect.bottom);
                Object.assign(protoDropLine.style, {
                    display: 'block',
                    top:   (lineY - 1) + 'px',
                    left:  ((iframeRect.left - protoSideRect.left) + targetRect.left) + 'px',
                    width: targetRect.width + 'px',
                });
            } catch(err) {}
        }
    });

    protoOverlay.addEventListener('mouseleave', function() {
        if (!_moveMode && !pickedTarget) {
            protoHighlight.style.display = 'none';
            _hoveredEl = null;
        }
    });

    /* Форвардим wheel-события в iframe чтобы прото-сторона скроллилась */
    protoOverlay.addEventListener('wheel', function(e) {
        e.preventDefault();
        try {
            var iw = protoFrame.contentWindow;
            if (iw) iw.scrollBy({ left: e.deltaX, top: e.deltaY, behavior: 'instant' });
        } catch (ex) {}
    }, { passive: false });

    protoActDelete.addEventListener('click', function(e) {
        e.stopPropagation();
        var el = pickedTarget && pickedTarget._el;
        if (!el) return;
        el.remove();
        protoHighlight.style.display = 'none';
        protoActions.classList.remove('on');
        pickedTarget = null;
        updatePickBar();
        _protoSave();
    });

    protoActMove.addEventListener('mousedown', function(e) {
        e.preventDefault();
        e.stopPropagation();
        var el = pickedTarget && pickedTarget._el;
        if (!el) return;
        _moveMode  = true;
        _movingEl  = el;
        protoOverlay.classList.add('active');
        protoOverlay.style.cursor = 'grabbing';
        protoHighlight.style.opacity = '0.35';
        protoDropLine.style.display = 'block';
        protoActions.classList.remove('on');
    });

    function _handleMoveDrag(e) {
        var overlayRect = protoOverlay.getBoundingClientRect();
        var x = e.clientX - overlayRect.left;
        var y = e.clientY - overlayRect.top;
        try {
            var iframeDoc = protoFrame.contentDocument || protoFrame.contentWindow.document;
            _movingEl.style.visibility = 'hidden';
            var el = iframeDoc.elementFromPoint(x, y);
            _movingEl.style.visibility = '';
            if (!el || el === _movingEl || _movingEl.contains(el)) return;
            var parent = _movingEl.parentElement;
            var target = el;
            while (target && target.parentElement !== parent) target = target.parentElement;
            if (!target || target === _movingEl) return;

            var targetRect = target.getBoundingClientRect();
            var before = y < (targetRect.top - overlayRect.top + targetRect.height / 2);
            _dropTarget = { el: target, before: before };

            var iframeRect    = protoFrame.getBoundingClientRect();
            var protoSideRect = document.getElementById('__rw_proto_side').getBoundingClientRect();
            var lineY = (iframeRect.top - protoSideRect.top) + (before ? targetRect.top : targetRect.bottom);
            Object.assign(protoDropLine.style, {
                display: 'block',
                top:   (lineY - 1) + 'px',
                left:  ((iframeRect.left - protoSideRect.left) + targetRect.left) + 'px',
                width: targetRect.width + 'px',
            });
        } catch(err) {}
    }

    document.addEventListener('mouseup', function(e) {
        if (!_moveMode) return;
        _moveMode = false;
        protoOverlay.style.cursor = '';
        protoDropLine.style.display = 'none';
        protoHighlight.style.opacity = '';

        if (_dropTarget && _movingEl) {
            var parent = _dropTarget.el.parentElement;
            if (_dropTarget.before) {
                parent.insertBefore(_movingEl, _dropTarget.el);
            } else {
                parent.insertBefore(_movingEl, _dropTarget.el.nextSibling);
            }
            _protoSave();
        }
        _dropTarget = null;
        _movingEl = null;
        pickedTarget = null;
        protoHighlight.style.display = 'none';
        protoActions.classList.remove('on');
        protoOverlay.classList.remove('active');
        updatePickBar();
    });

    protoOverlay.addEventListener('click', function(e) {
        if (_moveMode) return;

        if (!_addMode) {
            /* Клик выбирает блок прототипа (как раньше делала кнопка «Выбрать блок») */
            var found = _protoElementAt(e.clientX, e.clientY);
            if (!found) {
                pickedTarget = null;
                protoHighlight.style.display = 'none';
                protoActions.classList.remove('on');
                updatePickBar();
                return;
            }
            pickedTarget = {
                html:     found.candidate.outerHTML,
                selector: found.sel,
                _el:      found.candidate,
            };
            _protoShowHighlight(found.elRect, false);
            _protoShowActions(found.elRect);
            updatePickBar();
            return;
        }

        if (_addMode) {
            var overlayRect = protoOverlay.getBoundingClientRect();
            var x = e.clientX - overlayRect.left;
            var y = e.clientY - overlayRect.top;
            try {
                var iframeDoc2 = protoFrame.contentDocument || protoFrame.contentWindow.document;
                var el2 = iframeDoc2.elementFromPoint(x, y);
                if (!el2 || el2.tagName === 'HTML' || el2.tagName === 'BODY') return;
                var cand2 = el2;
                while (cand2 && cand2.tagName !== 'BODY') {
                    if (PROTO_BLOCK_TAGS.indexOf(cand2.tagName) !== -1) break;
                    cand2 = cand2.parentElement;
                }
                if (!cand2 || cand2.tagName === 'BODY') cand2 = el2;
                var targetRect2 = cand2.getBoundingClientRect();
                var before2 = y < (targetRect2.top + targetRect2.height / 2);
                var sel2 = cand2.id
                    ? '#' + cand2.id
                    : (cand2.className && typeof cand2.className === 'string'
                        ? '.' + cand2.className.trim().split(/\s+/)[0]
                        : cand2.tagName.toLowerCase());
                _addInsert = { el: cand2, before: before2, selector: sel2 };
                addHint.textContent = '✓ Место: ' + (before2 ? 'перед' : 'после') + ' ' + sel2 + ' — введи описание блока';
                addSubmit.disabled = false;
                addDesc.focus();
            } catch(err) {}
        }
    });

    /* ── Pick bar ─────────────────────────────────────────────────────────────── */
    function updatePickBar() {
        var hasRef = !!pickedRef;
        var hasTgt = !!pickedTarget;

        pickBar.classList[hasRef ? 'add' : 'remove']('on');

        if (hasRef) {
            pickSlotRef.textContent = 'Эталон: ' + pickedRef.selector;
            pickSlotRef.classList.add('set');
        } else {
            pickSlotRef.textContent = 'Эталон: не выбран';
            pickSlotRef.classList.remove('set');
        }

        if (hasTgt) {
            pickSlotTgt.textContent = 'Цель: ' + pickedTarget.selector;
            pickSlotTgt.classList.add('set');
        } else {
            pickSlotTgt.textContent = 'Цель: весь прототип';
            pickSlotTgt.classList.remove('set');
        }

        if (hasRef && hasTgt) {
            pickApplyBtn.textContent = '⇄ Трансформировать →';
            pickApplyBtn.classList.add('transform');
        } else {
            pickApplyBtn.textContent = 'Применить →';
            pickApplyBtn.classList.remove('transform');
        }

        pickApplyBtn.disabled = !hasRef;
    }

    function clearAll() {
        pickedRef = null;
        pickedTarget = null;
        protoHighlight.style.display = 'none';
        protoActions.classList.remove('on');
        pickBar.classList.remove('on');
        pickNote.value = '';
        updatePickBar();
        var ctx = browserCanvas.getContext('2d');
        if (ctx) ctx.clearRect(0, 0, browserCanvas.width, browserCanvas.height);
        drag = { active: false, sx: 0, sy: 0, ex: 0, ey: 0 };
        if (_addMode) disableAddMode();
    }

    pickCancelBtn.addEventListener('click', clearAll);
    addCancel.addEventListener('click', disableAddMode);

    addDesc.addEventListener('input', function() {
        if (_addInsert) addSubmit.disabled = !addDesc.value.trim();
    });
    addDesc.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !addSubmit.disabled) addSubmit.click();
    });

    addSubmit.addEventListener('click', async function() {
        if (!_addInsert || addSubmit.disabled) return;
        var desc = addDesc.value.trim();
        if (!desc) return;

        var posLabel = (_addInsert.before ? 'перед' : 'после') + ' элемента ' + _addInsert.selector;
        var siblingHtml = (_addInsert.el.outerHTML || '').slice(0, 400);
        var request = 'Добавь новый блок: "' + desc + '". Вставь его ' + posLabel + '. HTML соседнего элемента: ' + siblingHtml;

        addSubmit.disabled = true;
        showApplyStatus('Отправляю в LLM...', '');

        try {
            var resp = await fetch('/planning/prototype/' + projectId + '/refine', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ page_name: _protoCurrentPageName(), request: request }),
            });
            var data = await resp.json();
            if (data.result === 'ok') {
                showApplyStatus('✓ Блок добавлен', 'ok');
                disableAddMode();
                setTimeout(function() { protoFrame.contentWindow.location.reload(); }, 600);
            } else {
                showApplyStatus('Ошибка: ' + (data.error || 'неизвестная'), 'err');
                addSubmit.disabled = false;
            }
        } catch(e) {
            showApplyStatus('Ошибка: ' + e.message, 'err');
            addSubmit.disabled = false;
        }
    });

    /* ── Применить / Трансформировать ───────────────────────────────────────── */
    pickApplyBtn.addEventListener('click', async function() {
        if (!pickedRef || pickApplyBtn.disabled) return;

        var note = pickNote.value.trim();
        var isTransform = !!pickedTarget;
        var request = note || (isTransform
            ? 'Трансформировать выделенный блок прототипа в стиле эталонного блока, сохранив оригинальный контент'
            : 'Применить выделенный блок к прототипу');

        pickApplyBtn.disabled = true;
        showApplyStatus('Отправляю в LLM...', '');

        var body = {
            page_name: pageName,
            request: request,
            reference_url: browserUrlIn.value.trim() || '',
            reference_html: pickedRef.html,
            reference_css: pickedRef.css || '',
        };
        if (isTransform) {
            body.target_html = pickedTarget.html;
        }

        try {
            var resp = await fetch('/planning/prototype/' + projectId + '/refine', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            });
            var data = await resp.json();
            if (data.result === 'ok') {
                showApplyStatus(isTransform ? '✓ Трансформировано' : '✓ Применено', 'ok');
                clearAll();
                setTimeout(function() { protoFrame.contentWindow.location.reload(); }, 600);
            } else {
                showApplyStatus('Ошибка: ' + (data.error || 'неизвестная'), 'err');
                pickApplyBtn.disabled = false;
            }
        } catch(e) {
            showApplyStatus('Ошибка: ' + e.message, 'err');
            pickApplyBtn.disabled = false;
        }
    });

    /* ── Horizontal scrollbar ────────────────────────────────────────────────── */
    var _hscrollDrag = false;
    var _hscrollStartX = 0;
    var _hscrollStartLeft = 0;
    var _pageScrollWidth = 0;
    var _pageScrollX = 0;
    var _pageViewportW = 0;
    var _hscrollInFlight = false;
    var _hscrollPendingX = null;

    function updateHScrollbar(data) {
        var sw = data.scrollWidth || 0;
        var vw = data.viewportW  || 0;
        var sx = data.scrollX    || 0;
        _pageScrollWidth = sw; _pageScrollX = sx; _pageViewportW = vw;

        if (!sw || sw <= vw) { hscroll.classList.remove('on'); return; }
        hscroll.classList.add('on');

        var trackW = hscroll.offsetWidth;
        var thumbW = Math.max(30, Math.round(trackW * vw / sw));
        var maxLeft = trackW - thumbW;
        var thumbLeft = Math.round(maxLeft * sx / (sw - vw));
        hscrollThumb.style.width = thumbW + 'px';
        hscrollThumb.style.left  = thumbLeft + 'px';
    }

    function _doHScroll() {
        if (_hscrollPendingX === null || _hscrollInFlight) return;
        var targetX = _hscrollPendingX;
        _hscrollPendingX = null;
        _hscrollInFlight = true;
        fetch('/design/browser/click', {
            method: 'POST', credentials: 'include',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(Object.assign({action: 'scroll_to', scrollX: targetX, scrollY: -1}, viewDims())),
        }).then(function(r){ return r.json(); }).then(function(d) {
            if (!d.error && d.screenshot) browserImg.src = 'data:image/png;base64,' + d.screenshot;
            if (d.scrollWidth) updateHScrollbar(d);
        }).catch(function(){}).then(function() {
            _hscrollInFlight = false;
            if (_hscrollPendingX !== null) _doHScroll();
        });
    }

    hscrollThumb.addEventListener('mousedown', function(e) {
        e.preventDefault();
        _hscrollDrag = true;
        _hscrollStartX    = e.clientX;
        _hscrollStartLeft = parseInt(hscrollThumb.style.left) || 0;
    });
    document.addEventListener('mousemove', function(e) {
        if (!_hscrollDrag) return;
        var trackW = hscroll.offsetWidth;
        var thumbW = hscrollThumb.offsetWidth;
        var maxLeft = trackW - thumbW;
        var newLeft = Math.min(Math.max(0, _hscrollStartLeft + (e.clientX - _hscrollStartX)), maxLeft);
        hscrollThumb.style.left = newLeft + 'px';
        _hscrollPendingX = Math.round((_pageScrollWidth - _pageViewportW) * newLeft / maxLeft);
        _doHScroll();
    });
    document.addEventListener('mouseup', function() { _hscrollDrag = false; });

    /* ── Browser URL history ─────────────────────────────────────────────────── */
    var _urlHistoryCache = null;

    async function _urlHistoryLoad() {
        if (_urlHistoryCache) return _urlHistoryCache;
        try {
            var resp = await fetch('/design/browser/history/' + projectId, { credentials: 'include' });
            var data = await resp.json();
            _urlHistoryCache = data.result || [];
        } catch(e) { _urlHistoryCache = []; }
        return _urlHistoryCache;
    }

    function _urlHistoryInvalidate() { _urlHistoryCache = null; }

    async function _urlHistoryShow() {
        var urls = await _urlHistoryLoad();
        if (!urls.length) return;
        urlHistoryDrop.innerHTML = '';
        var typed = browserUrlIn.value.trim().toLowerCase();
        var filtered = typed ? urls.filter(function(u) { return u.toLowerCase().includes(typed); }) : urls;
        if (!filtered.length) { urlHistoryDrop.classList.remove('on'); return; }
        filtered.forEach(function(url) {
            var d = document.createElement('div');
            d.textContent = url;
            d.title = url;
            d.addEventListener('mousedown', function(e) {
                e.preventDefault();
                browserUrlIn.value = url;
                urlHistoryDrop.classList.remove('on');
                browserGoBtn.click();
            });
            urlHistoryDrop.appendChild(d);
        });
        urlHistoryDrop.classList.add('on');
    }

    browserUrlIn.addEventListener('focus', _urlHistoryShow);
    browserUrlIn.addEventListener('input', _urlHistoryShow);
    browserUrlIn.addEventListener('blur', function() {
        setTimeout(function() { urlHistoryDrop.classList.remove('on'); }, 150);
    });

    /* ── Browser navigation ──────────────────────────────────────────────────── */
    function showLoader(on) { browserLoader.classList[on ? 'add' : 'remove']('on'); }

    async function browserNavigate(url) {
        urlHistoryDrop.classList.remove('on');
        showLoader(true);
        try {
            var resp = await fetch('/design/browser/navigate', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(Object.assign({url: url, project_id: projectId}, viewDims())),
            });
            var data = await resp.json();
            if (data.error) { showApplyStatus('Ошибка: ' + data.error, 'err'); return; }
            browserImg.src = 'data:image/png;base64,' + data.screenshot;
            browserUrlIn.value = data.url || url;
            browserTitle.textContent = data.title || '';
            updateHScrollbar(data);
            _urlHistoryInvalidate();
        } catch(e) {
            showApplyStatus('Ошибка: ' + e.message, 'err');
        } finally {
            showLoader(false);
        }
    }

    browserGoBtn.addEventListener('click', function () {
        var url = browserUrlIn.value.trim();
        if (url) browserNavigate(url);
    });
    browserUrlIn.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') browserGoBtn.click();
    });
    browserBackBtn.addEventListener('click', async function() {
        showLoader(true);
        try {
            var resp = await fetch('/design/browser/click', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(Object.assign({action: 'back'}, viewDims())),
            });
            var data = await resp.json();
            if (!data.error) {
                browserImg.src = 'data:image/png;base64,' + data.screenshot;
                browserUrlIn.value = data.url || browserUrlIn.value;
                browserTitle.textContent = data.title || '';
            }
        } catch(e) {} finally { showLoader(false); }
    });

    /* ── Canvas drag-выделение ───────────────────────────────────────────────── */
    function viewDims() {
        var r = browserView.getBoundingClientRect();
        return { viewW: Math.round(r.width), viewH: Math.round(r.height) };
    }

    function updateScale() {
        var rect = browserView.getBoundingClientRect();
        if (!rect.width || !browserImg.naturalWidth) return;
        var naturalMatchesView = (
            Math.abs(browserImg.naturalWidth  - rect.width)  < 2 &&
            Math.abs(browserImg.naturalHeight - rect.height) < 2
        );
        if (naturalMatchesView) {
            browserScaleX = 1; browserScaleY = 1;
            browserDisplayW = rect.width; browserDisplayH = rect.height;
            return;
        }
        var imgAspect  = browserImg.naturalWidth / browserImg.naturalHeight;
        var viewAspect = rect.width / rect.height;
        if (imgAspect >= viewAspect) {
            browserDisplayW = rect.width;
            browserDisplayH = rect.width / imgAspect;
        } else {
            browserDisplayH = rect.height;
            browserDisplayW = rect.height * imgAspect;
        }
        browserScaleX = browserImg.naturalWidth  / browserDisplayW;
        browserScaleY = browserImg.naturalHeight / browserDisplayH;
    }

    function resizeCanvas() {
        var rect = browserView.getBoundingClientRect();
        if (!rect.width) return;
        browserCanvas.width  = rect.width;
        browserCanvas.height = rect.height;
        updateScale();
        drawSelection();
    }
    window.addEventListener('resize', resizeCanvas);
    browserImg.addEventListener('load', function() {
        browserLoaded = true;
        drag = { active: false, sx: 0, sy: 0, ex: 0, ey: 0 };
        resizeCanvas();
    });
    if (window.ResizeObserver) {
        new ResizeObserver(function() {
            if (!drag.active) resizeCanvas();
        }).observe(browserView);
    }

    function canvasPos(e) {
        var rect = browserCanvas.getBoundingClientRect();
        return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }

    function drawSelection() {
        var ctx = browserCanvas.getContext('2d');
        ctx.clearRect(0, 0, browserCanvas.width, browserCanvas.height);
        var x = Math.min(drag.sx, drag.ex), y = Math.min(drag.sy, drag.ey);
        var w = Math.abs(drag.ex - drag.sx), h = Math.abs(drag.ey - drag.sy);
        if (!w || !h) return;
        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth   = 2;
        ctx.setLineDash([4, 3]);
        ctx.strokeRect(x, y, w, h);
        ctx.fillStyle   = 'rgba(59,130,246,0.12)';
        ctx.fillRect(x, y, w, h);
    }

    /* ── Wheel scroll ────────────────────────────────────────────────────────── */
    var _scrollInFlight = false;
    var _scrollPendingX = 0;
    var _scrollPendingY = 0;

    async function _sendScroll() {
        if (_scrollInFlight) return;
        var dx = Math.round(_scrollPendingX);
        var dy = Math.round(_scrollPendingY);
        if (!dx && !dy) return;
        _scrollPendingX = 0;
        _scrollPendingY = 0;
        _scrollInFlight = true;
        try {
            var resp = await fetch('/design/browser/click', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(Object.assign({action: 'scroll', deltaX: dx, deltaY: dy}, viewDims())),
            });
            var data = await resp.json();
            if (!data.error && data.screenshot) {
                browserImg.src = 'data:image/png;base64,' + data.screenshot;
                updateHScrollbar(data);
            }
        } catch(e2) {}
        _scrollInFlight = false;
        if (_scrollPendingX || _scrollPendingY) _sendScroll();
    }

    browserCanvas.addEventListener('wheel', function(e) {
        e.preventDefault();
        if (!browserLoaded) return;
        if (e.shiftKey) {
            _scrollPendingX += e.deltaY * 4;
        } else {
            _scrollPendingX += e.deltaX * 3;
            _scrollPendingY += e.deltaY * 3;
        }
        _sendScroll();
    }, {passive: false});

    browserCanvas.addEventListener('mousedown', function(e) {
        if (!browserLoaded) return;
        var p = canvasPos(e);
        drag = { active: true, sx: p.x, sy: p.y, ex: p.x, ey: p.y };
    });
    browserCanvas.addEventListener('mousemove', function(e) {
        if (!drag.active) return;
        var p = canvasPos(e);
        drag.ex = p.x; drag.ey = p.y;
        drawSelection();
    });
    document.addEventListener('mouseup', async function(e) {
        if (!drag.active) return;
        drag.active = false;
        var _cr = browserCanvas.getBoundingClientRect();
        drag.ex = Math.min(Math.max(0, e.clientX - _cr.left), _cr.width);
        drag.ey = Math.min(Math.max(0, e.clientY - _cr.top),  _cr.height);
        drawSelection();

        var w = Math.abs(drag.ex - drag.sx), h = Math.abs(drag.ey - drag.sy);

        function toImgX(cx) { return Math.min(Math.max(0, Math.round(cx * browserScaleX)), browserImg.naturalWidth  - 1); }
        function toImgY(cy) { return Math.min(Math.max(0, Math.round(cy * browserScaleY)), browserImg.naturalHeight - 1); }

        if (w < 10 || h < 10) {
            var cx = toImgX(drag.sx);
            var cy = toImgY(drag.sy);
            showLoader(true);
            try {
                var resp = await fetch('/design/browser/click', {
                    method: 'POST', credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(Object.assign({x: cx, y: cy}, viewDims())),
                });
                var data = await resp.json();
                if (!data.error) {
                    browserImg.src = 'data:image/png;base64,' + data.screenshot;
                    browserUrlIn.value = data.url || browserUrlIn.value;
                    browserTitle.textContent = data.title || '';
                    updateHScrollbar(data);
                }
            } catch(err) {} finally { showLoader(false); }
            return;
        }

        var rx = toImgX(Math.min(drag.sx, drag.ex));
        var ry = toImgY(Math.min(drag.sy, drag.ey));
        var rw = Math.round(w * browserScaleX);
        var rh = Math.round(h * browserScaleY);

        showLoader(true);
        try {
            var resp2 = await fetch('/design/browser/pick', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({x: rx, y: ry, w: rw, h: rh}),
            });
            var el = await resp2.json();
            if (el.error) {
                showApplyStatus('Ошибка: ' + el.error, 'err');
            } else {
                pickedRef = {
                    html: el.html || '',
                    css: (el.css || '') + '\n' + (el.inline_style || ''),
                    selector: el.selector || el.tag || '?',
                };
                updatePickBar();
            }
        } catch(e) {
            showApplyStatus('Ошибка: ' + e.message, 'err');
        } finally {
            showLoader(false);
        }
    });

    /* ── Toast ─────────────────────────────────────────────────────────────────── */
    var _statusTimer = null;
    var _statusCloseBtn = document.createElement('button');
    _statusCloseBtn.id = '__rw_apply_status_close';
    _statusCloseBtn.textContent = '✕';
    _statusCloseBtn.addEventListener('click', function() { applyStatus.className = ''; });
    applyStatus.appendChild(_statusCloseBtn);

    var _statusMsgEl = document.createElement('span');
    applyStatus.insertBefore(_statusMsgEl, _statusCloseBtn);

    var _statusCopyBtn = document.createElement('button');
    _statusCopyBtn.id = '__rw_apply_status_copy';
    _statusCopyBtn.textContent = 'Копировать';
    _statusCopyBtn.addEventListener('click', function() {
        navigator.clipboard.writeText(_statusMsgEl.textContent).then(function() {
            _statusCopyBtn.textContent = '✓ Скопировано';
            setTimeout(function() { _statusCopyBtn.textContent = 'Копировать'; }, 1500);
        }).catch(function() {
            var ta = document.createElement('textarea');
            ta.value = _statusMsgEl.textContent;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            _statusCopyBtn.textContent = '✓ Скопировано';
            setTimeout(function() { _statusCopyBtn.textContent = 'Копировать'; }, 1500);
        });
    });
    applyStatus.appendChild(document.createElement('br'));
    applyStatus.appendChild(_statusCopyBtn);

    function showApplyStatus(msg, cls) {
        _statusMsgEl.textContent = msg;
        applyStatus.className = 'on' + (cls ? ' ' + cls : '');
        clearTimeout(_statusTimer);
        if (cls === 'ok') {
            _statusTimer = setTimeout(function() { applyStatus.className = ''; }, 5000);
        }
    }
})();
