// Run with NODE_PATH pointing to a runtime containing playwright.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

async function main() {
  const bundlePath = path.resolve(__dirname, '../src/landppt/web/static/js/dom-to-pptx.bundle.js');
  // Expose the capture primitive only in this test, not in the production API.
  const bundle = fs.readFileSync(bundlePath, 'utf8').replace(
    'exports.__landpptPatchVersion =',
    'exports.__testCaptureDecorativeTextVisual = captureDecorativeTextVisual; exports.__landpptPatchVersion ='
  );
  const edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const browser = await chromium.launch({
    ...(fs.existsSync(edge) ? { executablePath: edge } : {}), headless: true,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(String(error)));
    await page.setContent('<html><head></head><body style="margin:0"><img id="page-image" width="12" height="12"></body></html>');
    await page.addScriptTag({ content: bundle });
    const report = await page.evaluate(async () => {
      const capture = window.domToPptx.__testCaptureDecorativeTextVisual;
      const resetCss = `
        *, ::before, ::after { box-sizing: border-box; border-width: 0; border-style: solid; }
        html { line-height: 1.5; }
        body { margin: 0; line-height: inherit; }
        img, svg, video, canvas, audio, iframe, embed, object { display: block; vertical-align: middle; }
        img, video { max-width: 100%; height: auto; }
      `;
      const reset = document.createElement('style');
      reset.textContent = resetCss;
      const makeText = (doc, i) => {
        const node = doc.createElement(i % 2 ? 'span' : 'div');
        node.textContent = ['2026', 'CHAPTER 1', 'Georgia 486', '章节 2'][i];
        node.style.cssText = `position:absolute;display:block;left:40px;top:${40 + i * 130}px;width:600px;height:115px;margin:0;padding:0;border:0;box-sizing:border-box;font:${i % 2 ? 'bold ' : ''}72px Georgia,serif;line-height:${i % 2 ? '1.4' : '1'};letter-spacing:${i % 2 ? '2px' : '-2px'};color:rgba(80,20,130,${i === 0 ? '.15' : '.8'});text-shadow:2px 3px 2px rgba(0,0,0,.2);`;
        doc.body.appendChild(node);
        return node;
      };
      const decode = async (data) => {
        const image = new Image();
        image.src = data;
        await image.decode();
        const canvas = document.createElement('canvas');
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(image, 0, 0);
        const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        let minY = canvas.height, maxY = -1, mass = 0, weightedY = 0;
        for (let y = 0; y < canvas.height; y++) {
          for (let x = 0; x < canvas.width; x++) {
            const alpha = pixels[(y * canvas.width + x) * 4 + 3];
            if (alpha > 8) { minY = Math.min(minY, y); maxY = Math.max(maxY, y); }
            mass += alpha;
            weightedY += y * alpha;
          }
        }
        return { minY, maxY, centroidY: weightedY / mass, mass };
      };
      const comparisons = [];
      for (const useIframe of [false, true]) {
        const frame = useIframe ? document.createElement('iframe') : null;
        if (frame) {
          frame.style.cssText = 'width:1000px;height:650px;border:0';
          document.body.appendChild(frame);
          frame.contentDocument.body.style.margin = '0';
        }
        const doc = frame ? frame.contentDocument : document;
        const nodes = [0, 1, 2, 3].map((i) => makeText(doc, i));
        const original = nodes.map((node) => node.outerHTML);
        const clean = await Promise.all(nodes.map((node) => capture(node, { decorativeTextRasterScale: 2 })));
        document.head.appendChild(reset);
        const polluted = await Promise.all(nodes.map((node) => capture(node, { decorativeTextRasterScale: 2 })));
        const attachShadow = HTMLElement.prototype.attachShadow;
        let fallback;
        try {
          HTMLElement.prototype.attachShadow = undefined;
          fallback = await Promise.all(nodes.map((node) => capture(node, { decorativeTextRasterScale: 2 })));
        } finally {
          HTMLElement.prototype.attachShadow = attachShadow;
        }
        for (let i = 0; i < nodes.length; i++) {
          comparisons.push({
            context: useIframe ? 'iframe' : 'same-document', text: nodes[i].textContent,
            identical: clean[i].data === polluted[i].data,
            fallbackIdentical: clean[i].data === fallback[i].data,
            before: await decode(clean[i].data), after: await decode(polluted[i].data),
            sourceUnchanged: nodes[i].outerHTML === original[i],
          });
        }
        // The fix must not globally override the page's legitimate image CSS.
        if (getComputedStyle(document.getElementById('page-image')).display !== 'block') {
          throw new Error('Page image display was mutated');
        }
        reset.remove();
        nodes.forEach((node) => node.remove());
        if (frame) frame.remove();
      }
      // Both alpha-matte and transparent retry must clean up on measurement errors.
      const failedNode = makeText(document, 0);
      const originalFailedNode = failedNode.outerHTML;
      const offsetTop = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetTop');
      let failedCapture;
      try {
        Object.defineProperty(HTMLElement.prototype, 'offsetTop', {
          configurable: true,
          get() {
            const root = this.getRootNode();
            if (root.host && root.host.hasAttribute('data-html2canvas-font-metrics')) {
              throw new Error('Intentional font-metrics test failure');
            }
            return offsetTop.get.call(this);
          },
        });
        failedCapture = await capture(failedNode);
      } finally {
        Object.defineProperty(HTMLElement.prototype, 'offsetTop', offsetTop);
      }
      const failureSourceUnchanged = failedNode.outerHTML === originalFailedNode;
      failedNode.remove();
      return {
        comparisons, failureSourceUnchanged, failureReturnedNull: failedCapture === null,
        remainingProbes: document.querySelectorAll('[data-html2canvas-font-metrics]').length,
      };
    });
    console.log(JSON.stringify(report, null, 2));
    assert.deepEqual(errors, []);
    assert.equal(report.remainingProbes, 0);
    assert.ok(report.failureReturnedNull);
    assert.ok(report.failureSourceUnchanged);
    for (const sample of report.comparisons) {
      assert.ok(sample.before.mass > 0, `Empty capture: ${sample.text}`);
      assert.ok(sample.identical, `${sample.context}: Tailwind changed pixels for ${sample.text}`);
      assert.ok(sample.fallbackIdentical, `${sample.context}: No-Shadow-DOM fallback changed ${sample.text}`);
      assert.ok(sample.sourceUnchanged, `Source changed: ${sample.text}`);
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
