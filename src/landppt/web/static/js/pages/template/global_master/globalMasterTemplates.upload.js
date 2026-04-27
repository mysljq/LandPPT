export function createGlobalMasterTemplatesUpload({ state, apiClient, formatBytes, loadTemplates }) {

const MAX_IMAGES = 15;

function initImageUpload() {
    console.log('[upload] initImageUpload called (multi-image v2)');
    const imageUploadArea = document.getElementById('imageUploadArea');
    const pptxUploadArea = document.getElementById('pptxUploadArea');
    const dropzone = document.getElementById('uploadDropzone');
    const fileInput = document.getElementById('imageFileInput');
    const selectBtn = document.getElementById('selectImageBtn');
    const removeBtn = document.getElementById('removeImageBtn');
    const addMoreBtn = document.getElementById('addMoreImageBtn');
    const pptxFileInput = document.getElementById('pptxFileInput');
    const selectPptxBtn = document.getElementById('selectPptxBtn');
    const removePptxBtn = document.getElementById('removePptxBtn');
    const modeRadios = document.querySelectorAll('input[name="generation_mode"]');

    // Initialise multi-image array on state
    if (!Array.isArray(state.uploadedImages)) {
        state.uploadedImages = [];
    }

    const updateReferenceUploadArea = (modeValue) => {
        const mode = String(modeValue || 'text_only');
        const showImage = mode === 'reference_style' || mode === 'exact_replica';
        const showPptx = mode === 'pptx_extract';
        if (imageUploadArea) {
            imageUploadArea.style.display = showImage ? 'block' : 'none';
        }
        if (pptxUploadArea) {
            pptxUploadArea.style.display = showPptx ? 'block' : 'none';
        }
    };

    modeRadios.forEach((radio) => {
        radio.addEventListener('change', () => {
            updateReferenceUploadArea(radio.value);
        });
    });
    updateReferenceUploadArea(document.querySelector('input[name="generation_mode"]:checked')?.value || 'text_only');

    if (selectBtn && fileInput) {
        selectBtn.addEventListener('click', () => fileInput.click());
    }
    if (addMoreBtn && fileInput) {
        addMoreBtn.addEventListener('click', () => fileInput.click());
    }
    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            const files = e.target.files;
            if (files && files.length > 0) handleImageFiles(files);
        });
    }
    if (removeBtn) {
        removeBtn.addEventListener('click', clearUploadedImages);
    }
    if (selectPptxBtn && pptxFileInput) {
        selectPptxBtn.addEventListener('click', () => pptxFileInput.click());
    }
    if (pptxFileInput) {
        pptxFileInput.addEventListener('change', (e) => {
            const file = e.target.files?.[0];
            if (file) handlePptxFile(file);
        });
    }
    if (removePptxBtn) {
        removePptxBtn.addEventListener('click', clearUploadedPptx);
    }
    if (dropzone) {
        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('drag-over');
        });
        dropzone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');
        });
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');
            const files = e.dataTransfer?.files;
            if (files && files.length > 0) handleImageFiles(files);
        });
    }
}

function handleImageFiles(fileList) {
    console.log('[upload] handleImageFiles called, fileList.length =', fileList.length);
    if (!Array.isArray(state.uploadedImages)) {
        state.uploadedImages = [];
    }
    const files = Array.from(fileList).filter(f => f.type.startsWith('image/'));
    console.log('[upload] image files after filter:', files.length);
    if (files.length === 0) {
        alert('请上传图片文件');
        return;
    }
    const remaining = MAX_IMAGES - state.uploadedImages.length;
    if (remaining <= 0) {
        alert(`最多上传 ${MAX_IMAGES} 张参考图片`);
        return;
    }
    const toAdd = files.slice(0, remaining);
    let loaded = 0;
    toAdd.forEach((file) => {
        if (file.size > 10 * 1024 * 1024) {
            alert(`图片 ${file.name} 超过 10MB，已跳过`);
            loaded++;
            if (loaded >= toAdd.length) refreshImagePreview();
            return;
        }
        const reader = new FileReader();
        reader.onload = (e) => {
            state.uploadedImages.push({
                filename: file.name,
                size: file.size,
                type: file.type,
                data: e.target.result,
            });
            loaded++;
            if (loaded >= toAdd.length) refreshImagePreview();
        };
        reader.onerror = () => { loaded++; if (loaded >= toAdd.length) refreshImagePreview(); };
        reader.readAsDataURL(file);
    });
    // Reset file input so re-selecting the same files triggers change event
    const fileInput = document.getElementById('imageFileInput');
    if (fileInput) fileInput.value = '';
}

function handlePptxFile(file) {
    const lowerName = String(file?.name || '').toLowerCase();
    const isPptxMime = file?.type === 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
    if (!lowerName.endsWith('.pptx') && !isPptxMime) {
        alert('请上传 .pptx 文件');
        return;
    }
    if (file.size > 50 * 1024 * 1024) {
        alert('PPTX 文件过大，请控制在 50MB 以内');
        return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
        state.uploadedPptx = {
            filename: file.name,
            size: file.size,
            type: file.type || 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            data: e.target.result,
        };
        showPptxPreview();
    };
    reader.onerror = () => alert('读取 PPTX 文件失败');
    reader.readAsDataURL(file);
}

function refreshImagePreview() {
    console.log('[upload] refreshImagePreview called, images:', (state.uploadedImages || []).length);
    const previewContainer = document.getElementById('imagePreviewContainer');
    const grid = document.getElementById('imagePreviewGrid');
    console.log('[upload] DOM elements found:', { previewContainer: !!previewContainer, grid: !!grid });
    const countEl = document.getElementById('imageCount');
    const totalInfo = document.getElementById('imageTotalInfo');

    if (!previewContainer || !grid) return;
    const images = state.uploadedImages || [];
    if (images.length === 0) {
        previewContainer.style.display = 'none';
        return;
    }
    previewContainer.style.display = 'block';
    if (countEl) countEl.textContent = String(images.length);
    const totalSize = images.reduce((s, img) => s + (img.size || 0), 0);
    if (totalInfo) totalInfo.textContent = `${images.length} 张图片，共 ${formatBytes(totalSize)}`;

    grid.innerHTML = '';
    images.forEach((img, idx) => {
        const card = document.createElement('div');
        card.style.cssText = 'position:relative; border:1px solid #e0e0e0; border-radius:6px; overflow:hidden; background:#fafafa;';
        const thumb = document.createElement('img');
        thumb.src = img.data;
        thumb.alt = img.filename;
        thumb.style.cssText = 'width:100%; height:90px; object-fit:cover; display:block;';
        const info = document.createElement('div');
        info.style.cssText = 'padding:2px 4px; font-size:11px; color:#666; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;';
        info.textContent = img.filename;
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.textContent = '\u00d7';
        removeBtn.title = '移除此图';
        removeBtn.style.cssText = 'position:absolute; top:2px; right:2px; background:rgba(0,0,0,0.5); color:#fff; border:none; border-radius:50%; width:20px; height:20px; cursor:pointer; font-size:14px; line-height:18px; text-align:center; padding:0;';
        removeBtn.addEventListener('click', () => {
            state.uploadedImages.splice(idx, 1);
            state.uploadedImage = state.uploadedImages[0] || null;
            refreshImagePreview();
        });
        card.appendChild(thumb);
        card.appendChild(info);
        card.appendChild(removeBtn);
        grid.appendChild(card);
    });
    // Backward compat
    state.uploadedImage = images[0] || null;
}

function showPptxPreview() {
    const previewContainer = document.getElementById('pptxPreviewContainer');
    const filename = document.getElementById('pptxFilename');
    const size = document.getElementById('pptxSize');
    const hint = document.getElementById('pptxExtractHint');

    if (!state.uploadedPptx || !previewContainer) return;

    previewContainer.style.display = 'block';
    if (filename) filename.textContent = state.uploadedPptx.filename;
    if (size) size.textContent = formatBytes(state.uploadedPptx.size);
    if (hint) hint.textContent = '生成时将自动提取 PPTX 的版式、字体、配色与布局特征';
}

function clearUploadedImages() {
    state.uploadedImages = [];
    state.uploadedImage = null;
    const previewContainer = document.getElementById('imagePreviewContainer');
    if (previewContainer) previewContainer.style.display = 'none';
    const grid = document.getElementById('imagePreviewGrid');
    if (grid) grid.innerHTML = '';
    const fileInput = document.getElementById('imageFileInput');
    if (fileInput) fileInput.value = '';
}

function clearUploadedPptx() {
    state.uploadedPptx = null;
    const previewContainer = document.getElementById('pptxPreviewContainer');
    if (previewContainer) previewContainer.style.display = 'none';
    const fileInput = document.getElementById('pptxFileInput');
    if (fileInput) fileInput.value = '';
}

async function handleTemplateImport(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
        const content = await readFileContent(file);
        let templateData;
        if (file.name.endsWith('.json')) {
            templateData = JSON.parse(content);
        } else if (file.name.endsWith('.html')) {
            templateData = {
                template_name: file.name.replace('.html', ''),
                description: `从文件 ${file.name} 导入`,
                html_template: content,
                tags: ['导入'],
                is_default: false,
            };
        } else {
            throw new Error('请选择 .json 或 .html 文件');
        }

        if (!templateData.template_name || !templateData.html_template) {
            throw new Error('文件缺少模板名称或HTML内容');
        }

        if (typeof templateData.tags === 'string') {
            templateData.tags = templateData.tags.split(',').map((t) => t.trim()).filter(Boolean);
        }
        if (!Array.isArray(templateData.tags)) {
            templateData.tags = [];
        }

        await apiClient.post('/api/global-master-templates/', templateData);
        event.target.value = '';
        loadTemplates(1);
        alert('模板导入成功');
    } catch (error) {
        console.error('导入失败', error);
        alert('导入模板失败: ' + error.message);
        event.target.value = '';
    }
}

function readFileContent(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target.result);
        reader.onerror = reject;
        reader.readAsText(file);
    });
}

return {
    initImageUpload,
    clearUploadedImage: clearUploadedImages,
    clearUploadedPptx,
    handleTemplateImport,
};
}
