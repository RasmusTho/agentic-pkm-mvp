var initialized = false;

function renderSvg(id) {
  return '<svg id="' + id + '" xmlns="http://www.w3.org/2000/svg" role="img" ' +
    'data-testid="stub-mermaid-svg" viewBox="0 0 160 40">' +
    '<title>Stub Mermaid diagram</title>' +
    '<rect x="1" y="1" width="158" height="38" fill="none" stroke="currentColor"></rect>' +
    '<text x="12" y="24">stub mermaid</text>' +
    '</svg>';
}

export default {
  initialize(options) {
    initialized = true;
    this.options = options;
  },
  async render(id, source) {
    if (!initialized) {
      throw new Error('mermaid stub used before initialize');
    }
    if (String(source).includes('BROKEN_CLIENT_RENDER')) {
      throw new Error('stub mermaid render failure');
    }
    return {svg: renderSvg(id)};
  }
};
