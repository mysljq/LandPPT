/* Shared outline-stage view of the exact plan consumed by slide generation. */
window.ParallelPagePlan = (() => {
    const requests = new Map();
    const colors = ['#2563eb', '#7c3aed', '#0f766e', '#b45309'];
    function element(tag, text) {
        const node = document.createElement(tag);
        if (text !== undefined) node.textContent = text;
        return node;
    }
    function mount(container, outline, projectId) {
        if (!container || !Array.isArray(outline?.slides)) return;
        const previous = container.querySelector(':scope > .parallel-page-plan');
        if (previous) previous.remove();
        const panel = element('section');
        panel.className = 'parallel-page-plan';
        panel.style.cssText = 'padding:16px;margin:12px 0;border:1px solid #dbe3ee;border-radius:10px;background:#f8fafc;text-align:left';
        const heading = element('div');
        heading.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap';
        heading.append(element('strong', '并列页面分组'));
        const button = element('button', '识别 / 重新识别分组');
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline-primary';
        heading.append(button);
        panel.append(heading, element('p', '同组页面共用一张基准页作为设计参考，图示和局部内容仍可不同。未入组页面独立设计。'));
        const result = element('div');
        result.setAttribute('aria-live', 'polite');
        panel.append(result);
        container.prepend(panel);
        const slides = JSON.parse(JSON.stringify(outline.slides));
        const key = projectId + ':' + JSON.stringify(slides);
        async function load(force = false) {
            button.disabled = true;
            result.textContent = '正在识别并列页面…';
            try {
                if (force || !requests.has(key)) {
                    const pending = fetch(`/projects/${encodeURIComponent(projectId)}/parallel-page-plan`, {
                        method: 'POST', headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({slides, force})
                    }).then(async response => {
                        const data = await response.json();
                        if (!response.ok) throw new Error(data.detail || '分组识别失败，请重试');
                        return data.plan;
                    });
                    requests.set(key, pending);
                    pending.catch(() => { if (requests.get(key) === pending) requests.delete(key); });
                }
                const plan = await requests.get(key);
                if (!panel.isConnected) return;
                outline.parallel_page_plan = plan;
                result.replaceChildren();
                const groups = plan.groups || [];
                result.append(element('p', groups.length ? `识别到 ${groups.length} 个并列组。标有“基准”的页面先生成，其余成员统一参考它。` : '未识别到并列页面组，所有页面将独立设计。'));
                groups.forEach((group, index) => {
                    const box = element('div');
                    box.style.cssText = `border-left:4px solid ${colors[index % colors.length]};padding:8px 12px;margin:10px 0;background:white`;
                    box.append(element('strong', `组 ${index + 1} · 基准第 ${group.reference_page} 页`));
                    const list = element('ul');
                    (group.pages || []).forEach(page => {
                        list.append(element('li', `第 ${page} 页${page === group.reference_page ? ' 【基准】' : ''}：${slides[page - 1]?.title || '未命名页面'}`));
                    });
                    box.append(list, element('div', `分组理由：${group.reason || '同级内容，适合共用设计结构'}`));
                    result.append(box);
                });
            } catch (error) {
                result.textContent = error.message;
            } finally {
                button.disabled = false;
            }
        }
        button.addEventListener('click', () => load(true));
        load();
    }
    return {mount};
})();
