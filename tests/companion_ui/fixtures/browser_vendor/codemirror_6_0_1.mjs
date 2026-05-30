export const basicSetup = [];

function docFromText(text) {
  return {
    length: text.length,
    toString() {
      return text;
    }
  };
}

export class EditorView {
  constructor(config) {
    this.parent = config.parent || null;
    this.state = {doc: docFromText(String(config.doc || ''))};
    if (this.parent) {
      var mount = document.createElement('div');
      mount.setAttribute('data-testid', 'codemirror-stub');
      mount.textContent = this.state.doc.toString();
      this.parent.appendChild(mount);
      this.mount = mount;
    }
  }

  dispatch(update) {
    if (update && update.changes && typeof update.changes.insert === 'string') {
      this.state = {doc: docFromText(update.changes.insert)};
      if (this.mount) {
        this.mount.textContent = update.changes.insert;
      }
    }
  }

  requestMeasure() {}
}
