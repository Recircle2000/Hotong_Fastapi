import { useEffect } from "react";

const APP_NAME = "호통 대시보드";

export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = `${title} | ${APP_NAME}`;
  }, [title]);
}
