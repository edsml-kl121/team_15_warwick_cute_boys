const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const window = {};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../markdown.js'), 'utf8'), { window, URL });
const parse = text => JSON.parse(JSON.stringify(window.zippyMarkdown.parse(text)));

test('inline bold, italic, code and links become typed parts', () => {
  const [paragraph] = parse('You hit **90 g** of *protein*, see `log` or [route](https://maps.example/x).');
  assert.equal(paragraph.type, 'paragraph');
  assert.deepEqual(paragraph.children.map(part => part.type), ['text', 'strong', 'text', 'em', 'text', 'code', 'text', 'link', 'text']);
  assert.equal(paragraph.children[1].children[0].text, '90 g');
  assert.equal(paragraph.children[7].href, 'https://maps.example/x');
});

test('pipe tables keep header and row cells', () => {
  const [table] = parse('| Place | Protein |\n|---|---:|\n| Easy Health | **45 g** |\n| Salad Factory | 35 g |');
  assert.equal(table.type, 'table');
  assert.deepEqual(table.head.map(cell => cell[0].text), ['Place', 'Protein']);
  assert.equal(table.rows.length, 2);
  assert.equal(table.rows[0][1][0].type, 'strong');
});

test('lists, headings and paragraphs split into blocks', () => {
  const blocks = parse('## Tonight\nTwo options:\n- Easy Health\n- Salad Factory\n\n1. Walk\n2. Eat');
  assert.deepEqual(blocks.map(block => block.type), ['heading', 'paragraph', 'ul', 'ol']);
  assert.equal(blocks[2].items.length, 2);
});

test('plain text, lone asterisks and unclosed markup stay literal', () => {
  const [paragraph] = parse('5 * 3 = 15 and **unfinished');
  assert.deepEqual(paragraph.children, [{ type: 'text', text: '5 * 3 = 15 and **unfinished' }]);
});

test('fenced code keeps its text unparsed', () => {
  const [code] = parse('```\n**not bold**\n```');
  assert.deepEqual(code, { type: 'code', text: '**not bold**' });
});
