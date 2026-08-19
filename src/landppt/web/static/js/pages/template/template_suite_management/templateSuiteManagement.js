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
    imageGeneratedSuite: null,   // 基于AI读图生成的套件
    imageFiles: {},              // 已选择的上传截图：part -> File
    previewSuiteId: null,        // 当前预览的库中套件 id
    editPart: null,              // 编辑器正在编辑的套件部分（cover/transition/catalog/ending/header_footer）
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

    dom.imageGenerateModal = document.getElementById('imageGenerateModal');
    dom.imgGenUpload = document.getElementById('imgGenUpload');
    dom.imgGenProgress = document.getElementById('imgGenProgress');
    dom.imgGenComplete = document.getElementById('imgGenComplete');
    dom.imgGenStatus = document.getElementById('imgGenStatus');
    dom.imgGenElapsed = document.getElementById('imgGenElapsed');
    dom.imgUploadGrid = document.getElementById('imgUploadGrid');
    dom.imgCreativitySlider = document.getElementById('imgCreativitySlider');
    dom.imgCreativityLabel = document.getElementById('imgCreativityLabel');
    dom.imgPreviewBox = document.getElementById('imgPreviewBox');
    dom.imgPreviewFrame = document.getElementById('imgPreviewFrame');
    dom.imgSuiteNameInput = document.getElementById('imgSuiteNameInput');
    dom.imgSaveStatus = document.getElementById('imgSaveStatus');
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
    document.getElementById('generateSuiteFromImagesBtn').addEventListener('click', openImageGenerateModal);
    document.getElementById('closeImageGenerateModal').addEventListener('click', closeImageGenerateModal);

    dom.creativitySlider.addEventListener('input', updateCreativityLabel);
    dom.suiteNameInput.addEventListener('input', () => {
        const s = dom.saveSuiteStatus;
        if (s) s.textContent = '';
    });

    // 点击遮罩层关闭弹窗（「从模板生成套件」弹窗除外：生成过程/表单填写不应误关闭，需用 ✕ 或「关闭」按钮）
    document.addEventListener('click', (e) => {
        if (e.target.classList && e.target.classList.contains('modal') && e.target !== dom.generateModal) {
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

// 套件卡片封面预览：把 cover HTML 的槽位填上示例文字，作为卡片缩略图（参考模板管理卡片）。
function _fillCardPreviewHtml(html) {
    if (!html || !html.trim()) {
        return '<div style="padding:40px;color:#94a3b8;font-size:14px;text-align:center;">暂无封面</div>';
    }
    let h = html;
    h = h.replace(/\{\{\s*cover_title\s*\}\}/g, '示例标题');
    h = h.replace(/\{\{\s*cover_subtitle\s*\}\}/g, '示例副标题');
    h = h.replace(/\{\{\s*cover_extra\s*\}\}/g, '');
    // 其余残留槽位替换为空，避免卡片上出现原始 {{...}}
    h = h.replace(/\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}/g, '');
    return h;
}

function buildSuiteCard(suite) {
    const tags = (suite.tags || []).map(t => `<span class="tag-chip">${t}</span>`).join('');
    const templateName = suite.template_name || '独立套件';
    const coverHtml = _fillCardPreviewHtml(suite.cover);
    return `
    <div class="suite-card">
        <div class="suite-card-preview" onclick="window.suiteMgmtOpenPreview(${suite.id}, '${suite.suite_name}')">
            <iframe srcdoc="${escapeHtml(coverHtml)}" loading="lazy"></iframe>
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
    if (state.editPart) {
        // 编辑器打开时：切换 tab 也切换编辑目标（重新加载该类型源码）
        openSuiteEditor();
    } else {
        showPreviewTab(tab);
    }
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
    state.previewSuiteId = id;
    state.editPart = null;
    dom.previewModal.style.display = 'flex';
    closeSuiteEditor();
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
    state.previewSuiteId = null;
    state.editPart = null;
    const area = document.getElementById('suiteEditorArea');
    if (area) area.style.display = 'none';
    const previewBox = document.getElementById('previewBox');
    if (previewBox) previewBox.style.display = 'block';
    const btn = document.getElementById('editSuiteBtn');
    if (btn) btn.textContent = '✏️ 编辑当前页面';
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

// ---------------- 基于AI读图生成套件 ----------------

const IMAGE_PART_LABELS = {
    cover: '封面页',
    transition: '过渡页',
    catalog: '目录页',
    ending: '结尾页',
    content: '内容页',
};

function openImageGenerateModal() {
    if (!dom.imageGenerateModal) return;
    state.imageGeneratedSuite = null;
    state.imageFiles = {};
    dom.imgGenUpload.style.display = 'block';
    dom.imgGenProgress.style.display = 'none';
    dom.imgGenComplete.style.display = 'none';
    if (dom.imgSaveStatus) dom.imgSaveStatus.textContent = '';
    renderImageUploadSlots();
    updateImgCreativityLabel();
    dom.imageGenerateModal.style.display = 'flex';
}

function closeImageGenerateModal() {
    if (!dom.imageGenerateModal) return;
    dom.imageGenerateModal.style.display = 'none';
    state.imageGeneratedSuite = null;
    state.imageFiles = {};
}

function renderImageUploadSlots() {
    const grid = dom.imgUploadGrid;
    if (!grid) return;
    grid.innerHTML = Object.entries(IMAGE_PART_LABELS).map(([part, label]) => `
        <div style="border:1px solid var(--border-color,#e5e7eb); border-radius:10px; overflow:hidden; background:#fff;">
            <div style="padding:8px 10px; font-size:0.8rem; font-weight:600; color:var(--text-secondary); display:flex; justify-content:space-between; align-items:center;">
                <span>${label}</span>
                <button type="button" onclick="clearImageUpload('${part}')" id="imgClear_${part}"
                    style="display:none; background:none; border:none; color:#ef4444; cursor:pointer; font-size:0.78rem;">移除</button>
            </div>
            <label id="imgSlot_${part}" for="imgFile_${part}"
                style="display:block; height:90px; background:#f8fafc; cursor:pointer; position:relative; overflow:hidden;">
                <div id="imgPlaceholder_${part}" style="height:100%; display:flex; align-items:center; justify-content:center; color:#94a3b8; font-size:0.75rem;">点击上传</div>
                <img id="imgThumb_${part}" style="display:none; width:100%; height:100%; object-fit:contain;" alt="">
            </label>
            <input type="file" id="imgFile_${part}" accept="image/*" style="display:none;"
                onchange="handleImageFileSelected('${part}', this)">
        </div>
    `).join('');
}

function handleImageFileSelected(part, input) {
    const file = input && input.files && input.files[0];
    if (!file) return;
    state.imageFiles[part] = file;
    const thumb = document.getElementById(`imgThumb_${part}`);
    const ph = document.getElementById(`imgPlaceholder_${part}`);
    const clearBtn = document.getElementById(`imgClear_${part}`);
    if (thumb && ph) {
        thumb.src = URL.createObjectURL(file);
        thumb.style.display = 'block';
        ph.style.display = 'none';
    }
    if (clearBtn) clearBtn.style.display = 'inline-block';
}

function clearImageUpload(part) {
    delete state.imageFiles[part];
    const input = document.getElementById(`imgFile_${part}`);
    if (input) input.value = '';
    const thumb = document.getElementById(`imgThumb_${part}`);
    const ph = document.getElementById(`imgPlaceholder_${part}`);
    const clearBtn = document.getElementById(`imgClear_${part}`);
    if (thumb) { thumb.style.display = 'none'; thumb.src = ''; }
    if (ph) ph.style.display = 'flex';
    if (clearBtn) clearBtn.style.display = 'none';
}

function updateImgCreativityLabel() {
    const slider = dom.imgCreativitySlider;
    const label = dom.imgCreativityLabel;
    if (!slider || !label) return;
    const val = parseInt(slider.value, 10);
    let text = String(val);
    if (val <= 1) text += ' · 严格复刻截图';
    else if (val <= 3) text += ' · 以截图为主';
    else if (val <= 6) text += ' · 截图与创意平衡';
    else if (val <= 8) text += ' · 大胆创意';
    else text += ' · 最具创意';
    label.textContent = text;
}

async function startImageGenerateSuite() {
    if (!dom.imgGenProgress) return;
    if (!Object.keys(state.imageFiles).length) {
        alert('请至少上传一张页面截图');
        return;
    }
    const creativity = parseInt(dom.imgCreativitySlider.value, 10) || 5;
    const startBtn = document.getElementById('imgStartGenerateBtn');
    if (startBtn) startBtn.disabled = true;
    dom.imgGenUpload.style.display = 'none';
    dom.imgGenProgress.style.display = 'block';
    if (dom.imgGenStatus) dom.imgGenStatus.textContent = '正在提交截图并识别...';

    const genStart = Date.now();
    const timer = setInterval(() => {
        const sec = Math.floor((Date.now() - genStart) / 1000);
        if (dom.imgGenElapsed) dom.imgGenElapsed.textContent = `已耗时 ${sec} 秒`;
    }, 1000);
    const finish = () => clearInterval(timer);

    try {
        const fd = new FormData();
        fd.append('creativity', String(creativity));
        const extractImagesEl = document.getElementById('imgExtractImages');
        fd.append('extract_images', String(extractImagesEl ? extractImagesEl.checked : true));
        for (const [part, file] of Object.entries(state.imageFiles)) {
            fd.append(part, file);
        }
        const resp = await fetch('/api/template-suites/generate-from-images', {
            method: 'POST',
            body: fd,
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || err.message || `HTTP ${resp.status}`);
        }
        let data;
        if (resp.headers.get('content-type')?.includes('text/event-stream')) {
            data = await readSuiteGenerateStream(resp, dom.imgGenStatus);
        } else {
            data = await resp.json();
        }
        if (data && data.success === false) throw new Error(data.message || '生成失败');
        if (!data || !data.suite) throw new Error('生成未返回套件数据');
        state.imageGeneratedSuite = data.suite;
        if (dom.imgSuiteNameInput) dom.imgSuiteNameInput.value = '';
        await renderImageGenPreview('cover');
        finish();
        dom.imgGenProgress.style.display = 'none';
        dom.imgGenComplete.style.display = 'block';
    } catch (error) {
        finish();
        console.error('Image suite generation error:', error);
        dom.imgGenProgress.style.display = 'none';
        dom.imgGenUpload.style.display = 'block';
        alert(`生成失败：${error.message}`);
    } finally {
        if (startBtn) startBtn.disabled = false;
    }
}

async function renderImageGenPreview(tab) {
    state.currentPreviewTab = tab;
    const s = state.imageGeneratedSuite;
    if (!s) return;
    let html = '';
    if (tab === 'cover') html = s.cover;
    else if (tab === 'transition') html = s.transition;
    else if (tab === 'catalog') html = s.catalog || '';
    else if (tab === 'ending') html = s.ending || '';
    else html = wrapContentPreview(s.header_footer);
    setPreviewDoc(dom.imgPreviewFrame, dom.imgPreviewBox, html);
    highlightTab('imgGenComplete');
}

window.suiteMgmtShowImageGenTab = (tab) => {
    state.currentPreviewTab = tab;
    renderImageGenPreview(tab);
};

async function saveImageGeneratedSuiteToLibrary() {
    const s = state.imageGeneratedSuite;
    if (!s) {
        alert('没有可保存的套件');
        return;
    }
    const defaultName = (s.template_name || 'AI读图') + '套件';
    const name = (dom.imgSuiteNameInput ? dom.imgSuiteNameInput.value : '') || defaultName;
    const saveBtn = document.getElementById('imgSaveSuiteBtn');
    if (saveBtn) saveBtn.disabled = true;
    if (dom.imgSaveStatus) dom.imgSaveStatus.textContent = '保存中...';
    try {
        await api('/api/template-suites', {
            method: 'POST',
            body: JSON.stringify({
                suite_name: name.trim(),
                description: '基于AI读图生成',
                cover: s.cover,
                transition: s.transition,
                catalog: s.catalog || '',
                ending: s.ending || '',
                header_footer: s.header_footer,
                design_tokens: s.design_tokens || '',
                template_id: s.template_id || null,
                template_hash: s.template_hash || null,
                template_name: s.template_name || null,
                tags: s.tags || ['AI读图'],
            }),
        });
        if (dom.imgSaveStatus) dom.imgSaveStatus.textContent = '✅ 已保存到套件库';
        loadSuites(1);
    } catch (error) {
        if (dom.imgSaveStatus) dom.imgSaveStatus.textContent = `❌ 保存失败：${error.message}`;
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

// ---------------- 套件页面 HTML 编辑器（参考 PPT 编辑器） ----------------

const SUITE_PART_LABELS = {
    cover: '封面页',
    transition: '过渡页',
    catalog: '目录页',
    ending: '结尾页',
    header_footer: '内容页（页头页脚）',
};

// 预览 tab 名 → 套件部分键（content tab 对应 header_footer）
function _libTabToPart(tab) {
    return tab === 'content' ? 'header_footer' : tab;
}

// 获取（或初始化）CodeMirror 编辑器；未加载 CodeMirror 时回退到原生 textarea。
function _getCodeMirrorEditor() {
    const ta = document.getElementById('suiteEditorCode');
    if (!ta) return null;
    if (typeof CodeMirror === 'undefined') return null;
    if (!window._suiteCodeMirror) {
        window._suiteCodeMirror = CodeMirror.fromTextArea(ta, {
            mode: 'htmlmixed',
            theme: 'material',
            lineNumbers: true,
            lineWrapping: true,
            autoCloseTags: true,
            autoCloseBrackets: true,
        });
        window._suiteCodeMirror.on('change', () => {
            clearTimeout(window._suiteEditPreviewTimer);
            window._suiteEditPreviewTimer = setTimeout(updateSuiteEditorPreview, 500);
        });
    }
    return window._suiteCodeMirror;
}

async function openSuiteEditor() {
    const id = state.previewSuiteId;
    if (!id) {
        alert('请先在列表中打开一个套件的预览');
        return;
    }
    const part = _libTabToPart(state.currentPreviewTab);
    state.editPart = part;
    const labelEl = document.getElementById('suiteEditPartLabel');
    if (labelEl) labelEl.textContent = SUITE_PART_LABELS[part] || part;
    const status = document.getElementById('suiteEditStatus');
    if (status) status.textContent = '';
    try {
        const data = await api(`/api/template-suites/${id}`);
        const raw = (data.suite || {})[part] || '';
        const cm = _getCodeMirrorEditor();
        if (cm) {
            cm.setValue(raw);
            setTimeout(() => cm.refresh(), 50);
        } else {
            document.getElementById('suiteEditorCode').value = raw;
        }
    } catch (error) {
        alert(`加载套件失败：${error.message}`);
        return;
    }
    document.getElementById('suiteEditorArea').style.display = 'block';
    document.getElementById('previewBox').style.display = 'none';
    const btn = document.getElementById('editSuiteBtn');
    if (btn) btn.textContent = '返回预览';
    updateSuiteEditorPreview();
}

function closeSuiteEditor() {
    state.editPart = null;
    const area = document.getElementById('suiteEditorArea');
    if (area) area.style.display = 'none';
    const previewBox = document.getElementById('previewBox');
    if (previewBox) previewBox.style.display = 'block';
    const btn = document.getElementById('editSuiteBtn');
    if (btn) btn.textContent = '✏️ 编辑当前页面';
    const status = document.getElementById('suiteEditStatus');
    if (status) status.textContent = '';
}

function updateSuiteEditorPreview() {
    const part = state.editPart;
    const frame = document.getElementById('suiteEditPreviewFrame');
    const box = document.getElementById('suiteEditPreviewBox');
    if (!frame || !part) return;
    const cm = _getCodeMirrorEditor();
    let html = cm ? cm.getValue() : document.getElementById('suiteEditorCode').value;
    if (part === 'header_footer') html = wrapContentPreview(html);
    setPreviewDoc(frame, box, html);
}

async function saveSuiteEditor() {
    const id = state.previewSuiteId;
    const part = state.editPart;
    if (!id || !part) return;
    const cm = _getCodeMirrorEditor();
    const html = cm ? cm.getValue() : document.getElementById('suiteEditorCode').value;
    const saveBtn = document.getElementById('suiteEditSaveBtn');
    const status = document.getElementById('suiteEditStatus');
    if (saveBtn) saveBtn.disabled = true;
    if (status) status.textContent = '保存中...';
    try {
        const resp = await fetch(`/api/template-suites/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [part]: html }),
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
            throw new Error(data.detail || data.message || `HTTP ${resp.status}`);
        }
        if (status) status.textContent = '✅ 已保存';
        // 刷新预览数据并回到预览视图
        const previewData = await api(`/api/template-suites/${id}/preview`);
        state.previewData = previewData.preview;
        showPreviewTab(state.currentPreviewTab);
        closeSuiteEditor();
    } catch (error) {
        if (status) status.textContent = `❌ 保存失败：${error.message}`;
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

// 本文件以 <script type="module"> 加载，内联 onchange/onclick/oninput 只能访问 window 上的函数，
// 因此这里把图片生成流程用到的处理函数挂到 window（与套件管理页其它内联处理器一致）。
window.handleImageFileSelected = handleImageFileSelected;
window.clearImageUpload = clearImageUpload;
window.updateImgCreativityLabel = updateImgCreativityLabel;
window.startImageGenerateSuite = startImageGenerateSuite;
window.saveImageGeneratedSuiteToLibrary = saveImageGeneratedSuiteToLibrary;
window.closeImageGenerateModal = closeImageGenerateModal;
window.openSuiteEditor = openSuiteEditor;
window.closeSuiteEditor = closeSuiteEditor;
window.saveSuiteEditor = saveSuiteEditor;

