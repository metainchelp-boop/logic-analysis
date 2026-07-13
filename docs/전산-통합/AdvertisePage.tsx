// 전산(metainc-web-frontend)에 추가할 "광고 관리" 페이지.
// 위치 예: src/pages/advertise/AdvertisePage.tsx
// 광고 앱(ad.metainc.co.kr)을 iframe으로 전산 안에 띄움. 권한 없는 직원은 차단.
//
// ※ 1단계(현재): 광고 앱은 자체 로그인을 사용 → iframe 안에서 한 번 로그인.
//   2단계(나중): ?sso=<token> 으로 전산 로그인 자동 연동(아래 SSO 주석 참고).

import { useRef } from 'react';
import { userStore } from '../../store/user/userStore';

// ★ 'ad.' 서브도메인은 광고차단기에 막혀서 'dashboard.'로 사용
const AD_APP_URL = 'https://dashboard.metainc.co.kr';

export default function AdvertisePage() {
  const { auth, isTopManager } = userStore();
  // 권한: 대표(최고관리자) 또는 광고 관리 권한 보유자만
  const canView = isTopManager || (auth as any).isAdvertiseAccess;
  const iframeRef = useRef<HTMLIFrameElement>(null);

  if (!canView) {
    return <div style={{ padding: 24 }}>광고 관리 열람 권한이 없습니다.</div>;
  }

  // 2단계 SSO 적용 시:
  // const token = (localStorage.getItem('token') || '').replace(/^Bearer\s+/i, '');
  // const src = token ? `${AD_APP_URL}/?sso=${encodeURIComponent(token)}` : AD_APP_URL;
  const src = AD_APP_URL;

  return (
    <div>
      <iframe
        ref={iframeRef}
        src={src}
        title="광고 관리"
        allowFullScreen
        style={{
          width: '100%',
          height: 'calc(100vh - 96px)',
          border: 'none',
          borderRadius: 6,
        }}
      />
    </div>
  );
}
