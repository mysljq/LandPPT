const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.isConnected = true; }
    append(...nodes) { this.children.push(...nodes); }
    prepend(node) { this.children.unshift(node); }
    replaceChildren(...nodes) { this.children = nodes; this.textContent = ''; }
    setAttribute() {}
    addEventListener(event, handler) { this[event] = handler; }
    querySelector() { return this.children.find(n => n.className === 'parallel-page-plan'); }
    remove() { this.isConnected = false; }
}
const text = node => [node.textContent || '', ...node.children.map(text)].join(' ');
const tick = () => new Promise(resolve => setImmediate(resolve));

(async () => {
    let calls = 0;
    let fail = false;
    const context = {window: {}, document: {createElement: tag => new Element(tag)},
        fetch: async () => {
            calls++;
            return {ok: !fail, json: async () => fail ? {detail: '请先保存大纲'} : {
                plan: {groups: [{pages: [1, 2], reference_page: 1, reason: '<script>reason</script>'}]}
            }};
        }};
    vm.runInNewContext(fs.readFileSync('src/landppt/web/static/js/pages/project/todo_board/parallelPagePlan.js', 'utf8'), context);
    const outline = {slides: [{title: '方案 A'}, {title: '方案 B'}]};
    const first = new Element('div');
    const second = new Element('div');
    context.window.ParallelPagePlan.mount(first, outline, 'project');
    context.window.ParallelPagePlan.mount(second, outline, 'project');
    await tick();
    assert.equal(calls, 1, 'multiple outline views share one classification request');
    assert.match(text(first), /基准第 1 页/);
    assert.match(text(first), /第 2 页：方案 B/);
    assert.equal(outline.parallel_page_plan.groups.length, 1);
    assert.match(text(first), /<script>reason<\/script>/, 'model text is inserted as text');
    fail = true;
    const button = first.children[0].children[0].children[1];
    button.click();
    await tick();
    assert.equal(calls, 2);
    assert.match(text(first), /请先保存大纲/);
    assert.equal(button.disabled, false);
    console.log('parallel page plan UI passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
