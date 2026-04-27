        function getTargetAudience(outline) {
            if (!outline || !outline.metadata) {
                return '普通大众';
            }
            const audienceType = outline.metadata.target_audience;
            // 如果选择的是"自定义"，则使用custom_audience字段的值
            if (audienceType === '自定义' && outline.metadata.custom_audience) {
                return outline.metadata.custom_audience;
            }
            return audienceType || '普通大众';
        }

        // 创建美化的AI优化需求输入弹窗
        function showAIOptimizeModal(config) {
            return new Promise((resolve, reject) => {
                // 创建模态框遮罩
                const modal = document.createElement('div');
                modal.className = 'ai-optimize-modal';

                // 创建弹窗内容
                const content = document.createElement('div');
                content.className = 'ai-optimize-modal__card';

                // 建议示例
                const suggestions = config.suggestions || [
                    '增加更多文字说明',
                    '简化内容，突出核心要点',
                    '添加数据支撑和案例分析',
                    '优化逻辑结构，增强说服力',
                    '增加视觉化描述建议'
                ];

                content.innerHTML = `
                    <div class="ai-optimize-modal__header">
                        <div class="ai-optimize-modal__header-content">
                            <div>
                                <h3 class="ai-optimize-modal__title">
                                    <i class="fas fa-magic"></i>${config.title}
                                </h3>
                                <p class="ai-optimize-modal__subtitle">${config.subtitle}</p>
                            </div>
                            <button type="button" class="ai-optimize-modal__close" onclick="this.closest('.ai-optimize-modal').remove()" aria-label="关闭">
                                <span aria-hidden="true">×</span>
                            </button>
                        </div>
                    </div>

                    <div class="ai-optimize-modal__body">
                        <div class="current-info">
                            <div>
                                <strong><i class="fas fa-info-circle"></i> 当前内容</strong><br>
                                ${config.currentInfo}
                            </div>
                        </div>

                        <div class="input-group">
                            <label class="input-label" for="aiOptimizeInput">
                                <i class="fas fa-edit"></i> 请描述您的优化需求
                            </label>
                            <textarea id="aiOptimizeInput" class="input-textarea" placeholder="详细描述您希望如何优化此内容...

例如：
- 增加更多技术细节
- 重新组织逻辑结构
- 添加案例分析"></textarea>
                        </div>

                        <div class="suggestions">
                            <label class="suggestion-label">
                                <i class="fas fa-lightbulb"></i> 点击快捷建议快速填充
                            </label>
                            <div class="suggestion-list">
                                ${suggestions.map(s => `<span class="suggestion-tag" onclick="document.getElementById('aiOptimizeInput').value = '${s}'">${s}</span>`).join('')}
                            </div>
                        </div>
                    </div>

                    <div class="ai-optimize-modal__footer">
                        <div class="footer-hint">
                            <i class="fas fa-robot"></i> AI将根据您的需求智能优化内容
                        </div>
                        <div class="footer-actions">
                            <button type="button" class="outline-modal-btn" onclick="this.closest('.ai-optimize-modal').remove()">
                                <i class="fas fa-times"></i><span>取消</span>
                            </button>
                            <button type="button" id="confirmOptimizeBtn" class="outline-modal-btn outline-modal-btn--solid">
                                <i class="fas fa-magic"></i><span>开始优化</span>
                            </button>
                        </div>
                    </div>
                `;

                modal.appendChild(content);
                document.body.appendChild(modal);

                // 聚焦输入框
                setTimeout(() => {
                    const input = document.getElementById('aiOptimizeInput');
                    if (input) input.focus();
                }, 100);

                // 点击背景关闭
                modal.addEventListener('click', (e) => {
                    if (e.target === modal) {
                        modal.remove();
                        reject('用户取消');
                    }
                });

                // 确认按钮
                const confirmBtn = document.getElementById('confirmOptimizeBtn');
                confirmBtn.onclick = () => {
                    const input = document.getElementById('aiOptimizeInput');
                    const value = input?.value.trim();
                    if (!value) {
                        // 输入框抖动动画（通过 class 触发，动画定义在 quickEdit.css）
                        input.classList.add('shake');
                        setTimeout(() => { input.classList.remove('shake'); }, 500);
                        return;
                    }
                    modal.remove();
                    resolve(value);
                };
            });
        }

        // AI优化单页幻灯片大纲
        async function aiOptimizeSingleSlideInSlidesEditor() {
            // 从表单中获取当前数据
            const title = document.getElementById('slideTitle')?.value.trim() || '';
            const slideType = document.getElementById('slideType')?.value || 'content';
            const description = document.getElementById('slideDescription')?.value.trim() || '';

            // 获取所有内容要点
            let contentPoints = [];
            const bulletPointsContainer = document.getElementById('bulletPointsContainer');
            if (bulletPointsContainer) {
                const bulletPointItems = bulletPointsContainer.querySelectorAll('.bullet-point-item');
                contentPoints = Array.from(bulletPointItems).map(item => {
                    const textElement = item.querySelector('.bullet-point-text');
                    return textElement ? textElement.textContent.trim() : '';
                }).filter(point => point);
            }

            if (!title) {
                showNotification('请先输入页面标题', 'warning');
                return;
            }

            // 显示美化的优化需求输入弹窗
            let userRequest;
            try {
                userRequest = await showAIOptimizeModal({
                    title: `AI优化 - 第${currentSlideIndex + 1}页`,
                    subtitle: '让AI帮助您优化这一页的内容',
                    currentInfo: `<strong>标题：</strong>${title}<br><strong>类型：</strong>${slideType}<br><strong>内容要点：</strong>${contentPoints.length}个`,
                    suggestions: [
                        '增加更多技术细节和实例',
                        '简化内容，突出核心要点',
                        '优化逻辑结构，使内容更连贯',
                        '增强说服力，添加数据支撑',
                        '丰富表达方式，提升专业度'
                    ]
                });
            } catch (e) {
                return; // 用户取消
            }

            if (!userRequest || !userRequest.trim()) {
                return;
            }

            // 显示加载提示
            showNotification('AI正在优化第' + (currentSlideIndex + 1) + '页...', 'info');

            try {
                // 使用项目大纲数据
                if (!projectOutline || !projectOutline.slides) {
                    throw new Error('大纲数据不存在');
                }

                const outlineContent = JSON.stringify(projectOutline);

                // 调用AI优化接口
                const response = await fetch('/api/ai/optimize-outline', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        outline_content: outlineContent,
                        user_request: userRequest.trim(),
                        language: projectOutline?.metadata?.language || 'zh',
                        project_info: {
                            topic: projectOutline.title || '未知',
                            scenario: projectOutline.metadata?.scenario || '通用',
                            target_audience: getTargetAudience(projectOutline)
                        },
                        optimization_type: 'single',
                        slide_index: currentSlideIndex
                    })
                });

                const result = await response.json();

                if (result.success && result.optimized_content) {
                    // 解析优化后的单页数据
                    const optimizedSlide = JSON.parse(result.optimized_content);

                    // 更新弹窗中的表单
                    document.getElementById('slideTitle').value = optimizedSlide.title || '';
                    document.getElementById('slideType').value = optimizedSlide.slide_type || 'content';
                    document.getElementById('slideDescription').value = optimizedSlide.description || '';

                    // 更新内容要点
                    const container = document.getElementById('bulletPointsContainer');
                    if (container && optimizedSlide.content_points && optimizedSlide.content_points.length > 0) {
                        // 清空现有内容
                        container.innerHTML = '';

                        // 添加优化后的要点
                        optimizedSlide.content_points.forEach((point, index) => {
                            const pointDiv = document.createElement('div');
                            pointDiv.className = 'bullet-point-item';
                            pointDiv.setAttribute('data-index', index);
                            pointDiv.style.cssText = 'display: flex; align-items: flex-start; margin-bottom: 8px; padding: 8px; border-radius: 4px; transition: all 0.2s ease; position: relative;';
                            pointDiv.innerHTML = `
                                <span style="color: #666; margin-right: 8px; font-weight: bold; min-width: 20px;">•</span>
                                <div style="flex: 1; position: relative;">
                                    <div class="bullet-point-text" contenteditable="true" style="outline: none; min-height: 20px; line-height: 1.4; word-wrap: break-word;">${point}</div>
                                </div>
                            `;
                            container.appendChild(pointDiv);
                        });
                    }

                    showNotification('✅ AI优化完成，请检查后保存', 'success');

                } else {
                    // 显示详细的错误信息
                    let errorMsg = result.error || '未知错误';
                    if (result.extracted_json) {
                        console.error('提取的JSON:', result.extracted_json);
                    }
                    if (result.raw_response) {
                        console.error('AI原始响应:', result.raw_response);
                    }
                    showNotification('AI优化失败: ' + errorMsg, 'error');
                }

            } catch (error) {
                console.error('AI优化失败:', error);
                showNotification('AI优化失败: ' + error.message, 'error');
            }
        }

