# 전산(metainc-web)에 "광고 관리" 탭 추가 — 적용 가이드

> 대상: `~/Documents/GitHub/metainc-web-frontend` (React 18 + Vite + Zustand + React Router)
> 목표: 상단 메뉴에 **"광고 관리"** 탭 추가, **대표+광고팀에게만 노출**, 클릭 시 `ad.metainc.co.kr`(광고 앱) 표시.
> ⚠️ 운영 코드 변경 → 반드시 검토 후, 대표 확인하에 적용·배포.

## 변경 파일 4곳 (+ 백엔드 1)

### 1) `src/router/index.ts` — URL 정의 추가
`METAINC_URL` 객체에 추가:
```ts
advertise: {
  advertise: 'advertise',
  list: 'list',
},
```

### 2) `src/pages/advertise/AdvertisePage.tsx` — 새 페이지
→ 같은 폴더의 `AdvertisePage.tsx` 파일을 그대로 복사.

### 3) `src/router/MetaIncRouter.tsx` — 라우트 추가
```tsx
const { advertise } = METAINC_URL;
// <Routes> 안, 기존 탭들 옆에:
<Route path={`${advertise.advertise}/${advertise.list}`} element={<AdvertisePage />} />
```
(상단에 `import AdvertisePage from '../pages/advertise/AdvertisePage';`)

### 4) `src/components/molecule/common/Header.tsx` — 메뉴 노출
기존 `<NavLink>` 들 사이에 추가:
```tsx
{(isTopManager || (auth as any).isAdvertiseAccess) && (
  <NavLink to="/advertise/list">광고 관리</NavLink>
)}
```

### 5) (백엔드) 권한 `isAdvertiseAccess` 추가 — 둘 중 택1

**A. 정식(권장):** Spring 백엔드 로그인 응답 `auth`에 `isAdvertiseAccess: boolean` 추가 + 직원별 권한설정에서 광고팀에게 부여.
→ 운영 DB·Java 변경이라 신중히. (메모리: Jasypt·운영DB 주의)

**B. 임시(빠른 시작, 백엔드 무변경):** Header.tsx에서 광고팀 사번/로그인ID를 직접 지정.
```tsx
const AD_TEAM = ['대표loginId', 'ad1loginId', 'ad2loginId'];   // ← 실제 ID로
const { loginId } = userStore();
{(isTopManager || AD_TEAM.includes(loginId)) && (
  <NavLink to="/advertise/list">광고 관리</NavLink>
)}
```
→ 1단계는 **B**로 빠르게 시작, 안정화되면 **A**로 전환 권장.

## 단계 요약
- **1단계(지금):** 위 1~4 + 5-B 적용 → 대표+광고팀만 탭 보임. 광고 앱은 iframe 안에서 자체 로그인.
- **2단계(나중):** 5-A 정식 권한 + `AdvertisePage.tsx`의 SSO 주석 활성화 → 전 직원 자동 로그인·읽기전용.

## 배포
프론트 변경 후: `git push cafe24 HEAD:master --force` (기존 워크플로, `.github/workflows/deploy.yml` 참고).
