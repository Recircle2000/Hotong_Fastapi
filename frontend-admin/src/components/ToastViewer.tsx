import { useEffect, useRef } from "react";
import Viewer from "@toast-ui/editor/viewer";

type ToastViewerProps = {
  value: string;
};

export function ToastViewer({ value }: ToastViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<Viewer | null>(null);

  useEffect(() => {
    if (!containerRef.current) {
      return undefined;
    }

    const container = containerRef.current;
    container.innerHTML = "";
    const viewer = new Viewer({
      el: container,
      initialValue: value ?? "",
    });
    viewerRef.current = viewer;

    return () => {
      viewerRef.current?.destroy();
      viewerRef.current = null;
    };
  }, [value]);

  return <div ref={containerRef} className="toast-viewer-shell" />;
}
