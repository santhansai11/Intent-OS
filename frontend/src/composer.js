// An explicit empty selection remains empty; saved sources are the default.
export function sourceFolders(config, selected) {
  if (!config) return [];
  if (selected !== null) return selected.filter(root => config.roots.includes(root));
  const sources = config.roots.filter(root => root !== config.workspace);
  return sources.length ? sources : config.roots;
}
