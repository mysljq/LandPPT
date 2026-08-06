// 套件管理页 — 全局模板套件库（module）
const state = {
    suites: [],
    currentPage: 1,
    pageSize: 6,
    totalPages: 1,
    totalCount: 0,
    currentSearch: '',
    templates: [],
    generatedSuite: null,
    previewData: null,
    currentPreviewTab: 'cover',
};

const dom = {};
let suiteNameInputTimeout = null;

document.addEventListener('DOMContentLoaded', () => {
    cacheDom();
    bindEvents();
    loadSuites(1);
});

function cacheDom() {
    dom.grid = document.getElementById('suitesGrid');
    dom.loading = document.getElementById('loadingIndicator');
    dom.searchInput = document.getElementById('searchInput');
    dom.refreshBtn = document.getElementById('refreshBtn');
    dom.paginationInfo = document.getElementById('paginationInfo');
    dom.pageNumbers = document.getElementById('pageNumbers');
    dom.prevPageBtn = document.getElementById('prevPageBtn');
    dom.nextPageBtn = document.getElementById('nextPageBtn');
    dom.pageSizeSelect = document.getElementById('pageSizeSelect');

    dom.generateModal = document.getElementById('generateModal');
    dom.genStep1 = document.getElementById('genStep1');
    dom.genProgress = document.getElementById('genProgress');
    dom.genComplete = document.getElementById('genComplete');
    dom.templateSelect = document.getElementById('templateSelect');
    dom.templatePreviewWrap = document.getElementById('templatePreviewWrap');
    dom.templatePreviewBox = document.getElementById('templatePreviewBox');
    dom.templatePreviewFrame = document.getElementById('templatePreviewFrame');
    dom.creativitySlider = document.getElementById('creativitySlider');
    dom.creativityLabel = document.getElementById('creativityLabel');
    dom.suiteNameInput = document.getElementById('suiteNameInput');
    dom.genPreviewBox = document.getElementById('genPreviewBox');
    dom.genPreviewFrame = document.getElementById('genPreviewFrame');
    dom.saveSuiteBtn = document.getElementById('saveSuiteBtn');
    dom.saveSuiteStatus = document.getElementById('saveSuiteStatus');

    dom.previewModal = document.getElementById('previewModal');
    dom.previewTitle = document.getElementById('previewTitle');
    dom.previewBox = document.getElementById('previewBox');
    dom.previewFrame = document.getElementById('previewFrame');
}

function bindEvents() {
    dom.searchInput.addEventListener('input', () => {
        clearTimeout(suiteNameInputTimeout);
        suiteNameInputTimeout = setTimeout(() => {
            state.currentSearch = dom.searchInput.value.trim();
            state.currentPage = 1;
            loadSuites(1);
        }, 300);
    });
    dom.refreshBtn.addEventListener('click', () => loadSuites(state.currentPage));
    dom.prevPageBtn.addEventListener('click', () => changePage(state.currentPage - 1));
    dom.nextPageBtn.addEventListener('click', () => changePage(state.currentPage + 1));
    dom.pageSizeSelect.addEventListener('change', () => {
        state.pageSize = parseInt(dom.pageSizeSelect.value, 10) || 6;
        state.currentPage = 1;
        loadSuites(1);
    });

    document.getElementById('generateSuiteFromTemplateBtn').addEventListener('click', openGenerateModal);
    document.getElementById('closeGenerateModal').addEventListener('click', closeGenerateModal);
    document.getElementById('startGenerateBtn').addEventListener('click', startGenerateSuite);
    document.getElementById('saveSuiteBtn').addEventListener('click', saveSuiteToLibrary);
    document.getElementById('closeCompleteBtn').addEventListener('click', closeGenerateModal);
    document.getElementById('closePreviewModal').addEventListener('click', closePreviewModal);

    dom.creativitySlider.addEventListener('input', updateCreativityLabel);
    dom.suiteNameInput.addEventListener('input', () => {
        const s = dom.saveSuiteStatus;
        if (s) s.textContent = '';
    });

    // 点击遮罩层关闭弹窗
    document.addEventListener('click', (e) => {
        if (e.target.classList && e.target.classList.contains('modal')) {
            e.target.style.display = 'none';
            if (e.target === dom.previewModal) state.previewData = null;
        }
    });
    // Esc 关闭弹窗
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        if (dom.generateModal && dom.generateModal.style.display !== 'none') closeGenerateModal();
        if (dom.previewModal && dom.previewModal.style.display !== 'none') closePreviewModal();
    });
}

// ---------------- 列表 ----------------

async function api(path, options = {}) {
    const resp = await fetch(path, {
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
    });
    if (!resp.ok) {
        let detail = `HTTP ${resp.status}`;
        try {
            const data = await resp.json();
            detail = data.detail || data.message || detail;
        } catch (_) {}
        throw new Error(detail);
    }
    return resp.json();
}

async function loadSuites(page) {
    showLoading(true);
    try {
        const params = new URLSearchParams({ page: String(page), page_size: String(state.pageSize) });
        if (state.currentSearch) params.append('search', state.currentSearch);
        const data = await api(`/api/template-suites?${params}`);
        state.suites = data.suites || [];
        state.currentPage = data.pagination?.current_page || page;
        state.totalPages = data.pagination?.total_pages || 1;
        state.totalCount = data.pagination?.total_count || 0;
        renderSuites();
        updatePagination();
    } catch (error) {
        dom.grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:48px; color:var(--text-secondary);">加载失败：${error.message}</div>`;
    } finally {
        showLoading(false);
    }
}

function renderSuites() {
    if (!state.suites.length) {
        dom.grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:48px; color:var(--text-secondary);">暂无套件。点击右上角"从模板生成套件"创建。</div>`;
        return;
    }
    dom.grid.innerHTML = state.suites.map(buildSuiteCard).join('');
}

function buildSuiteCard(suite) {
    const tags = (suite.tags || []).map(t => `<span class="tag-chip">${t}</span>`).join('');
    const templateName = suite.template_name || '独立套件';
    return `
    <div class="suite-card">
        <div class="suite-card-preview" onclick="window.suiteMgmtOpenPreview(${suite.id}, '${suite.suite_name}')">
            <iframe srcdoc="${escapeHtml('<div style="padding:40px;color:#666;text-align:center;font-size:14px;">点击预览</div>')}" loading="lazy"></iframe>
        </div>
        <div class="suite-card-info">
            <div class="suite-card-name">
                <span title="${escapeHtml(suite.suite_name)}">${escapeHtml(suite.suite_name)}</span>
            </div>
            <div class="suite-card-desc">${escapeHtml(suite.description || '模板套件：封面 / 过渡页 / 内容页页头页脚')}</div>
            <div class="suite-card-meta">
                <span>来源：${escapeHtml(templateName)}</span>
                <span>使用 ${suite.usage_count || 0} 次</span>
                ${tags ? `<span>${tags}</span>` : ''}
            </div>
        </div>
        <div class="suite-card-actions">
            <button class="btn btn-sm btn-outline-primary" onclick="window.suiteMgmtOpenPreview(${suite.id}, '${suite.suite_name}')">👁️ 预览</button>
            <button class="btn btn-sm btn-outline" onclick="window.suiteMgmtDuplicate(${suite.id})">复制</button>
            <button class="btn btn-sm btn-outline" onclick="window.suiteMgmtDelete(${suite.id})">删除</button>
        </div>
    </div>`;
}

function escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function updatePagination() {
    dom.paginationInfo.textContent = `显示第 ${(state.currentPage - 1) * state.pageSize + 1}-${Math.min(state.currentPage * state.pageSize, state.totalCount)} 项，共 ${state.totalCount} 项`;
    dom.prevPageBtn.disabled = state.currentPage <= 1;
    dom.nextPageBtn.disabled = state.currentPage >= state.totalPages;
    const pages = [];
    for (let i = 1; i <= state.totalPages; i++) pages.push(i);
    dom.pageNumbers.innerHTML = pages.map(p =>
        `<button class="page-btn ${p === state.currentPage ? 'active' : ''}" onclick="window.suiteMgmtChangePage(${p})" style="min-width:32px;height:32px;padding:4px 8px;border:1px solid var(--border-color,#e5e7eb);background:#fff;border-radius:6px;cursor:pointer;font-size:0.8rem;">${p}</button>`
    ).join('');
}

window.suiteMgmtChangePage = (p) => changePage(p);
function changePage(p) {
    if (p < 1 || p > state.totalPages || p === state.currentPage) return;
    loadSuites(p);
}

function showLoading(show) {
    dom.loading.style.display = show ? 'block' : 'none';
    dom.grid.style.display = show ? 'none' : 'grid';
}

// ---------------- 从模板生成 ----------------

async function openGenerateModal() {
    state.generatedSuite = null;
    dom.genStep1.style.display = 'block';
    dom.genProgress.style.display = 'none';
    dom.genComplete.style.display = 'none';
    dom.saveSuiteStatus.textContent = '';
    dom.generateModal.style.display = 'flex';
    updateCreativityLabel();
    try {
        await loadTemplatesForSelect();
    } catch (_) {}
}

async function loadTemplatesForSelect() {
    const data = await api('/api/global-master-templates/?active_only=true&page=1&page_size=100');
    state.templates = data.templates || [];
    dom.templateSelect.innerHTML = '<option value="">请选择模板</option>' + state.templates.map(t =>
        `<option value="${t.id}">${escapeHtml(t.template_name)}</option>`).join('');
    // 用 onchange 赋值避免每次打开弹窗重复绑定监听
    dom.templateSelect.onchange = previewSelectedTemplate;
}

// 以 16:9 等比展示 1280x720 页面：iframe 保持真实尺寸，按容器宽度缩放。
// 同时限制高度不超过视口的 68%，避免宽屏下预览超出弹窗高度被裁切。
function fitPreview(frame, box) {
    if (!frame || !box) return;
    const w = box.clientWidth || 800;
    const hCap = ((window.innerHeight || 720) * 0.68) / 720;
    const scale = Math.min(w / 1280, hCap);
    frame.style.transform = `scale(${scale})`;
    // transform-origin 已在样式里设 top left
}

function setPreviewDoc(frame, box, html) {
    if (!frame) return;
    frame.onload = () => fitPreview(frame, box);
    frame.srcdoc = html || '';
    // srcdoc 可能不触发 onload（同源空内容），兜底立即缩放
    setTimeout(() => fitPreview(frame, box), 50);
}

async function previewSelectedTemplate() {
    const templateId = parseInt(dom.templateSelect.value, 10);
    if (!templateId || !dom.templatePreviewWrap) {
        if (dom.templatePreviewWrap) dom.templatePreviewWrap.style.display = 'none';
        return;
    }
    dom.templatePreviewWrap.style.display = 'block';
    setPreviewDoc(dom.templatePreviewFrame, dom.templatePreviewBox,
        '<div style="padding:24px;color:#94a3b8;text-align:center;font-size:14px;">模板预览加载中...</div>');
    try {
        const detail = await api(`/api/global-master-templates/${templateId}`);
        const html = detail.html_template || detail.template?.html_template || '';
        setPreviewDoc(dom.templatePreviewFrame, dom.templatePreviewBox, html);
    } catch (_) {
        setPreviewDoc(dom.templatePreviewFrame, dom.templatePreviewBox,
            '<div style="padding:24px;color:#94a3b8;text-align:center;font-size:14px;">模板预览加载失败</div>');
    }
}

function updateCreativityLabel() {
    const val = parseInt(dom.creativitySlider.value, 10) || 5;
    let text = String(val);
    if (val <= 1) text += ' · 严格遵循母版';
    else if (val <= 3) text += ' · 以母版为主';
    else if (val <= 6) text += ' · 母版与创意平衡';
    else if (val <= 8) text += ' · 大胆创意';
    else text += ' · 最具创意';
    dom.creativityLabel.textContent = text;
}

async function startGenerateSuite() {
    const templateId = parseInt(dom.templateSelect.value, 10);
    if (!templateId) {
        alert('请先选择模板');
        return;
    }
    const creativity = parseInt(dom.creativitySlider.value, 10) || 5;
    const statusEl = document.getElementById('genProgressStatus');
    const elapsedEl = document.getElementById('genProgressElapsed');
    const startBtn = document.getElementById('startGenerateBtn');
    if (startBtn) startBtn.disabled = true;
    dom.genStep1.style.display = 'none';
    dom.genProgress.style.display = 'block';
    dom.saveSuiteStatus.textContent = '';
    if (statusEl) statusEl.textContent = '正在提交生成请求...';

    // 已耗时计时器：生成期间持续刷新，让用户明确知道任务仍在运行。
    const genStart = Date.now();
    const timer = setInterval(() => {
        const sec = Math.floor((Date.now() - genStart) / 1000);
        if (elapsedEl) elapsedEl.textContent = `已耗时 ${sec} 秒`;
        if (sec === 90 && statusEl) statusEl.textContent = '生成耗时较长，请查看后端控制台日志确认 LLM 调用是否正常...';
    }, 1000);
    const finish = () => clearInterval(timer);

    try {
        const resp = await fetch('/api/template-suites/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ template_id: templateId, creativity, stream: true }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || err.message || `HTTP ${resp.status}`);
        }

        let data;
        if (resp.headers.get('content-type')?.includes('text/event-stream')) {
            data = await readSuiteGenerateStream(resp, statusEl);
        } else {
            data = await resp.json();
        }

        if (data && data.success === false) {
            throw new Error(data.message || '生成失败');
        }
        if (!data || !data.suite) {
            throw new Error('生成未返回套件数据');
        }
        state.generatedSuite = data.suite;
        dom.suiteNameInput.value = state.generatedSuite.suite_name || '';
        await renderGenPreview('cover');
        finish();
        dom.genProgress.style.display = 'none';
        dom.genComplete.style.display = 'block';
    } catch (error) {
        finish();
        console.error('Suite generation error:', error);
        dom.genProgress.style.display = 'none';
        dom.genStep1.style.display = 'block';
        alert(`生成失败：${error.message}`);
    } finally {
        if (startBtn) startBtn.disabled = false;
    }
}

// 读取 SSE 流，逐个事件刷新状态文本，返回 complete 事件里的 {success, suite, message}。
async function readSuiteGenerateStream(resp, statusEl) {
    const reader = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let result = null;
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value || new Uint8Array(), { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            let event;
            try {
                event = JSON.parse(line.slice(6));
            } catch (_) {
                continue;
            }
            if (event.type === 'status' && statusEl) {
                statusEl.textContent = event.message || statusEl.textContent;
            }
            if (event.type === 'complete') {
                result = { success: true, suite: event.suite, message: event.message };
            }
            if (event.type === 'error') {
                throw new Error(event.message || '生成失败');
            }
        }
    }
    if (!result) throw new Error('生成未返回完成事件');
    return result;
}

async function renderGenPreview(tab) {
    state.currentPreviewTab = tab;
    const s = state.generatedSuite;
    if (!s) return;
    let html = '';
    if (tab === 'cover') html = s.cover;
    else if (tab === 'transition') html = s.transition;
    else if (tab === 'catalog') html = s.catalog || '';
    else if (tab === 'ending') html = s.ending || '';
    else html = wrapContentPreview(s.header_footer);
    setPreviewDoc(dom.genPreviewFrame, dom.genPreviewBox, html);
    highlightTab('genComplete');
}

function wrapContentPreview(hf) {
    return `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>html,body{margin:0;padding:0;width:1280px;height:720px;overflow:hidden}</style></head><body>${hf || ''}</body></html>`;
}

function highlightTab(scope) {
    document.querySelectorAll(`#${scope} .suite-tab-btn`).forEach(btn => {
        btn.classList.toggle('active', btn.dataset.suiteTab === state.currentPreviewTab);
    });
}

// 生成弹窗内的 tab：只渲染刚生成的套件（不要污染列表预览）。
window.suiteMgmtShowGenTab = (tab) => {
    state.currentPreviewTab = tab;
    renderGenPreview(tab);
};

// 预览弹窗内的 tab：只渲染库中套件（不受 state.generatedSuite 残留影响）。
window.suiteMgmtShowLibTab = (tab) => {
    state.currentPreviewTab = tab;
    showPreviewTab(tab);
};

async function saveSuiteToLibrary() {
    const s = state.generatedSuite;
    if (!s) {
        alert('没有可保存的套件');
        return;
    }
    const name = (dom.suiteNameInput.value || '').trim() || s.suite_name || '未命名套件';
    dom.saveSuiteBtn.disabled = true;
    dom.saveSuiteStatus.textContent = '保存中...';
    try {
        await api('/api/template-suites', {
            method: 'POST',
            body: JSON.stringify({
                suite_name: name,
                description: s.description || '',
                cover: s.cover,
                transition: s.transition,
                catalog: s.catalog || '',
                ending: s.ending || '',
                header_footer: s.header_footer,
                design_tokens: s.design_tokens || '',
                template_id: s.template_id || null,
                template_hash: s.template_hash || null,
                template_name: s.template_name || null,
                tags: s.tags || ['AI生成'],
            }),
        });
        dom.saveSuiteStatus.textContent = '✅ 已保存到套件库';
        loadSuites(1);
    } catch (error) {
        dom.saveSuiteStatus.textContent = `❌ 保存失败：${error.message}`;
    } finally {
        dom.saveSuiteBtn.disabled = false;
    }
}

function closeGenerateModal() {
    dom.generateModal.style.display = 'none';
    // 关闭生成弹窗后清掉刚生成的套件状态，避免干扰之后预览列表中的套件。
    state.generatedSuite = null;
}

// ---------------- 预览库中套件 ----------------

window.suiteMgmtOpenPreview = async (id, name) => {
    dom.previewTitle.textContent = `套件预览 - ${name || '套件'}`;
    dom.previewModal.style.display = 'flex';
    try {
        const data = await api(`/api/template-suites/${id}/preview`);
        state.previewData = data.preview;
        showPreviewTab('cover');
    } catch (error) {
        alert(`预览失败：${error.message}`);
    }
};

function showPreviewTab(tab) {
    if (!state.previewData) return;
    state.currentPreviewTab = tab;
    const html = state.previewData[tab] || '';
    setPreviewDoc(dom.previewFrame, dom.previewBox, html);
    highlightTab('previewModal');
}

function closePreviewModal() {
    dom.previewModal.style.display = 'none';
    state.previewData = null;
}

// ---------------- 复制 / 删除 ----------------

window.suiteMgmtDuplicate = async (id) => {
    try {
        await api(`/api/template-suites/${id}/duplicate`, { method: 'POST' });
        loadSuites(state.currentPage);
    } catch (error) {
        alert(`复制失败：${error.message}`);
    }
};

window.suiteMgmtDelete = async (id) => {
    if (!confirm('确定删除该套件？')) return;
    try {
        await api(`/api/template-suites/${id}`, { method: 'DELETE' });
        loadSuites(state.currentPage);
    } catch (error) {
        alert(`删除失败：${error.message}`);
    }
};
