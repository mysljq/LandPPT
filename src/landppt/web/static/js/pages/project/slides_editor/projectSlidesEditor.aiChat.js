function setAIAssistantMessageText(messageDiv, content) {
    return window.projectSlidesEditorPretext.setAssistantMessageText(messageDiv, content);
}

function refreshAIAssistantMessageLayout(messageDiv) {
    return window.projectSlidesEditorPretext.refreshAssistantMessageLayout(messageDiv);
}

function destroyAIAssistantMessageRender(messageDiv) {
    window.projectSlidesEditorPretext.destroyAssistantMessageRender(messageDiv);
}

function addAIMessage(content, type = 'assistant', messageId = null) {
    const messagesContainer = document.getElementById('aiChatMessages');

    function attachRegenerateButton(messageDiv) {
        if (!messageDiv) return;
        if (!messageDiv.classList.contains('assistant')) return;
        if (messageDiv.classList.contains('system')) return;
        if (messageDiv.classList.contains('ai-waiting')) return;
        if (!messageDiv.id) return;
        if (messageDiv.querySelector('.ai-answer-regenerate-btn')) return;

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ai-answer-regenerate-btn';
        btn.title = '重新回答';
        btn.innerHTML = '<i class="fas fa-sync-alt"></i>';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            regenerateAIAnswerForMessage(messageDiv.id);
        });
        messageDiv.appendChild(btn);
    }

    // 如果提供了messageId，尝试找到现有消息并更新
    if (messageId) {
        const existingMessage = document.getElementById(messageId);
        if (existingMessage) {
            if (type === 'user') {
                existingMessage.textContent = content;
            } else {
                setAIAssistantMessageText(existingMessage, content);
                attachRegenerateButton(existingMessage);
            }
            messagesContainer.scrollTop = messagesContainer.scrollHeight;

            // 尝试同步更新对话历史（用于流式消息的最终落库/覆盖）
            updateAIChatHistoryMessage(messageId, content);
            return existingMessage;
        }
    }

    // 创建新消息
    const messageDiv = document.createElement('div');
    messageDiv.className = `ai-message ${type}`;
    if (!messageId && type !== 'user') {
        messageId = 'ai-message-' + Date.now() + '-' + Math.random().toString(16).slice(2);
    }
    if (messageId) messageDiv.id = messageId;
    if (type === 'assistant') {
        messageDiv.dataset.complete = (content && String(content).trim()) ? 'true' : 'false';
    }

    if (type === 'user') {
        messageDiv.textContent = content;
    } else {
        setAIAssistantMessageText(messageDiv, content);
        attachRegenerateButton(messageDiv);
    }

    messagesContainer.appendChild(messageDiv);
    if (type !== 'user') {
        refreshAIAssistantMessageLayout(messageDiv);
    }
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    // 保存到聊天历史（按幻灯片索引存储）
    if (currentSlideIndex >= 0) {
        if (!aiChatHistory[currentSlideIndex]) {
            aiChatHistory[currentSlideIndex] = [];
        }
        // 将type转换为role格式，以便后端AI能正确理解
        const role = type === 'user' ? 'user' : 'assistant';
        aiChatHistory[currentSlideIndex].push({
            role: role,
            content: content,
            timestamp: Date.now(),
            messageId: messageId
        });
    }

    return messageDiv;
}

function updateAIChatHistoryMessage(messageId, newContent) {
    if (!messageId) return;
    if (currentSlideIndex < 0) return;
    if (!aiChatHistory[currentSlideIndex]) return;

    // 从后往前找，避免同一时间戳生成的ID碰撞（理论上不会）
    for (let i = aiChatHistory[currentSlideIndex].length - 1; i >= 0; i--) {
        const msg = aiChatHistory[currentSlideIndex][i];
        if (msg && msg.messageId === messageId) {
            msg.content = newContent;
            return;
        }
    }
}

// 添加等待响应动画
function addWaitingAnimation() {
    const messagesContainer = document.getElementById('aiChatMessages');
    const waitingDiv = document.createElement('div');
    waitingDiv.className = 'ai-message assistant ai-waiting';
    waitingDiv.id = 'ai-waiting-animation';
    waitingDiv.innerHTML = `
        <div class="ai-typing-indicator">
            <span></span>
            <span></span>
            <span></span>
        </div>
        <span style="margin-left: 10px;">AI正在思考中...</span>
    `;

    messagesContainer.appendChild(waitingDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    return waitingDiv;
}

// 移除等待动画
function removeWaitingAnimation() {
    document.querySelectorAll('#ai-waiting-animation, .ai-message.ai-waiting').forEach(el => el.remove());
}

function clearAIMessages() {
    const messagesContainer = document.getElementById('aiChatMessages');
    messagesContainer.querySelectorAll('.ai-message.assistant').forEach(destroyAIAssistantMessageRender);
    // 保留系统欢迎消息
    const systemMessage = messagesContainer.querySelector('.ai-message.system');
    messagesContainer.innerHTML = '';
    if (systemMessage) {
        messagesContainer.appendChild(systemMessage);
    }
    // 清除当前幻灯片的对话历史
    if (currentSlideIndex >= 0) {
        aiChatHistory[currentSlideIndex] = [];
    }
}

// 切换幻灯片时清除对话记录
function clearAIMessagesForSlideSwitch() {
    const messagesContainer = document.getElementById('aiChatMessages');
    messagesContainer.querySelectorAll('.ai-message.assistant').forEach(destroyAIAssistantMessageRender);
    // 保留系统欢迎消息
    const systemMessage = messagesContainer.querySelector('.ai-message.system');
    messagesContainer.innerHTML = '';
    if (systemMessage) {
        messagesContainer.appendChild(systemMessage);
    }
}

// 验证当前幻灯片索引的有效性
function validateCurrentSlideIndex(functionName = 'unknown') {
    const isValid = currentSlideIndex >= 0 && currentSlideIndex < (slidesData ? slidesData.length : 0);

    if (!isValid) {
        return false;
    }

    return true;
}

// 清除AI对话上下文
function clearAIContext() {
    if (confirm('确定要清除当前幻灯片的对话上下文吗？这将删除当前幻灯片的所有对话记录。')) {
        clearAIMessages();
        showNotification('对话上下文已清除', 'info');
    }
}

// 显示当前幻灯片大纲
function showSlideOutline() {
    if (currentSlideIndex < 0 || currentSlideIndex >= slidesData.length) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    const currentSlide = slidesData[currentSlideIndex];
    let outlineContent = '';

    // 尝试从项目大纲中获取当前页的信息
    if (projectOutline && projectOutline.slides && projectOutline.slides[currentSlideIndex]) {
        const slideOutline = projectOutline.slides[currentSlideIndex];
        outlineContent = `
            <div class="outline-field">
                <label class="outline-field__label" for="slideTitle">标题：</label>
                <input type="text" id="slideTitle" class="outline-field__input" value="${(slideOutline.title || currentSlide.title || '').replace(/"/g, '&quot;')}">
            </div>
            <div class="outline-field">
                <label class="outline-field__label" for="slideType">类型：</label>
                <select id="slideType" class="outline-field__select">
                    <option value="title" ${(slideOutline.slide_type || slideOutline.type) === 'title' ? 'selected' : ''}>标题页</option>
                    <option value="content" ${(slideOutline.slide_type || slideOutline.type) === 'content' ? 'selected' : ''}>内容页</option>
                    <option value="conclusion" ${(slideOutline.slide_type || slideOutline.type) === 'conclusion' ? 'selected' : ''}>结论页</option>
                </select>
            </div>
            ${slideOutline.content_points ? `
                <div class="outline-field">
                    <label class="outline-field__label">要点：</label>
                    <div id="bulletPointsContainer" class="outline-bullets">
                        ${slideOutline.content_points.map((point, index) => `
                            <div class="bullet-point-item" data-index="${index}">
                                <span style="color: #666; margin-right: 8px; font-weight: bold; min-width: 20px;">•</span>
                                <div style="flex: 1; position: relative;">
                                    <div class="bullet-point-text" contenteditable="true" style="outline: none; min-height: 20px; line-height: 1.4; word-wrap: break-word;">${point}</div>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                    <div class="outline-bullets__actions">
                        <button class="enhance-all-btn outline-modal-btn" onclick="enhanceAllBulletPoints()" title="AI增强所有要点">
                            <i class="fas fa-magic"></i><span>增强要点</span>
                        </button>
                        <button type="button" class="outline-modal-btn bullet-add-btn" onclick="addNewBulletPoint()" title="添加要点">
                            <i class="fas fa-plus"></i><span>添加要点</span>
                        </button>
                    </div>
                </div>
            ` : `
                <div class="outline-field">
                    <label class="outline-field__label">要点：</label>
                    <div id="bulletPointsContainer" class="outline-bullets">
                        <div class="outline-bullets__empty">
                            <i class="fas fa-list"></i>
                            <p>暂无要点，点击下方按钮添加</p>
                        </div>
                    </div>
                    <div class="outline-bullets__actions">
                        <button type="button" class="enhance-all-btn outline-modal-btn" onclick="enhanceAllBulletPoints()" title="AI增强所有要点">
                            <i class="fas fa-magic"></i><span>增强要点</span>
                        </button>
                        <button type="button" class="outline-modal-btn bullet-add-btn" onclick="addNewBulletPoint()" title="添加要点">
                            <i class="fas fa-plus"></i><span>添加要点</span>
                        </button>
                    </div>
                </div>
            `}
            <div class="outline-field">
                <label class="outline-field__label" for="slideDescription">描述：</label>
                <textarea id="slideDescription" class="outline-field__textarea" rows="4">${slideOutline.description || ''}</textarea>
            </div>
        `;
    } else {
        outlineContent = `
            <div class="outline-field">
                <label class="outline-field__label" for="slideTitle">标题：</label>
                <input type="text" id="slideTitle" class="outline-field__input" value="${(currentSlide.title || '').replace(/"/g, '&quot;')}">
            </div>
            <div class="outline-field">
                <label class="outline-field__label" for="slideType">类型：</label>
                <select id="slideType" class="outline-field__select">
                    <option value="title">标题页</option>
                    <option value="content" selected>内容页</option>
                    <option value="conclusion">结论页</option>
                </select>
            </div>
            <div class="outline-field">
                <label class="outline-field__label" for="slidePoints">要点：</label>
                <textarea id="slidePoints" class="outline-field__textarea" rows="6" placeholder="请输入要点，每行一个..."></textarea>
            </div>
            <div class="outline-field">
                <label class="outline-field__label" for="slideDescription">描述：</label>
                <textarea id="slideDescription" class="outline-field__textarea" rows="4" placeholder="请输入幻灯片描述..."></textarea>
            </div>
        `;
    }

    // 创建大纲编辑模态框
    const modal = document.createElement('div');
    modal.id = 'slideOutlineModal';
    modal.className = 'outline-modal';

    const content = document.createElement('div');
    content.className = 'outline-modal__content';

    // 头部：标题 + 关闭按钮
    const header = document.createElement('div');
    header.className = 'outline-modal__header';
    header.innerHTML = `
        <h5 class="outline-modal__title"><i class="fas fa-file-alt"></i> 第${currentSlideIndex + 1}页大纲编辑</h5>
    `;

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'outline-modal__close';
    closeBtn.setAttribute('aria-label', '关闭');
    closeBtn.innerHTML = '<i class="fas fa-times"></i>';

    header.appendChild(closeBtn);

    // 内容区
    const body = document.createElement('div');
    body.className = 'outline-modal__body';
    body.innerHTML = outlineContent;

    // 底部按钮区
    const footer = document.createElement('div');
    footer.className = 'outline-modal__footer';
    footer.innerHTML = `
        <button onclick="aiOptimizeSingleSlideInSlidesEditor()" class="outline-modal-btn outline-modal-btn--solid">
            <i class="fas fa-robot"></i>
            <span>AI优化</span>
        </button>
        <div class="outline-modal__footer-group">
            <button onclick="saveSlideOutline()" class="outline-modal-btn outline-modal-btn--solid">
                <i class="fas fa-save"></i>
                <span>保存大纲</span>
            </button>
            <button onclick="regenerateFromOutline()" class="outline-modal-btn">
                <i class="fas fa-sync"></i>
                <span>根据大纲重新生成</span>
            </button>
        </div>
    `;

    closeBtn.addEventListener('click', () => {
        document.body.removeChild(modal);
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            document.body.removeChild(modal);
        }
    });

    content.appendChild(header);
    content.appendChild(body);
    content.appendChild(footer);
    modal.appendChild(content);
    document.body.appendChild(modal);
}

// 保存幻灯片大纲
async function saveSlideOutline() {
    const title = document.getElementById('slideTitle').value;
    const type = document.getElementById('slideType').value;
    const description = document.getElementById('slideDescription').value;

    // 从大纲编辑界面收集要点数据
    let points = [];
    const bulletPointsContainer = document.getElementById('bulletPointsContainer');
    if (bulletPointsContainer) {
        const bulletPointItems = bulletPointsContainer.querySelectorAll('.bullet-point-item');
        points = Array.from(bulletPointItems).map(item => {
            const textElement = item.querySelector('.bullet-point-text');
            return textElement ? textElement.textContent.trim() : '';
        }).filter(point => point); // 过滤空要点
    } else {
        // 回退到传统的textarea方式（如果没有新的要点容器）
        const pointsElement = document.getElementById('slidePoints');
        points = pointsElement ? pointsElement.value.split('\n').filter(p => p.trim()) : [];
    }

    // 更新本地数据
    if (!projectOutline) {
        projectOutline = { slides: [] };
    }
    if (!projectOutline.slides) {
        projectOutline.slides = [];
    }

    projectOutline.slides[currentSlideIndex] = {
        title: title,
        slide_type: type,
        type: type,
        description: description,
        content_points: points
    };

    // 更新幻灯片标题
    if (slidesData[currentSlideIndex]) {
        slidesData[currentSlideIndex].title = title;
        slidesData[currentSlideIndex].slide_type = type;
        slidesData[currentSlideIndex].content_type = type;
        slidesData[currentSlideIndex].description = description;
        slidesData[currentSlideIndex].content_points = points;
    }

    try {
        // 保存大纲到数据库
        const response = await fetch(`/projects/${window.landpptEditorConfig.projectId}/update-outline`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                outline_content: JSON.stringify(projectOutline, null, 2)
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        if (data.status === 'success') {
            if (typeof saveSingleSlideToServer === 'function' && slidesData[currentSlideIndex]?.html_content) {
                await saveSingleSlideToServer(
                    currentSlideIndex,
                    slidesData[currentSlideIndex].html_content,
                    { slideData: slidesData[currentSlideIndex], isUserEdited: true }
                );
            }
            showNotification('大纲已保存！', 'success');
        } else {
            throw new Error(data.message || data.error || '保存失败');
        }
    } catch (error) {
        showNotification('保存大纲失败：' + error.message, 'error');
        return; // 如果保存失败，不关闭模态框
    }

    // 关闭模态框
    const modal = document.getElementById('slideOutlineModal');
    if (modal) {
        document.body.removeChild(modal);
    }

    // 更新缩略图标题
    const thumbnails = document.querySelectorAll('.slide-thumbnail .slide-title');
    if (thumbnails[currentSlideIndex]) {
        thumbnails[currentSlideIndex].textContent = `${currentSlideIndex + 1}. ${title}`;
    }

    // 更新AI编辑助手右上角的大纲显示
    updateAIOutlineDisplay();
}

// 更新AI编辑助手右上角的大纲显示
function updateAIOutlineDisplay() {
    // 这里可以添加更新右上角大纲显示的逻辑
    // 目前大纲按钮点击时会显示最新的大纲信息
}

// 获取项目选择的全局母版模板
async function getSelectedGlobalTemplate() {
    try {
        const response = await fetch(`/api/projects/${window.landpptEditorConfig.projectId}/selected-global-template`);
        if (!response.ok) {
            return null;
        }
        const data = await response.json();
        return data.template || null;
    } catch (error) {
        return null;
    }
}

// 使用全局母版生成幻灯片HTML内容
async function generateSlideWithGlobalTemplate(template, title, content) {
    try {
        let htmlTemplate = template.html_template;

        // 替换模板中的占位符
        htmlTemplate = htmlTemplate.replace(/\{\{\s*page_title\s*\}\}/g, title);
        htmlTemplate = htmlTemplate.replace(/\{\{\s*main_heading\s*\}\}/g, title);
        htmlTemplate = htmlTemplate.replace(/\{\{\s*page_content\s*\}\}/g, content);
        htmlTemplate = htmlTemplate.replace(/\{\{\s*current_page_number\s*\}\}/g, '1');
        htmlTemplate = htmlTemplate.replace(/\{\{\s*total_page_count\s*\}\}/g, slidesData.length.toString());

        return htmlTemplate;
    } catch (error) {
        // 返回默认的HTML内容
        return `
            <div style="width: 1280px; height: 720px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        display: flex; flex-direction: column; justify-content: center; align-items: center;
                        color: white; font-family: 'Microsoft YaHei', Arial, sans-serif;">
                <h1 style="font-size: 48px; margin-bottom: 20px; text-align: center;">${title}</h1>
                <p style="font-size: 24px; text-align: center;">${content}</p>
            </div>
        `;
    }
}

// 根据大纲重新生成幻灯片
function regenerateFromOutline() {
    if (confirm('确定要根据当前大纲重新生成这张幻灯片吗？这将覆盖现有内容。')) {
        // 先保存大纲
        saveSlideOutline();

        // 然后重新生成
        setTimeout(() => {
            regenerateSlideByIndex(currentSlideIndex);
        }, 500);
    }
}

// 同步更新大纲（插入、删除、排序时调用）
async function updateOutlineForSlideOperation(operation, slideIndex, slideData = null) {
    try {
        if (!projectOutline) {
            projectOutline = { slides: [] };
        }
        if (!projectOutline.slides) {
            projectOutline.slides = [];
        }

        switch (operation) {
            case 'insert':
                // 插入新的幻灯片大纲
                if (slideData) {
                    projectOutline.slides.splice(slideIndex, 0, slideData);
                }
                break;
            case 'delete':
                // 删除指定位置的幻灯片大纲
                if (slideIndex >= 0 && slideIndex < projectOutline.slides.length) {
                    projectOutline.slides.splice(slideIndex, 1);
                }
                break;
            case 'move': {
                // 调整大纲顺序（拖拽排序时调用）
                const toIndex = slideData && Number.isInteger(slideData.to_index) ? slideData.to_index : null;
                if (toIndex === null) break;
                if (slideIndex < 0 || slideIndex >= projectOutline.slides.length) break;
                if (toIndex < 0 || toIndex > projectOutline.slides.length) break;
                if (slideIndex === toIndex) break;

                const moved = projectOutline.slides.splice(slideIndex, 1)[0];
                projectOutline.slides.splice(toIndex, 0, moved);
                break;
            }
        }

        if (Array.isArray(projectOutline.slides)) {
            projectOutline.slides.forEach((slide, index) => {
                if (slide && typeof slide === 'object') {
                    slide.page_number = index + 1;
                }
            });
        }

        // 保存更新后的大纲到数据库
        const operationPayload = {
            type: operation,
            slide_index: slideIndex
        };
        if (operation === 'move' && slideData && Number.isInteger(slideData.to_index)) {
            operationPayload.to_index = slideData.to_index;
        }
        if (operation === 'insert' && slideData) {
            operationPayload.slide_data = slideData;
        }

        const response = await fetch(`/projects/${window.landpptEditorConfig.projectId}/update-outline`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                outline_content: JSON.stringify(projectOutline, null, 2),
                operation: operationPayload
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        if (data.status === 'success') {
            // 大纲已同步更新
        } else {
            throw new Error(data.message || data.error || '大纲更新失败');
        }
    } catch (error) {
        throw error;
    }
}

// 发送AI消息 - 使用流式输出
function getAgentEventLabel(event) {
    const type = event && event.type;
    const labels = {
        agent_start: '开始分析',
        agent_step: '选择下一步',
        tool_call: '调用工具',
        tool_result: '工具结果',
        validation_result: '校验结果',
        draft_ready: '草稿就绪',
        needs_confirmation: '等待确认',
        final: '草稿就绪',
        error: '出错'
    };
    return labels[type] || type || 'Agent 事件';
}

function compactAgentText(value, maxLength = 420) {
    const text = typeof value === 'string' ? value : String(value ?? '');
    if (text.length <= maxLength) {
        return text;
    }
    return `${text.slice(0, maxLength)}...`;
}

function stringifyAgentPayload(payload) {
    if (!payload || typeof payload !== 'object') {
        return '';
    }
    try {
        return JSON.stringify(payload, (key, value) => {
            if (typeof value === 'string') {
                return compactAgentText(value, 220);
            }
            return value;
        }, 2);
    } catch (error) {
        return compactAgentText(String(payload));
    }
}

function getAgentEventDetail(event) {
    if (!event) {
        return '';
    }

    if (event.type === 'agent_start') {
        const slideLabel = event.slideIndex ? `第${event.slideIndex}页` : '';
        return [slideLabel, event.mode ? `模式：${event.mode}` : ''].filter(Boolean).join(' · ');
    }

    if (event.type === 'tool_call') {
        const input = stringifyAgentPayload(event.toolInput || event.actionInput || {});
        return [event.tool || event.action || '', input].filter(Boolean).join('\n');
    }

    if (event.type === 'tool_result') {
        const observation = event.observation || {};
        return observation.summary || observation.error || (event.success ? '完成' : '失败');
    }

    if (event.type === 'validation_result') {
        if (event.valid) {
            return 'HTML 校验通过';
        }
        const errors = Array.isArray(event.errors) ? event.errors.join('；') : '';
        return errors ? `HTML 校验失败：${errors}` : 'HTML 校验失败';
    }

    if (event.type === 'agent_step') {
        return [event.thought, event.action].filter(Boolean).join('\n');
    }

    if (event.type === 'draft_ready') {
        return event.proposal?.summary || 'Agent 已生成可预览的编辑草稿';
    }

    if (event.type === 'needs_confirmation') {
        return '';
    }

    if (event.type === 'error') {
        return event.error || event.message || '未知错误';
    }

    return event.message || event.summary || '';
}

function shouldCollapseAgentEvent(event) {
    return event && (event.type === 'tool_call' || event.type === 'tool_result');
}

function getAgentEventSummary(event) {
    if (!event) {
        return '';
    }
    if (event.type === 'tool_call') {
        return event.tool || event.action || 'tool';
    }
    if (event.type === 'tool_result') {
        const observation = event.observation || {};
        return compactAgentText(observation.summary || observation.error || (event.success ? 'done' : 'failed'), 120);
    }
    return compactAgentText(getAgentEventDetail(event), 120);
}

function getAgentEventExpandedDetail(event) {
    if (!event) {
        return '';
    }
    if (event.type === 'tool_result') {
        const payload = stringifyAgentPayload(event.observation || {});
        return payload || getAgentEventDetail(event);
    }
    return getAgentEventDetail(event);
}

function addAgentTimelineEvent(messageDiv, event) {
    if (!messageDiv || !event) return;

    let timeline = messageDiv.querySelector('.ai-agent-timeline');
    if (!timeline) {
        timeline = document.createElement('div');
        timeline.className = 'ai-agent-timeline';
        const regenerateBtn = messageDiv.querySelector('.ai-answer-regenerate-btn');
        messageDiv.insertBefore(timeline, regenerateBtn || null);
    }

    const item = document.createElement('div');
    item.className = `ai-agent-event ai-agent-event-${event.type || 'unknown'}`;

    const isCollapsible = shouldCollapseAgentEvent(event);
    const detailText = compactAgentText(getAgentEventExpandedDetail(event), isCollapsible ? 1400 : 700);

    if (isCollapsible) {
        item.classList.add('is-collapsed');

        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'ai-agent-event-toggle';
        toggle.setAttribute('aria-expanded', 'false');

        const title = document.createElement('span');
        title.className = 'ai-agent-event-title';
        title.textContent = getAgentEventLabel(event);

        const summary = document.createElement('span');
        summary.className = 'ai-agent-event-summary';
        summary.textContent = getAgentEventSummary(event);

        const icon = document.createElement('i');
        icon.className = 'fas fa-chevron-right ai-agent-event-caret';
        icon.setAttribute('aria-hidden', 'true');

        toggle.appendChild(title);
        if (summary.textContent) {
            toggle.appendChild(summary);
        }
        toggle.appendChild(icon);
        item.appendChild(toggle);

        if (detailText) {
            const detail = document.createElement('div');
            detail.className = 'ai-agent-event-detail';
            detail.textContent = detailText;
            item.appendChild(detail);
        }

        toggle.addEventListener('click', () => {
            const expanded = item.classList.toggle('is-expanded');
            item.classList.toggle('is-collapsed', !expanded);
            toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        });
    } else {
        const title = document.createElement('div');
        title.className = 'ai-agent-event-title';
        title.textContent = getAgentEventLabel(event);

        item.appendChild(title);
        if (detailText) {
            const detail = document.createElement('div');
            detail.className = 'ai-agent-event-detail';
            detail.textContent = detailText;
            item.appendChild(detail);
        }
    }
    timeline.appendChild(item);

    const messagesContainer = document.getElementById('aiChatMessages');
    if (messagesContainer) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

function addAgentProposalControls(messageDiv, proposal) {
    if (!messageDiv || !proposal || !proposal.htmlContent) return;
    if (messageDiv.querySelector('.ai-agent-proposal-controls')) return;

    const controls = document.createElement('div');
    controls.className = 'ai-agent-proposal-controls';
    controls.style.cssText = 'display:flex;gap:10px;align-items:center;margin-top:12px;padding-top:12px;border-top:1px solid #e5e7eb;flex-wrap:wrap;';

    const previewBtn = document.createElement('button');
    previewBtn.type = 'button';
    previewBtn.className = 'ai-preview-changes-btn';
    previewBtn.innerHTML = '<i class="fas fa-eye"></i> 预览';
    previewBtn.style.cssText = 'background:#007bff;color:white;border:none;padding:8px 14px;border-radius:4px;cursor:pointer;font-size:14px;display:inline-flex;align-items:center;gap:6px;';
    previewBtn.addEventListener('click', () => showHTMLPreview(proposal.htmlContent));

    const applyBtn = document.createElement('button');
    applyBtn.type = 'button';
    applyBtn.className = 'ai-apply-changes-btn';
    applyBtn.innerHTML = '<i class="fas fa-check"></i> 应用';
    applyBtn.style.cssText = 'background:#28a745;color:white;border:none;padding:8px 14px;border-radius:4px;cursor:pointer;font-size:14px;display:inline-flex;align-items:center;gap:6px;';
    applyBtn.disabled = proposal.validation && proposal.validation.valid === false;
    if (applyBtn.disabled) {
        applyBtn.style.background = '#6c757d';
        applyBtn.style.cursor = 'not-allowed';
        applyBtn.title = 'HTML 校验未通过，不能应用';
    }
    applyBtn.addEventListener('click', async () => {
        applyBtn.disabled = true;
        applyBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 应用中...';
        try {
            await applyAgentProposal(proposal);
            applyBtn.innerHTML = '<i class="fas fa-check-circle"></i> 已应用';
            applyBtn.style.background = '#6c757d';
            discardBtn.disabled = true;
            discardBtn.style.cursor = 'not-allowed';
        } catch (error) {
            applyBtn.disabled = false;
            applyBtn.innerHTML = '<i class="fas fa-exclamation-triangle"></i> 重试应用';
            showNotification(`Agent 应用失败：${error.message || error}`, 'error');
        }
    });

    const discardBtn = document.createElement('button');
    discardBtn.type = 'button';
    discardBtn.className = 'ai-preview-changes-btn';
    discardBtn.innerHTML = '<i class="fas fa-times"></i> 放弃';
    discardBtn.style.cssText = 'background:#6c757d;color:white;border:none;padding:8px 14px;border-radius:4px;cursor:pointer;font-size:14px;display:inline-flex;align-items:center;gap:6px;';
    discardBtn.addEventListener('click', () => {
        controls.remove();
        showNotification('已放弃 Agent 草稿', 'info');
    });

    controls.appendChild(previewBtn);
    controls.appendChild(applyBtn);
    controls.appendChild(discardBtn);

    const regenerateBtn = messageDiv.querySelector('.ai-answer-regenerate-btn');
    messageDiv.insertBefore(controls, regenerateBtn || null);
}

async function handleAgentStreamingResponse(response, waitingDiv) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let aiMessageDiv = null;
    let streamingMessageId = null;
    let finalSummary = '';

    const ensureMessage = () => {
        if (aiMessageDiv) {
            return aiMessageDiv;
        }
        removeWaitingAnimation();
        streamingMessageId = 'ai-agent-message-' + Date.now();
        aiMessageDiv = addAIMessage('Agent 正在编辑当前幻灯片', 'assistant', streamingMessageId);
        aiMessageDiv.dataset.complete = 'false';
        return aiMessageDiv;
    };

    const processLine = (line) => {
        if (!line.trim().startsWith('data: ')) return;
        const dataStr = line.slice(6).trim();
        if (!dataStr) return;

        let event;
        try {
            event = JSON.parse(dataStr);
        } catch (error) {
            return;
        }
        if (!event || event.type === '_agent_done') return;

        const messageDiv = ensureMessage();
        addAgentTimelineEvent(messageDiv, event);

        if ((event.type === 'draft_ready' || event.type === 'final') && event.proposal) {
            finalSummary = event.proposal.summary || 'Agent 已生成可预览的编辑草稿';
            setAIAssistantMessageText(messageDiv, finalSummary);
            addAgentProposalControls(messageDiv, event.proposal);
        } else if (event.type === 'error') {
            finalSummary = `抱歉，Agent 编辑失败：${event.error || event.message || '未知错误'}`;
            setAIAssistantMessageText(messageDiv, finalSummary);
        }
    };

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                processLine(line);
            }
        }

        if (buffer.trim()) {
            processLine(buffer);
        }

        if (!aiMessageDiv) {
            removeWaitingAnimation();
            finalSummary = 'Agent 没有返回可显示的结果';
            aiMessageDiv = addAIMessage(finalSummary, 'assistant');
        }
    } catch (error) {
        removeWaitingAnimation();
        finalSummary = '抱歉，处理 Agent 流式响应时出现错误。';
        if (aiMessageDiv) {
            setAIAssistantMessageText(aiMessageDiv, finalSummary);
        } else {
            aiMessageDiv = addAIMessage(finalSummary, 'assistant');
        }
    } finally {
        if (aiMessageDiv) {
            aiMessageDiv.dataset.complete = 'true';
            if (streamingMessageId && finalSummary) {
                updateAIChatHistoryMessage(streamingMessageId, finalSummary);
            }
            refreshAIAssistantMessageLayout(aiMessageDiv);
        }
    }
}

async function collectAgentProposalFromStream(response, onEvent = null) {
    if (!response || !response.body || typeof response.body.getReader !== 'function') {
        throw new Error('Agent未返回可读取的流式响应');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let proposal = null;

    const processLine = (line) => {
        if (!line.trim().startsWith('data: ')) return;
        const dataStr = line.slice(6).trim();
        if (!dataStr) return;

        const event = JSON.parse(dataStr);
        if (!event || event.type === '_agent_done') return;

        if (onEvent) onEvent(event);
        if (event.type === 'error') {
            throw new Error(event.error || event.message || 'Agent编辑失败');
        }
        if ((event.type === 'draft_ready' || event.type === 'final') && event.proposal && !proposal) {
            proposal = event.proposal;
        }
    };

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            processLine(line);
        }
    }

    buffer += decoder.decode();
    if (buffer.trim()) {
        processLine(buffer);
    }

    if (!proposal) {
        throw new Error('Agent未返回可应用的编辑草稿');
    }
    return proposal;
}

// options:
// - messageOverride: string (optional)
// - appendUserMessage: boolean (default true)
// - chatHistoryOverride: Array<{role:string,content:string}> (optional)
// - skipAutoEmbed: boolean (default false)
async function sendAIMessage(options = {}) {
    const inputBox = document.getElementById('aiInputBox');
    const sendBtn = document.getElementById('aiSendBtn');
    const appendUserMessage = options.appendUserMessage !== false;
    let message = (options.messageOverride ?? inputBox.value).trim();

    if (!message || isAISending) {
        return;
    }

    // 自动将所有已上传的图片信息嵌入到消息中
    if (!options.skipAutoEmbed) {
        message = autoEmbedUploadedImages(message);
    }

    if (currentSlideIndex < 0 || currentSlideIndex >= slidesData.length) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    // 获取当前幻灯片的对话历史（不包含当前这次的 userRequest）
    let chatHistoryForContext = [];
    if (Array.isArray(options.chatHistoryOverride)) {
        chatHistoryForContext = options.chatHistoryOverride;
    } else if (aiChatHistory[currentSlideIndex]) {
        chatHistoryForContext = aiChatHistory[currentSlideIndex].map(msg => ({
            role: msg.role,
            content: msg.content
        }));
    }

    // 禁用发送按钮和输入框
    isAISending = true;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 响应中...';
    inputBox.disabled = true;

    if (appendUserMessage) {
        // 添加用户消息
        addAIMessage(message, 'user');
        inputBox.value = '';
    }

    // 添加等待动画
    const waitingDiv = addWaitingAnimation();

    try {
        // 构建AI请求上下文
        const currentSlide = slidesData[currentSlideIndex];

        // 获取当前幻灯片的大纲信息
        let slideOutline = null;
        if (projectOutline && projectOutline.slides && projectOutline.slides[currentSlideIndex]) {
            slideOutline = projectOutline.slides[currentSlideIndex];
        }

        // 捕获幻灯片截图（如果启用了视觉模式）
        let slideScreenshot = null;
        if (visionModeEnabled) {
            slideScreenshot = await captureSlideScreenshot();
        }

        // 获取所有已上传的图片信息
        const referencedImages = getAllUploadedImages();

        const context = {
            projectId: window.landpptEditorConfig.projectId,
            slideIndex: currentSlideIndex + 1,
            mode: 'slide',
            slideTitle: currentSlide.title,
            slideContent: currentSlide.html_content,
            userRequest: message,
            slideOutline: slideOutline, // 添加当前幻灯片的大纲信息
            chatHistory: chatHistoryForContext, // 添加对话历史（不含当前 userRequest）
            images: referencedImages, // 添加图片信息
            visionEnabled: visionModeEnabled, // 添加视觉模式状态
            slideScreenshot: slideScreenshot, // 添加截图数据
            projectInfo: {
                title: window.landpptEditorProjectInfo.title,
                topic: window.landpptEditorProjectInfo.topic,
                scenario: window.landpptEditorProjectInfo.scenario
            }
        };



        // 发送流式AI编辑请求
        const response = await fetch('/api/ai/slide-edit-agent/stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(context)
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        // 处理流式响应
        await handleAgentStreamingResponse(response, waitingDiv);

    } catch (error) {
        removeWaitingAnimation();
        addAIMessage('抱歉，无法连接到AI服务。请检查网络连接后重试。', 'assistant');
    } finally {
        // 恢复发送按钮和输入框
        isAISending = false;
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<i class="fas fa-paper-plane"></i> 发送';
        inputBox.disabled = false;
        inputBox.focus();
    }
}

async function regenerateLastAIAnswer() {
    if (isAISending) return;

    if (!validateCurrentSlideIndex('regenerateLastAIAnswer')) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    const history = aiChatHistory[currentSlideIndex] || [];
    let lastUserIndex = -1;
    for (let i = history.length - 1; i >= 0; i--) {
        if (history[i] && history[i].role === 'user' && (history[i].content || '').trim()) {
            lastUserIndex = i;
            break;
        }
    }

    if (lastUserIndex < 0) {
        showNotification('没有可重新回答的提问', 'warning');
        return;
    }

    const lastUserMessage = (history[lastUserIndex].content || '').trim();
    if (!lastUserMessage) {
        showNotification('没有可重新回答的提问', 'warning');
        return;
    }

    const chatHistoryOverride = history.slice(0, lastUserIndex).map(m => ({
        role: m.role,
        content: m.content
    }));

    // 清理：移除这次提问之后的历史（通常是上一条 assistant 回复）
    aiChatHistory[currentSlideIndex] = history.slice(0, lastUserIndex + 1);

    // UI：移除最后一条 assistant 消息（避免屏幕上同时出现旧答案和新答案）
    const messagesContainer = document.getElementById('aiChatMessages');
    if (messagesContainer) {
        const allMessages = Array.from(messagesContainer.querySelectorAll('.ai-message'));
        for (let i = allMessages.length - 1; i >= 0; i--) {
            const el = allMessages[i];
            if (el.classList.contains('assistant') && !el.classList.contains('ai-waiting')) {
                destroyAIAssistantMessageRender(el);
                el.remove();
                break;
            }
        }
    }

    showNotification('AI正在重新回答...', 'info');
    await sendAIMessage({
        messageOverride: lastUserMessage,
        appendUserMessage: false,
        chatHistoryOverride,
        skipAutoEmbed: true
    });
}

async function regenerateAIAnswerForMessage(assistantMessageId) {
    if (isAISending) return;
    if (!assistantMessageId) return;

    if (!validateCurrentSlideIndex('regenerateAIAnswerForMessage')) {
        showNotification('请先选择一个幻灯片', 'warning');
        return;
    }

    const history = aiChatHistory[currentSlideIndex] || [];
    const assistantIndex = history.findIndex(m => m && m.role === 'assistant' && m.messageId === assistantMessageId);
    if (assistantIndex < 0) {
        showNotification('无法定位要重新回答的消息', 'warning');
        return;
    }

    let userIndex = -1;
    for (let i = assistantIndex - 1; i >= 0; i--) {
        if (history[i] && history[i].role === 'user' && (history[i].content || '').trim()) {
            userIndex = i;
            break;
        }
    }
    if (userIndex < 0) {
        showNotification('没有可重新回答的提问', 'warning');
        return;
    }

    const userMessage = (history[userIndex].content || '').trim();
    if (!userMessage) {
        showNotification('没有可重新回答的提问', 'warning');
        return;
    }

    const chatHistoryOverride = history.slice(0, userIndex).map(m => ({
        role: m.role,
        content: m.content
    }));

    // 截断历史：移除该 assistant 以及其后的所有消息
    aiChatHistory[currentSlideIndex] = history.slice(0, userIndex + 1);

    // DOM：移除该 assistant 气泡以及其后的所有气泡（保留 system/之前消息）
    const assistantEl = document.getElementById(assistantMessageId);
    if (assistantEl && assistantEl.parentElement) {
        let node = assistantEl;
        while (node) {
            const next = node.nextElementSibling;
            if (node.classList && node.classList.contains('ai-message') && !node.classList.contains('system')) {
                if (node.classList.contains('assistant')) {
                    destroyAIAssistantMessageRender(node);
                }
                node.remove();
            }
            node = next;
        }
    }

    showNotification('AI正在重新回答...', 'info');
    await sendAIMessage({
        messageOverride: userMessage,
        appendUserMessage: false,
        chatHistoryOverride,
        skipAutoEmbed: true
    });
}

// 处理流式响应
