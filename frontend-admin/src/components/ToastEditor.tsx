import { useEffect, useRef } from "react";
import { Editor, type EditorOptions } from "@toast-ui/editor";

type ToastEditorProps = {
  value: string;
  onChange: (value: string) => void;
  height?: string;
};

export function ToastEditor({
  value,
  onChange,
  height = "420px",
}: ToastEditorProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<Editor | null>(null);
  const onChangeRef = useRef(onChange);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    if (!containerRef.current || editorRef.current) {
      return undefined;
    }

    const options: EditorOptions = {
      el: containerRef.current,
      height,
      initialEditType: "markdown",
      initialValue: value,
      previewStyle: window.matchMedia("(max-width: 1024px)").matches
        ? "tab"
        : "vertical",
    };

    const editor = new Editor(options);
    editor.on("change", () => {
      onChangeRef.current(editor.getMarkdown());
    });
    editorRef.current = editor;

    return () => {
      editor.destroy();
      editorRef.current = null;
    };
  }, [height]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) {
      return;
    }
    const nextValue = value ?? "";
    if (editor.getMarkdown() !== nextValue) {
      editor.setMarkdown(nextValue, false);
    }
  }, [value]);

  return <div ref={containerRef} className="toast-editor-shell" />;
}
