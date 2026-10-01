// 대시보드 왼쪽 메뉴. 새 페이지는 App.tsx 라우트와 여기에 한 줄씩 추가한다.
export const navGroups = [
  {
    label: "공지",
    items: [
      { path: "/notices", label: "공지 관리" },
      { path: "/emergency-notices", label: "긴급공지" },
    ],
  },
  {
    label: "셔틀",
    items: [
      { path: "/shuttle", label: "시간표 관리" },
      { path: "/shuttle/timetable", label: "전체 시간표" },
      { path: "/shuttle-stations", label: "정류장" },
    ],
  },
  {
    label: "택시팟",
    items: [
      { path: "/taxi-parties", label: "팟 현황" },
      { path: "/taxi-reports", label: "신고" },
      { path: "/taxi-sanctions", label: "제재" },
      // 거점 페이지에 택시팟 운영 스위치도 있다.
      { path: "/taxi-locations", label: "거점·운영 설정" },
    ],
  },
] as const;
