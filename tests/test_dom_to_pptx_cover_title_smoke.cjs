const assert = require('node:assert/strict');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const JSZip = require('jszip');

async function main() {
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    headless: true,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    const projectMode = process.argv.includes('--project');
    const projectHtml = projectMode
      ? execFileSync(
          process.env.LANDPPT_TEST_PYTHON,
          ['-X', 'utf8', '-c',
            "import sqlite3; c=sqlite3.connect('file:landppt.db?mode=ro',uri=True); print(c.execute('select html_content from slide_data where project_id=? and slide_index=0',('15244677-64e9-4e77-9dff-dc7a69792f76',)).fetchone()[0])"],
          { cwd: process.cwd(), encoding: 'utf8' }
        )
      : null;
    await page.setContent(projectHtml || `
      <style>
        * { box-sizing: border-box; }
        body { margin: 0; width: 1280px; height: 720px; }
        .title-stack { display: flex; flex-direction: column; align-items: flex-start; }
        .title-sub { width: 700px; height: 73px; padding: 12px 32px; border-radius: 22px;
          background: #FFD93D; color: #2D2A32; font: 800 36px/39.6px Arial;
          box-shadow: 0 4px 0 rgba(45,42,50,.22); }
      </style>
      <div class="title-stack"><div class="title-sub">2026年度部门工作整体情况</div></div>
    `);
    await page.addScriptTag({ path: path.join(process.cwd(), 'src/landppt/web/static/js/dom-to-pptx.bundle.js') });
    const result = await page.evaluate(async (project) => {
      const root = project ? document.body : document.querySelector('.title-stack');
      const blob = await domToPptx.exportToPptx(root, {
        skipDownload: true,
        autoEmbedFonts: false,
      });
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      return { data: btoa(binary), version: domToPptx.__landpptPatchVersion };
    }, projectMode);
    const zip = await JSZip.loadAsync(Buffer.from(result.data, 'base64'));
    const slide = Object.keys(zip.files).find((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name));
    const xml = await zip.file(slide).async('string');
    const expectedTitles = projectMode
      ? ['部门工作情况汇报', '2026年度部门工作整体情况']
      : ['2026年度部门工作整体情况'];
    for (const title of expectedTitles) {
      const titleShapes = [...xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)]
        .map((match) => match[0])
        .filter((shape) => shape.includes(`<a:t>${title}</a:t>`) && shape.includes('prstGeom prst="roundRect"'));
      assert.ok(titleShapes.length >= 1, `expected an editable shape for ${title}`);
      for (const shape of titleShapes) {
        assert.match(shape, /<a:bodyPr[^>]*wrap="none"/, `expected no-wrap for ${title}`);
      }
    }
    if (!projectMode) {
      assert.equal(
        (xml.match(/<a:outerShdw\b/g) || []).length,
        1,
        'expected the title shadow to be attached to its editable shape'
      );
    }
    console.log(`PASS ${result.version}: ${projectMode ? 'project cover titles' : 'single-line cover title'} remain editable and unwrapped`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
