declare module "@toast-ui/editor" {
  export type EditorOptions = {
    el: HTMLElement;
    height?: string;
    initialEditType?: "markdown" | "wysiwyg";
    initialValue?: string;
    previewStyle?: "tab" | "vertical";
  };

  export class Editor {
    constructor(options: EditorOptions);
    on(event: "change", handler: () => void): void;
    getMarkdown(): string;
    setMarkdown(markdown: string, cursorToEnd?: boolean): void;
    destroy(): void;
  }

  export class Viewer {
    constructor(options: {
      el: HTMLElement;
      initialValue?: string;
    });
    destroy(): void;
  }
}

declare module "@toast-ui/editor/viewer" {
  export default class Viewer {
    constructor(options: {
      el: HTMLElement;
      initialValue?: string;
    });
    destroy(): void;
  }
}
