import test from 'node:test';
import assert from 'node:assert/strict';
import { sourceFolders } from './composer.js';

const config = {workspace: 'D:\\Intent OS\\storage\\workspace', roots: ['D:\\Intent OS\\storage\\workspace', 'D:\\', 'C:\\Documents']};
test('configured D drive is a default search source', () => {
  assert.deepEqual(sourceFolders(config, null), ['D:\\', 'C:\\Documents']);
});
test('explicit folder selection remains isolated', () => {
  assert.deepEqual(sourceFolders(config, ['D:\\']), ['D:\\']);
  assert.deepEqual(sourceFolders(config, []), []);
});
test('new configured folders are used before any manual selection', () => {
  assert.deepEqual(sourceFolders({...config, roots: [...config.roots, 'E:\\']}, null), ['D:\\', 'C:\\Documents', 'E:\\']);
});
test('removed grants cannot be submitted', () => {
  assert.deepEqual(sourceFolders(config, ['X:\\']), []);
});
test('workspace is fallback only when no other source is configured', () => {
  assert.deepEqual(sourceFolders({workspace: 'workspace', roots: ['workspace']}, null), ['workspace']);
  assert.deepEqual(sourceFolders(null, null), []);
});
