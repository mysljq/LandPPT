        // ===== dom-to-pptx 客户端导出功能 =====
        let isClientExporting = false;
        let clientExportAbortController = null;
        let clientExportCancelRequested = false;

        function createClientExportAbortError(message = '导出已取消') {
            try {
                return new DOMException(message, 'AbortError');
            } catch (_) {
                const error = new Error(message);
                error.name = 'AbortError';
                return error;
            }
        }

        function isClientExportAbortError(error) {
            return !!(error && (error.name === 'AbortError' || error.code === 20));
        }

        function createClientExportAbortController() {
            if (typeof AbortController === 'function') {
                return new AbortController();
            }
            const fallbackSignal = {
                aborted: false,
                reason: null
            };
            return {
                signal: fallbackSignal,
                abort(reason) {
                    fallbackSignal.aborted = true;
                    fallbackSignal.reason = reason || createClientExportAbortError();
                }
            };
        }

        function throwIfClientExportCancelled(signal) {
            if (signal && signal.aborted) {
                throw signal.reason || createClientExportAbortError();
            }
        }

        function updateExportCancelButton(visible, disabled = false, label = '取消导出') {
            const button = document.getElementById('exportCancelBtn');
            if (!button) return;
            button.style.display = visible ? 'inline-flex' : 'none';
            button.disabled = !!disabled;
            button.innerHTML = disabled
                ? '<i class="fas fa-spinner fa-spin"></i><span>' + label + '</span>'
                : '<i class="fas fa-times"></i><span>' + label + '</span>';
        }

        function cancelClientExport() {
            if (!isClientExporting || !clientExportAbortController || clientExportCancelRequested) {
                return;
            }
            clientExportCancelRequested = true;
            updateExportCancelButton(true, true, '正在取消...');
            updateExportUI('ban', '', '正在取消导出', '请稍候，正在终止当前客户端导出任务...', undefined, '取消中...');
            try {
                clientExportAbortController.abort(createClientExportAbortError());
            } catch (_) {
                clientExportAbortController.abort();
            }
        }

        function updateExportUI(icon, iconClass, title, subtitle, progress, status) {
            const exportIcon = document.getElementById('exportIcon');
            const exportTitle = document.getElementById('exportTitle');
            const exportSubtitle = document.getElementById('exportSubtitle');
            const exportProgressBar = document.getElementById('exportProgressBar');
            const exportStatus = document.getElementById('exportStatus');

            if (icon && exportIcon) {
                exportIcon.className = 'export-icon ' + (iconClass || '');
                exportIcon.innerHTML = '<i class="fas fa-' + icon + '"></i>';
            }
            if (title && exportTitle) exportTitle.textContent = title;
            if (subtitle !== undefined && exportSubtitle) exportSubtitle.textContent = subtitle;
            if (progress !== undefined && exportProgressBar) exportProgressBar.style.width = progress + '%';
            if (status && exportStatus) exportStatus.textContent = status;
        }

        function showExportOverlay() {
            const overlay = document.getElementById('exportOverlay');
            if (overlay) overlay.classList.add('active');
            document.body.style.overflow = 'hidden';
        }

        function hideExportOverlay() {
            const overlay = document.getElementById('exportOverlay');
            if (overlay) overlay.classList.remove('active');
            updateExportCancelButton(false);
            document.body.style.overflow = '';
        }

        function _canParseCssColor(colorValue) {
            if (!colorValue || typeof colorValue !== 'string') return false;
            if (window.CSS && typeof CSS.supports === 'function') {
                return CSS.supports('color', colorValue.trim());
            }
            return true;
        }

        // Normalize unsupported CSS color syntaxes (oklch/lab/...) to a canvas-parsed fallback.
        // If parsing fails, return original text to avoid hard-crashing export flow.
        function _toHexFallback(colorValue) {
            if (!_canParseCssColor(colorValue)) return colorValue;
            try {
                const cvs = document.createElement('canvas');
                cvs.width = cvs.height = 1;
                const ctx = cvs.getContext('2d');
                if (!ctx) return colorValue;
                ctx.fillStyle = '#000';
                ctx.fillStyle = colorValue;
                return ctx.fillStyle || colorValue;
            } catch (_) {
                return colorValue;
            }
        }

        // Convert modern CSS colors (oklch, oklab, lch, lab, color()) to hex for dom-to-pptx compatibility
        function convertModernColors(rootEl) {
            const modernColorRe = /\b(oklch|oklab|lch|lab|color)\s*\(/i;
            // CSS computed-style property names (hyphenated)
            const colorCssProps = [
                'color', 'background-color', 'border-color',
                'border-top-color', 'border-right-color', 'border-bottom-color', 'border-left-color',
                'outline-color', 'text-decoration-color', 'caret-color', 'column-rule-color',
                'fill', 'stroke', 'stop-color', 'flood-color', 'lighting-color'
            ];
            // Corresponding JS camelCase names for el.style
            const colorJsProps = [
                'color', 'backgroundColor', 'borderColor',
                'borderTopColor', 'borderRightColor', 'borderBottomColor', 'borderLeftColor',
                'outlineColor', 'textDecorationColor', 'caretColor', 'columnRuleColor',
                'fill', 'stroke', 'stopColor', 'floodColor', 'lightingColor'
            ];

            const cvs = document.createElement('canvas');
            cvs.width = cvs.height = 1;
            const ctx = cvs.getContext('2d');

            function toHex(val) {
                if (!_canParseCssColor(val)) return val;
                ctx.clearRect(0, 0, 1, 1);
                ctx.fillStyle = '#000';        // reset
                ctx.fillStyle = val;            // let browser parse
                return ctx.fillStyle || val;    // returns normalized color when available
            }

            // First rewrite <style> blocks so CSS rules don't re-inject oklch
            rootEl.querySelectorAll('style').forEach(styleEl => {
                if (modernColorRe.test(styleEl.textContent)) {
                    styleEl.textContent = styleEl.textContent.replace(
                        /(oklch|oklab|lch|lab|color)\([^)]*\)/gi, m => toHex(m)
                    );
                }
            });

            // Then read computed styles and bake as inline overrides
            const allEls = rootEl.querySelectorAll('*');
            const walk = [rootEl, ...allEls];
            for (const el of walk) {
                if (!el.style || el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;

                let cs;
                try { cs = window.getComputedStyle(el); } catch (e) { continue; }

                // Check each color property via computed style
                for (let i = 0; i < colorCssProps.length; i++) {
                    const val = cs.getPropertyValue(colorCssProps[i]);
                    if (val && modernColorRe.test(val)) {
                        el.style[colorJsProps[i]] = toHex(val);
                    }
                }

                // Check background (shorthand – computed style resolves it)
                const bgImg = cs.getPropertyValue('background-image');
                if (bgImg && modernColorRe.test(bgImg)) {
                    el.style.backgroundImage = bgImg.replace(/(oklch|oklab|lch|lab|color)\([^)]*\)/gi, m => toHex(m));
                }

                // box-shadow and text-shadow
                for (const sp of ['box-shadow', 'text-shadow']) {
                    const sv = cs.getPropertyValue(sp);
                    if (sv && modernColorRe.test(sv)) {
                        el.style[sp === 'box-shadow' ? 'boxShadow' : 'textShadow'] =
                            sv.replace(/(oklch|oklab|lch|lab|color)\([^)]*\)/gi, m => toHex(m));
                    }
                }
            }
        }

        function _sleep(ms) {
            return new Promise(resolve => setTimeout(resolve, ms));
        }

        const CLIENT_EXPORT_RESOURCE_CACHE = new Map();
        const CLIENT_EXPORT_MAX_INLINE_BYTES = 18 * 1024 * 1024;

        function resolveClientExportUrl(rawUrl, doc) {
            const value = String(rawUrl || '').trim();
            if (!value || value.startsWith('#') || /^javascript:/i.test(value)) return '';
            if (/^data:/i.test(value)) return value;
            try {
                const parsed = new URL(value, (doc && doc.baseURI) || window.location.href);
                const appOwnedPath = /^\/(?:api\/image\/view\/|api\/image\/thumbnail\/|static\/|temp\/)/i.test(parsed.pathname || '');
                const localHost = /^(localhost|127\.0\.0\.1|0\.0\.0\.0|\[?::1\]?)$/i.test(parsed.hostname || '');
                if (appOwnedPath && localHost && window.location && window.location.origin) {
                    return `${window.location.origin}${parsed.pathname}${parsed.search}${parsed.hash}`;
                }
                return parsed.href;
            } catch (_) {
                return value;
            }
        }

        function readBlobAsDataUrl(blob) {
            return new Promise((resolve) => {
                const reader = new FileReader();
                reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : null);
                reader.onerror = () => resolve(null);
                reader.readAsDataURL(blob);
            });
        }

        async function fetchClientExportResourceAsDataUrl(rawUrl, doc, timeoutMs = 4500) {
            const resolvedUrl = resolveClientExportUrl(rawUrl, doc);
            if (!resolvedUrl) return null;
            if (/^data:/i.test(resolvedUrl)) return resolvedUrl;
            if (/^(javascript|mailto|tel|about):/i.test(resolvedUrl)) return null;
            if (CLIENT_EXPORT_RESOURCE_CACHE.has(resolvedUrl)) {
                return CLIENT_EXPORT_RESOURCE_CACHE.get(resolvedUrl);
            }

            const fetchPromise = (async () => {
                let controller = null;
                let timer = null;
                try {
                    if (typeof AbortController === 'function') {
                        controller = new AbortController();
                        timer = setTimeout(() => controller.abort(), timeoutMs);
                    }
                    const response = await fetch(resolvedUrl, {
                        credentials: 'same-origin',
                        mode: 'cors',
                        signal: controller ? controller.signal : undefined
                    });
                    if (!response || !response.ok) return null;
                    const blob = await response.blob();
                    if (!blob || blob.size <= 0 || blob.size > CLIENT_EXPORT_MAX_INLINE_BYTES) return null;
                    const type = String(blob.type || '').toLowerCase();
                    if (type && !/^image\/|^video\//.test(type)) return null;
                    return await readBlobAsDataUrl(blob);
                } catch (_) {
                    return null;
                } finally {
                    if (timer) clearTimeout(timer);
                }
            })();

            CLIENT_EXPORT_RESOURCE_CACHE.set(resolvedUrl, fetchPromise);
            const result = await fetchPromise;
            CLIENT_EXPORT_RESOURCE_CACHE.set(resolvedUrl, result);
            return result;
        }

        function extractCssUrlTokens(value) {
            const urls = [];
            const text = String(value || '');
            if (!/url\s*\(/i.test(text)) return urls;
            text.replace(/url\(\s*(['"]?)(.*?)\1\s*\)/gi, (_, quote, url) => {
                const clean = String(url || '').trim();
                if (clean) urls.push(clean);
                return _;
            });
            return urls;
        }

        async function inlineImageElementForClientExport(img, doc) {
            if (!img || !img.getAttribute) return;
            try {
                const lazySrc = img.getAttribute('data-src') || img.getAttribute('data-original') || img.getAttribute('data-lazy-src');
                if (!img.getAttribute('src') && lazySrc) {
                    img.setAttribute('src', lazySrc);
                }
                img.loading = 'eager';
                img.decoding = 'sync';
            } catch (_) { }

            const sourceUrl = img.currentSrc || img.getAttribute('src') || '';
            if (!sourceUrl || /^data:/i.test(sourceUrl)) {
                try {
                    img.removeAttribute('srcset');
                    img.removeAttribute('sizes');
                } catch (_) { }
                return;
            }

            const dataUrl = await fetchClientExportResourceAsDataUrl(sourceUrl, doc);
            if (dataUrl && /^data:image\//i.test(dataUrl)) {
                img.setAttribute('src', dataUrl);
                img.removeAttribute('srcset');
                img.removeAttribute('sizes');
            } else if (img.currentSrc && img.currentSrc !== img.getAttribute('src')) {
                img.setAttribute('src', img.currentSrc);
                img.removeAttribute('srcset');
                img.removeAttribute('sizes');
            }
        }

        async function inlineCssBackgroundImagesForClientExport(doc, root) {
            if (!doc || !root || !root.querySelectorAll) return;
            const win = doc.defaultView || window;
            const nodes = [root, ...Array.from(root.querySelectorAll('*'))];

            for (const node of nodes) {
                if (!node || !node.style) continue;
                let bgImage = '';
                try {
                    bgImage = win.getComputedStyle(node).getPropertyValue('background-image') || '';
                } catch (_) {
                    bgImage = '';
                }
                const urls = extractCssUrlTokens(bgImage);
                if (!urls.length) continue;

                let rewritten = bgImage;
                for (const url of urls) {
                    if (/^data:/i.test(url)) continue;
                    const dataUrl = await fetchClientExportResourceAsDataUrl(url, doc);
                    if (dataUrl && /^data:image\//i.test(dataUrl)) {
                        const escaped = url.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                        rewritten = rewritten.replace(new RegExp(escaped, 'g'), dataUrl);
                    }
                }
                if (rewritten !== bgImage) {
                    node.style.setProperty('background-image', rewritten, 'important');
                }
            }
        }

        function inferClientExportObjectFitFromBackgroundSize(bgSize) {
            const raw = String(bgSize || '').trim().toLowerCase();
            if (raw.includes('cover')) return 'cover';
            if (raw.includes('contain')) return 'contain';
            if (raw.includes('100% 100%') || raw.includes('100%')) return 'fill';
            return 'cover';
        }

        function parseClientExportObjectPosition(positionValue) {
            const tokens = String(positionValue || '50% 50%').trim().toLowerCase().split(/\s+/).filter(Boolean);
            const parseToken = (token) => {
                if (token === 'left' || token === 'top') return 0;
                if (token === 'center') return 0.5;
                if (token === 'right' || token === 'bottom') return 1;
                if (token.endsWith('%')) {
                    const n = parseFloat(token);
                    return Number.isFinite(n) ? n / 100 : 0.5;
                }
                return 0.5;
            };
            return {
                x: parseToken(tokens[0] || '50%'),
                y: parseToken(tokens[1] || tokens[0] || '50%')
            };
        }

        function calculateClientExportImageRect(imgW, imgH, targetW, targetH, objectFit, objectPosition) {
            const safeImgW = Math.max(1, imgW || targetW || 1);
            const safeImgH = Math.max(1, imgH || targetH || 1);
            const fit = String(objectFit || 'cover').toLowerCase();
            const wRatio = targetW / safeImgW;
            const hRatio = targetH / safeImgH;
            let renderW = targetW;
            let renderH = targetH;
            if (fit === 'contain') {
                const s = Math.min(wRatio, hRatio);
                renderW = safeImgW * s;
                renderH = safeImgH * s;
            } else if (fit === 'cover') {
                const s = Math.max(wRatio, hRatio);
                renderW = safeImgW * s;
                renderH = safeImgH * s;
            } else if (fit === 'none') {
                renderW = safeImgW;
                renderH = safeImgH;
            }
            const pos = parseClientExportObjectPosition(objectPosition);
            return {
                x: (targetW - renderW) * pos.x,
                y: (targetH - renderH) * pos.y,
                w: renderW,
                h: renderH
            };
        }

        async function convertClientExportImageUrlToPngDataUrl(rawUrl, doc, targetW, targetH, objectFit, objectPosition, filterValue) {
            const resolvedUrl = resolveClientExportUrl(rawUrl, doc);
            if (!resolvedUrl) return null;
            try {
                let bitmap = null;
                if (/^data:/i.test(resolvedUrl)) {
                    bitmap = await new Promise(resolve => {
                        const img = new Image();
                        img.onload = () => resolve(img);
                        img.onerror = () => resolve(null);
                        img.src = resolvedUrl;
                    });
                } else {
                    const response = await fetch(resolvedUrl, { credentials: 'same-origin', mode: 'cors' });
                    if (!response || !response.ok) return null;
                    const blob = await response.blob();
                    if (!blob || blob.size <= 0) return null;

                    bitmap = typeof createImageBitmap === 'function'
                        ? await createImageBitmap(blob)
                        : await new Promise(resolve => {
                            const objectUrl = URL.createObjectURL(blob);
                            const img = new Image();
                            img.onload = () => {
                                URL.revokeObjectURL(objectUrl);
                                resolve(img);
                            };
                            img.onerror = () => {
                                URL.revokeObjectURL(objectUrl);
                                resolve(null);
                            };
                            img.src = objectUrl;
                        });
                }
                if (!bitmap) return null;

                const width = Math.max(1, Math.round(targetW || bitmap.width || 1));
                const height = Math.max(1, Math.round(targetH || bitmap.height || 1));
                const canvas = doc.createElement('canvas');
                canvas.width = width * 2;
                canvas.height = height * 2;
                const ctx = canvas.getContext('2d');
                if (!ctx) return null;
                ctx.scale(2, 2);
                if (filterValue && String(filterValue).trim().toLowerCase() !== 'none') {
                    try { ctx.filter = filterValue; } catch (_) { }
                }
                const rect = calculateClientExportImageRect(
                    bitmap.width,
                    bitmap.height,
                    width,
                    height,
                    objectFit,
                    objectPosition
                );
                ctx.drawImage(bitmap, rect.x, rect.y, rect.w, rect.h);
                if (typeof bitmap.close === 'function') bitmap.close();
                return canvas.toDataURL('image/png');
            } catch (_) {
                return null;
            }
        }

        function getClientExportBackgroundDebugState() {
            const state = window.__LANDPPT_PPTX_BG_EXPORT_DEBUG__ || {
                version: '2026-04-25-layer-clip-v21',
                startedAt: new Date().toISOString(),
                candidates: 0,
                materialized: 0,
                skipped: [],
                converted: []
            };
            window.__LANDPPT_PPTX_BG_EXPORT_DEBUG__ = state;
            return state;
        }

        function recordClientExportBackgroundDebug(kind, payload) {
            try {
                const state = getClientExportBackgroundDebugState();
                if (kind === 'candidate') {
                    state.candidates += 1;
                    return;
                }
                if (kind === 'materialized') {
                    state.materialized += 1;
                    state.converted.push(payload);
                    if (state.converted.length > 80) state.converted.shift();
                    return;
                }
                state.skipped.push({ kind, ...(payload || {}) });
                if (state.skipped.length > 120) state.skipped.shift();
            } catch (_) { }
        }

        function buildClientExportBackgroundImageElement(doc, sourceNode, cs, dataUrl, width, height) {
            const img = doc.createElement('img');
            img.src = dataUrl;
            img.alt = '';
            img.setAttribute('data-client-export-bg-image', 'true');
            img.setAttribute('data-client-export-bg-materialized', 'true');
            if (sourceNode && sourceNode.className) img.className = sourceNode.className;

            const position = cs.getPropertyValue('position') || 'absolute';
            img.style.position = position === 'static' ? 'absolute' : position;
            img.style.left = cs.getPropertyValue('left') || '0px';
            img.style.top = cs.getPropertyValue('top') || '0px';
            img.style.right = cs.getPropertyValue('right') || 'auto';
            img.style.bottom = cs.getPropertyValue('bottom') || 'auto';
            img.style.zIndex = cs.getPropertyValue('z-index') || 'auto';
            img.style.width = `${Math.max(1, Math.round(width || 1))}px`;
            img.style.height = `${Math.max(1, Math.round(height || 1))}px`;
            img.style.margin = cs.getPropertyValue('margin') || '0';
            img.style.opacity = cs.getPropertyValue('opacity') || '1';
            img.style.transform = cs.getPropertyValue('transform') || 'none';
            img.style.transformOrigin = cs.getPropertyValue('transform-origin') || '50% 50%';
            img.style.display = 'block';
            img.style.objectFit = 'fill';
            img.style.objectPosition = '50% 50%';
            img.style.pointerEvents = 'none';
            img.style.borderRadius = cs.getPropertyValue('border-radius') || '0';
            img.style.setProperty('background', 'none', 'important');
            img.style.setProperty('background-image', 'none', 'important');
            img.style.setProperty('filter', 'none', 'important');
            img.width = Math.max(1, Math.round(width || 1));
            img.height = Math.max(1, Math.round(height || 1));
            return img;
        }

        function buildClientExportBackgroundUnderlayImage(doc, dataUrl, width, height) {
            const img = doc.createElement('img');
            img.src = dataUrl;
            img.alt = '';
            img.setAttribute('data-client-export-bg-image', 'true');
            img.setAttribute('data-client-export-bg-underlay', 'true');
            img.style.position = 'absolute';
            img.style.inset = '0';
            img.style.width = '100%';
            img.style.height = '100%';
            img.style.display = 'block';
            img.style.objectFit = 'fill';
            img.style.objectPosition = '50% 50%';
            img.style.pointerEvents = 'none';
            img.style.zIndex = '0';
            img.style.margin = '0';
            img.style.setProperty('background', 'none', 'important');
            img.width = Math.max(1, Math.round(width || 1));
            img.height = Math.max(1, Math.round(height || 1));
            return img;
        }

        async function materializeLeafBackgroundImagesForClientExport(doc, root) {
            if (!doc || !root || !root.querySelectorAll) return;
            const win = doc.defaultView || window;
            const nodes = [root, ...Array.from(root.querySelectorAll('*'))];

            for (const node of nodes) {
                if (!node || !node.style || node.getAttribute('data-client-export-bg-materialized') === 'true') continue;

                let cs;
                try { cs = win.getComputedStyle(node); } catch (_) { continue; }
                if (!cs) continue;

                const bgImage = cs.getPropertyValue('background-image') || '';
                const urls = extractCssUrlTokens(bgImage);
                if (!urls.length) continue;
                recordClientExportBackgroundDebug('candidate');

                const rect = node.getBoundingClientRect();
                const width = Math.max(1, Math.round(rect.width || node.offsetWidth || 1));
                const height = Math.max(1, Math.round(rect.height || node.offsetHeight || 1));
                const hasChildElements = !!(node.children && node.children.length > 0);
                const hasTextContent = !!(node.textContent && node.textContent.trim());
                const isVisualLeaf = !hasChildElements && !hasTextContent;
                if (width <= 1 || height <= 1) {
                    recordClientExportBackgroundDebug('zero-size', {
                        className: node.className || '',
                        bgImage: bgImage.slice(0, 180),
                        width,
                        height
                    });
                    continue;
                }

                const dataUrl = await convertClientExportImageUrlToPngDataUrl(
                    urls[0],
                    doc,
                    width,
                    height,
                    inferClientExportObjectFitFromBackgroundSize(cs.getPropertyValue('background-size')),
                    cs.getPropertyValue('background-position') || '50% 50%',
                    isVisualLeaf ? (cs.getPropertyValue('filter') || '') : ''
                );
                if (!dataUrl) {
                    recordClientExportBackgroundDebug('convert-failed', {
                        className: node.className || '',
                        url: resolveClientExportUrl(urls[0], doc).slice(0, 240),
                        width,
                        height
                    });
                    continue;
                }

                const img = isVisualLeaf
                    ? buildClientExportBackgroundImageElement(doc, node, cs, dataUrl, width, height)
                    : buildClientExportBackgroundUnderlayImage(doc, dataUrl, width, height);
                node.setAttribute('data-client-export-bg-materialized', 'true');
                if (isVisualLeaf && node.parentNode && node !== root && node.tagName !== 'BODY' && node.tagName !== 'HTML') {
                    node.parentNode.replaceChild(img, node);
                } else {
                    if (isVisualLeaf) {
                        img.style.position = 'absolute';
                        img.style.inset = '0';
                        img.style.width = '100%';
                        img.style.height = '100%';
                    } else if (cs.getPropertyValue('position') === 'static') {
                        node.style.setProperty('position', 'relative', 'important');
                    }
                    node.style.setProperty('background-image', 'none', 'important');
                    if (isVisualLeaf) node.style.setProperty('filter', 'none', 'important');
                    node.insertBefore(img, node.firstChild);
                }
                recordClientExportBackgroundDebug('materialized', {
                    className: node.className || '',
                    tagName: node.tagName || '',
                    url: resolveClientExportUrl(urls[0], doc).slice(0, 240),
                    width,
                    height,
                    mode: img.parentNode === node ? (isVisualLeaf ? 'append-child' : 'prepend-underlay') : 'replace-node'
                });
            }
        }

        function createSnapshotImageFromElement(el, dataUrl) {
            if (!el || !el.parentNode || !dataUrl) return null;
            const doc = el.ownerDocument || document;
            const img = doc.createElement('img');
            img.src = dataUrl;
            img.alt = el.getAttribute && el.getAttribute('aria-label') || '';
            img.className = el.className || '';
            img.style.cssText = el.getAttribute && el.getAttribute('style') || '';
            if (!img.style.display) img.style.display = 'block';
            if (!img.style.width) img.style.width = `${el.getBoundingClientRect().width || el.offsetWidth || 1}px`;
            if (!img.style.height) img.style.height = `${el.getBoundingClientRect().height || el.offsetHeight || 1}px`;
            img.setAttribute('data-client-export-snapshot', 'true');
            el.parentNode.replaceChild(img, el);
            return img;
        }

        async function snapshotCanvasElementsForClientExport(doc) {
            if (!doc || !doc.querySelectorAll) return;
            const canvases = Array.from(doc.querySelectorAll('canvas'));
            for (const canvas of canvases) {
                try {
                    if (!canvas.width || !canvas.height) continue;
                    const dataUrl = canvas.toDataURL('image/png');
                    if (dataUrl && dataUrl.length > 128) {
                        createSnapshotImageFromElement(canvas, dataUrl);
                    }
                } catch (_) {
                    // Tainted canvases are left in place; dom-to-pptx will make its own best effort.
                }
            }
        }

        async function snapshotVideoElementsForClientExport(doc) {
            if (!doc || !doc.querySelectorAll) return;
            const videos = Array.from(doc.querySelectorAll('video'));
            for (const video of videos) {
                let dataUrl = null;
                const poster = video.getAttribute('poster') || '';
                if (poster) {
                    dataUrl = await fetchClientExportResourceAsDataUrl(poster, doc);
                }
                if (!dataUrl) {
                    try {
                        if (video.readyState < 2) {
                            await Promise.race([
                                new Promise(resolve => {
                                    video.addEventListener('loadeddata', resolve, { once: true });
                                    video.addEventListener('error', resolve, { once: true });
                                }),
                                _sleep(1200)
                            ]);
                        }
                        const rect = video.getBoundingClientRect();
                        const w = Math.max(1, Math.round(video.videoWidth || rect.width || video.offsetWidth || 1));
                        const h = Math.max(1, Math.round(video.videoHeight || rect.height || video.offsetHeight || 1));
                        const canvas = doc.createElement('canvas');
                        canvas.width = w;
                        canvas.height = h;
                        const ctx = canvas.getContext('2d');
                        if (ctx) {
                            ctx.drawImage(video, 0, 0, w, h);
                            dataUrl = canvas.toDataURL('image/png');
                        }
                    } catch (_) {
                        dataUrl = null;
                    }
                }
                if (dataUrl && /^data:image\//i.test(dataUrl)) {
                    createSnapshotImageFromElement(video, dataUrl);
                }
            }
        }

        async function prepareClientExportDynamicResources(doc, options = {}) {
            if (!doc || !doc.body) return;
            window.__LANDPPT_PPTX_BG_EXPORT_DEBUG__ = {
                version: '2026-04-25-layer-clip-v21',
                startedAt: new Date().toISOString(),
                candidates: 0,
                materialized: 0,
                skipped: [],
                converted: []
            };
            const signal = options.signal || null;
            const throwIfCancelled = () => {
                if (signal && signal.aborted) {
                    throw signal.reason || createClientExportAbortError();
                }
            };

            throwIfCancelled();
            const images = Array.from(doc.images || []);
            for (const img of images) {
                throwIfCancelled();
                await inlineImageElementForClientExport(img, doc);
            }

            await waitForDocumentImagesReady(doc, Number.isFinite(options.imageTimeoutMs) ? options.imageTimeoutMs : 2600);
            throwIfCancelled();
            await inlineCssBackgroundImagesForClientExport(doc, doc.body);
            throwIfCancelled();
            await materializeLeafBackgroundImagesForClientExport(doc, doc.body);
            throwIfCancelled();
            await snapshotVideoElementsForClientExport(doc);
            throwIfCancelled();
            await snapshotCanvasElementsForClientExport(doc);
        }

        window.__landpptDebugMaterializeBg = async function (targetDoc) {
            const doc =
                targetDoc ||
                (document.getElementById('slideFrame') &&
                    (document.getElementById('slideFrame').contentDocument ||
                        (document.getElementById('slideFrame').contentWindow &&
                            document.getElementById('slideFrame').contentWindow.document))) ||
                document;
            window.__LANDPPT_PPTX_BG_EXPORT_DEBUG__ = {
                version: '2026-04-25-layer-clip-v21',
                startedAt: new Date().toISOString(),
                candidates: 0,
                materialized: 0,
                skipped: [],
                converted: []
            };
            await inlineCssBackgroundImagesForClientExport(doc, doc.body);
            await materializeLeafBackgroundImagesForClientExport(doc, doc.body);
            return window.__LANDPPT_PPTX_BG_EXPORT_DEBUG__;
        };

        async function waitForDocumentFontsReady(doc, timeoutMs = 1500) {
            if (!doc || !doc.fonts || !doc.fonts.ready) return;
            try {
                await Promise.race([
                    doc.fonts.ready.catch(() => null),
                    _sleep(timeoutMs)
                ]);
            } catch (_) { }
        }

        function parseCssTimeToMs(raw) {
            if (!raw) return 0;
            const value = String(raw).trim().toLowerCase();
            if (!value) return 0;
            if (value.endsWith('ms')) {
                const n = parseFloat(value.slice(0, -2));
                return Number.isFinite(n) ? Math.max(0, n) : 0;
            }
            if (value.endsWith('s')) {
                const n = parseFloat(value.slice(0, -1));
                return Number.isFinite(n) ? Math.max(0, n * 1000) : 0;
            }
            const n = parseFloat(value);
            return Number.isFinite(n) ? Math.max(0, n) : 0;
        }

        function parseCssTimeListToMsList(raw) {
            if (!raw) return [0];
            const parts = String(raw).split(',');
            const list = parts.map(v => parseCssTimeToMs(v)).filter(v => Number.isFinite(v));
            return list.length > 0 ? list : [0];
        }

        function pickCycleValue(values, idx) {
            if (!values || values.length === 0) return '';
            return values[idx % values.length];
        }

        function estimateAnimationSettleMs(doc, capMs = 3500) {
            if (!doc || !doc.body) return 0;
            let maxMs = 0;
            const nodes = doc.querySelectorAll('*');
            const inspectCount = Math.min(nodes.length, 1500);

            for (let i = 0; i < inspectCount; i++) {
                const el = nodes[i];
                let cs;
                try { cs = doc.defaultView.getComputedStyle(el); } catch (_) { continue; }
                if (!cs) continue;

                // transitions
                const tDur = parseCssTimeListToMsList(cs.transitionDuration);
                const tDelay = parseCssTimeListToMsList(cs.transitionDelay);
                const tLen = Math.max(tDur.length, tDelay.length);
                for (let j = 0; j < tLen; j++) {
                    const total = pickCycleValue(tDur, j) + pickCycleValue(tDelay, j);
                    if (Number.isFinite(total)) maxMs = Math.max(maxMs, total);
                }

                // animations
                const names = String(cs.animationName || '').split(',').map(v => v.trim().toLowerCase());
                const aDur = parseCssTimeListToMsList(cs.animationDuration);
                const aDelay = parseCssTimeListToMsList(cs.animationDelay);
                const aIter = String(cs.animationIterationCount || '1').split(',').map(v => v.trim().toLowerCase());
                const aLen = Math.max(names.length, aDur.length, aDelay.length, aIter.length);
                for (let j = 0; j < aLen; j++) {
                    const name = pickCycleValue(names, j) || '';
                    if (name === 'none') continue;
                    const dur = pickCycleValue(aDur, j);
                    const delay = pickCycleValue(aDelay, j);
                    let iterRaw = pickCycleValue(aIter, j);
                    let iter = 1;
                    if (iterRaw === 'infinite') {
                        // Infinite animations should not block export forever.
                        iter = 1;
                    } else {
                        const parsedIter = parseFloat(iterRaw);
                        iter = Number.isFinite(parsedIter) && parsedIter > 0 ? parsedIter : 1;
                    }
                    const total = delay + dur * iter;
                    if (Number.isFinite(total)) maxMs = Math.max(maxMs, total);
                }
            }

            return Math.min(capMs, Math.max(0, Math.round(maxMs)));
        }

        async function waitForDocumentImagesReady(doc, timeoutMs = 2400) {
            if (!doc) return;
            const imgs = Array.from(doc.images || []);
            const pending = imgs.filter(img => !img.complete);
            if (pending.length === 0) return;

            await Promise.race([
                Promise.allSettled(
                    pending.map(img => new Promise(resolve => {
                        const done = () => {
                            img.removeEventListener('load', done);
                            img.removeEventListener('error', done);
                            resolve(true);
                        };
                        img.addEventListener('load', done, { once: true });
                        img.addEventListener('error', done, { once: true });
                    }))
                ),
                _sleep(timeoutMs)
            ]);
        }

        async function waitForAnimationFrames(win, count = 2) {
            if (!win || typeof win.requestAnimationFrame !== 'function') {
                await _sleep(34 * count);
                return;
            }
            for (let i = 0; i < count; i++) {
                await new Promise(resolve => win.requestAnimationFrame(() => resolve()));
            }
        }

        async function waitForDocumentMutationIdle(doc, quietMs = 320, timeoutMs = 2200) {
            if (!doc || !doc.documentElement) return;
            if (typeof MutationObserver !== 'function') {
                await _sleep(Math.min(Math.max(quietMs, 0), Math.max(timeoutMs, 0)));
                return;
            }

            const safeQuietMs = Math.max(80, Math.round(Number.isFinite(quietMs) ? quietMs : 320));
            const safeTimeoutMs = Math.max(safeQuietMs, Math.round(Number.isFinite(timeoutMs) ? timeoutMs : 2200));

            await new Promise((resolve) => {
                let settled = false;
                let quietTimer = null;
                let hardTimer = null;

                const finish = () => {
                    if (settled) return;
                    settled = true;
                    if (quietTimer) clearTimeout(quietTimer);
                    if (hardTimer) clearTimeout(hardTimer);
                    try { observer.disconnect(); } catch (_) { }
                    resolve();
                };

                const armQuietWindow = () => {
                    if (quietTimer) clearTimeout(quietTimer);
                    quietTimer = setTimeout(finish, safeQuietMs);
                };

                const observer = new MutationObserver((mutations) => {
                    const hasMeaningfulMutation = mutations.some((mutation) => {
                        if (!mutation) return false;
                        if (mutation.type === 'childList' || mutation.type === 'characterData') {
                            return true;
                        }
                        if (mutation.type === 'attributes') {
                            const attrName = String(mutation.attributeName || '').toLowerCase();
                            return !attrName || ['style', 'class', 'src', 'href', 'hidden', 'open'].includes(attrName);
                        }
                        return false;
                    });

                    if (hasMeaningfulMutation) {
                        armQuietWindow();
                    }
                });

                try {
                    observer.observe(doc.documentElement, {
                        subtree: true,
                        childList: true,
                        characterData: true,
                        attributes: true,
                        attributeFilter: ['style', 'class', 'src', 'href', 'hidden', 'open']
                    });
                } catch (_) {
                    resolve();
                    return;
                }

                armQuietWindow();
                hardTimer = setTimeout(finish, safeTimeoutMs);
            });
        }

        function isCanvasLikelyPainted(canvas) {
            if (!canvas) return true;
            if (canvas.width <= 1 || canvas.height <= 1) return false;
            try {
                const dataUrl = canvas.toDataURL('image/png');
                if (dataUrl && dataUrl.length > 1800) return true;
            } catch (_) {
                // Tainted canvas should be considered ready.
                return true;
            }
            try {
                const ctx = canvas.getContext('2d');
                if (!ctx) return true;
                const x = Math.max(0, Math.min(canvas.width - 1, Math.floor(canvas.width / 2)));
                const y = Math.max(0, Math.min(canvas.height - 1, Math.floor(canvas.height / 2)));
                const px = ctx.getImageData(x, y, 1, 1).data;
                return !!(px[0] || px[1] || px[2] || px[3]);
            } catch (_) {
                return true;
            }
        }

        async function waitForCanvasPaintReady(doc, timeoutMs = 2400) {
            if (!doc) return;
            const canvases = Array.from(doc.querySelectorAll('canvas'));
            if (canvases.length === 0) return;

            const start = Date.now();
            while (Date.now() - start < timeoutMs) {
                const allReady = canvases.every(isCanvasLikelyPainted);
                if (allReady) return;
                await _sleep(120);
            }
        }

        function settleCssAnimationsToFinalState(doc) {
            if (!doc || typeof doc.getAnimations !== 'function') return;
            try {
                const animations = doc.getAnimations({ subtree: true }) || [];
                for (const animation of animations) {
                    if (!animation || typeof animation.finish !== 'function') continue;
                    try {
                        const timing = animation.effect && typeof animation.effect.getComputedTiming === 'function'
                            ? animation.effect.getComputedTiming()
                            : null;
                        if (!timing) continue;
                        if (Number.isFinite(timing.endTime) || Number.isFinite(timing.iterations)) {
                            animation.finish();
                        }
                    } catch (_) { }
                }
            } catch (_) { }
        }

        async function waitForIframeVisualReady(tempIframe, timeoutMs = 3200, options = {}) {
            const imageTimeoutMs = Number.isFinite(options.imageTimeoutMs) ? options.imageTimeoutMs : 3000;
            const animationSettleCapMs = Number.isFinite(options.animationSettleCapMs) ? options.animationSettleCapMs : 5500;
            const start = Date.now();
            while (Date.now() - start < timeoutMs) {
                try {
                    const iframeDoc = tempIframe.contentDocument || tempIframe.contentWindow.document;
                    if (!iframeDoc || !iframeDoc.body) {
                        await _sleep(120);
                        continue;
                    }

                    if (iframeDoc.readyState !== 'complete' && iframeDoc.readyState !== 'interactive') {
                        await _sleep(120);
                        continue;
                    }

                    // Try forcing ECharts to flush layout before capture.
                    try {
                        const iframeWin = tempIframe.contentWindow;
                        if (iframeWin && iframeWin.echarts && typeof iframeWin.echarts.getInstanceByDom === 'function') {
                            iframeDoc.querySelectorAll('canvas').forEach((canvasEl) => {
                                try {
                                    const chart = iframeWin.echarts.getInstanceByDom(canvasEl);
                                    if (chart && typeof chart.resize === 'function') {
                                        chart.resize();
                                    }
                                } catch (_) { }
                            });
                        }
                    } catch (_) { }

                    const iframeWin = tempIframe.contentWindow;
                    await waitForDocumentFontsReady(iframeDoc, 1200);
                    await waitForDocumentImagesReady(iframeDoc, imageTimeoutMs);
                    await waitForFormulaRenderReady(iframeDoc, 2400);
                    await waitForCanvasPaintReady(iframeDoc, 2600);
                    await waitForAnimationFrames(iframeWin, 2);

                    // 页面常见入场动画会在 onload 后通过 setTimeout/改 class/改 style 分批触发。
                    // 这里先等 DOM 进入“静默窗口”，避免还停留在 opacity:0 / translate 初始态。
                    await waitForDocumentMutationIdle(
                        iframeDoc,
                        Math.min(420, animationSettleCapMs),
                        Math.min(Math.max(900, animationSettleCapMs), 2600)
                    );
                    await waitForAnimationFrames(iframeWin, 1);

                    // Wait for first-round CSS animation/transition to settle (capped).
                    const settleMs = estimateAnimationSettleMs(iframeDoc, animationSettleCapMs);
                    if (settleMs > 40) {
                        await _sleep(settleMs);
                    }
                    await waitForDocumentMutationIdle(iframeDoc, 180, 900);
                    settleCssAnimationsToFinalState(iframeDoc);
                    // One more frame to commit final paint.
                    await waitForAnimationFrames(iframeWin, 1);
                    tagFormulaNodesForExport(iframeDoc.body || iframeDoc);
                    await waitForCanvasPaintReady(iframeDoc, 900);
                    return;
                } catch (_) {
                    await _sleep(120);
                }
            }
        }

        function decodeCssContentText(rawContent) {
            if (!rawContent) return '';
            let s = String(rawContent).trim();
            if (!s || s === 'none' || s === 'normal' || s === '""' || s === "''") return '';
            if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
                s = s.slice(1, -1);
            }
            s = s.replace(/\\([0-9a-fA-F]{1,6})\s?/g, (_, hex) => {
                try { return String.fromCodePoint(parseInt(hex, 16)); } catch (_) { return ''; }
            });
            s = s.replace(/\\(["'\\])/g, '$1');
            return s;
        }

        const DEFAULT_ICON_EXPORT_RULES = {
            classTokenWhitelist: [
                'fa',
                'fas',
                'far',
                'fab',
                'fal',
                'fad',
                'fat',
                'fa-solid',
                'fa-regular',
                'fa-brands',
                'fa-light',
                'fa-duotone',
                'fa-thin',
                'bi',
                'material-icons',
                'material-symbols-outlined',
                'material-symbols-rounded',
                'material-symbols-sharp',
                'iconify'
            ],
            classPrefixWhitelist: ['fa-', 'bi-', 'ri-', 'ti-', 'ph-', 'mdi-', 'icon-'],
            faStyleClassTokens: [
                'fa',
                'fas',
                'far',
                'fab',
                'fal',
                'fad',
                'fat',
                'fa-solid',
                'fa-regular',
                'fa-brands',
                'fa-light',
                'fa-duotone',
                'fa-thin'
            ],
            faStyleClassAliases: {
                'fal': 'fa-regular',
                'fa-light': 'fa-regular',
                'fad': 'fa-solid',
                'fa-duotone': 'fa-solid',
                'fat': 'fa-regular',
                'fa-thin': 'fa-regular'
            },
            faClassFallbacks: {
                'fa-magnifying-glass-chart': 'fa-chart-line',
                'fa-messages': 'fa-comments',
                'fa-message-lines': 'fa-comment-dots',
                'fa-user-group': 'fa-users',
                'fa-user-group-simple': 'fa-users',
                'fa-envelope-open-text': 'fa-envelope-open',
                'fa-chart-pie-simple': 'fa-chart-pie',
                'fa-square-poll-horizontal': 'fa-chart-bar'
            },
            faDefaultFallbackByStyle: {
                brand: 'fa-github',
                regular: 'fa-circle',
                solid: 'fa-circle'
            }
        };

        let runtimeIconExportRulesRaw = null;
        let runtimeIconExportRulesCompiled = null;
        let runtimeIconExportRulesFetchPromise = null;

        function cloneDefaultIconExportRules() {
            return {
                classTokenWhitelist: Array.from(DEFAULT_ICON_EXPORT_RULES.classTokenWhitelist),
                classPrefixWhitelist: Array.from(DEFAULT_ICON_EXPORT_RULES.classPrefixWhitelist),
                faStyleClassTokens: Array.from(DEFAULT_ICON_EXPORT_RULES.faStyleClassTokens),
                faStyleClassAliases: Object.assign({}, DEFAULT_ICON_EXPORT_RULES.faStyleClassAliases),
                faClassFallbacks: Object.assign({}, DEFAULT_ICON_EXPORT_RULES.faClassFallbacks),
                faDefaultFallbackByStyle: Object.assign({}, DEFAULT_ICON_EXPORT_RULES.faDefaultFallbackByStyle)
            };
        }

        function sanitizeIconExportRules(rawRules) {
            const normalized = cloneDefaultIconExportRules();
            if (!rawRules || typeof rawRules !== 'object') return normalized;

            const toStringList = (value) => Array.isArray(value)
                ? value.map(v => String(v || '').trim().toLowerCase()).filter(Boolean)
                : [];
            const toStringMap = (value) => {
                const out = {};
                if (!value || typeof value !== 'object') return out;
                for (const [key, mapVal] of Object.entries(value)) {
                    const k = String(key || '').trim().toLowerCase();
                    const v = String(mapVal || '').trim().toLowerCase();
                    if (k && v) out[k] = v;
                }
                return out;
            };

            const classTokenWhitelist = toStringList(rawRules.classTokenWhitelist);
            if (classTokenWhitelist.length > 0) normalized.classTokenWhitelist = classTokenWhitelist;

            const classPrefixWhitelist = toStringList(rawRules.classPrefixWhitelist);
            if (classPrefixWhitelist.length > 0) normalized.classPrefixWhitelist = classPrefixWhitelist;

            const faStyleClassTokens = toStringList(rawRules.faStyleClassTokens);
            if (faStyleClassTokens.length > 0) normalized.faStyleClassTokens = faStyleClassTokens;

            const faStyleClassAliases = toStringMap(rawRules.faStyleClassAliases);
            if (Object.keys(faStyleClassAliases).length > 0) {
                normalized.faStyleClassAliases = Object.assign({}, normalized.faStyleClassAliases, faStyleClassAliases);
            }

            const faClassFallbacks = toStringMap(rawRules.faClassFallbacks);
            if (Object.keys(faClassFallbacks).length > 0) {
                normalized.faClassFallbacks = Object.assign({}, normalized.faClassFallbacks, faClassFallbacks);
            }

            const faDefaultFallbackByStyle = toStringMap(rawRules.faDefaultFallbackByStyle);
            if (Object.keys(faDefaultFallbackByStyle).length > 0) {
                normalized.faDefaultFallbackByStyle = Object.assign({}, normalized.faDefaultFallbackByStyle, faDefaultFallbackByStyle);
            }

            return normalized;
        }

        function compileIconExportRules(rawRules) {
            const normalized = sanitizeIconExportRules(rawRules);
            return {
                rawRules: normalized,
                classTokenWhitelistSet: new Set(normalized.classTokenWhitelist),
                classPrefixWhitelist: Array.from(normalized.classPrefixWhitelist),
                faStyleClassTokensSet: new Set(normalized.faStyleClassTokens),
                faStyleClassAliases: Object.assign({}, normalized.faStyleClassAliases),
                faClassFallbacks: Object.assign({}, normalized.faClassFallbacks),
                faDefaultFallbackByStyle: {
                    brand: String(normalized.faDefaultFallbackByStyle.brand || '').trim().toLowerCase() || 'fa-github',
                    regular: String(normalized.faDefaultFallbackByStyle.regular || '').trim().toLowerCase() || 'fa-circle',
                    solid: String(normalized.faDefaultFallbackByStyle.solid || '').trim().toLowerCase() || 'fa-circle'
                }
            };
        }

        function getCompiledIconExportRules() {
            if (!runtimeIconExportRulesCompiled) {
                runtimeIconExportRulesCompiled = compileIconExportRules(runtimeIconExportRulesRaw);
            }
            return runtimeIconExportRulesCompiled;
        }

