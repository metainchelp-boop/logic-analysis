import { useState } from "react";

// ========== 더미 데이터 ==========
const DUMMY = {
  keyword: "무선 이어폰",
  summary: {
    totalVolume: "158,400",
    productCount: "2,847,320",
    goldenCount: "12",
    compLevel: "높음",
  },
  volume: { pc: 42300, mobile: 116100, total: 158400 },
  competition: { pct: 72, label: "레드오션", color: "#ef4444", index: 18.0, products: 2847320, searches: 158400, avgCtr: 4.2 },
  market: { totalRevenue: "328억", avgPrice: "38,500원", top10Avg: "152,300원" },
  sales: { est30: "4,200건", avgDaily: "140건", convRate: "2.8%" },
  trend: [85, 92, 88, 95, 110, 125, 118, 130, 142, 138, 145, 158],
  related: [
    { keyword: "블루투스 이어폰", vol: 89200, comp: "높음" },
    { keyword: "노이즈캔슬링 이어폰", vol: 45600, comp: "보통" },
    { keyword: "무선 이어폰 추천", vol: 38100, comp: "높음" },
    { keyword: "가성비 이어폰", vol: 32400, comp: "보통" },
    { keyword: "운동용 이어폰", vol: 18900, comp: "낮음" },
  ],
  competitors: [
    { rank: 1, name: "삼성 갤럭시 버즈3 프로", price: "259,000", reviews: 15420, rating: 4.8 },
    { rank: 2, name: "애플 에어팟 프로 2세대", price: "329,000", reviews: 28300, rating: 4.9 },
    { rank: 3, name: "소니 WF-1000XM5", price: "279,000", reviews: 8940, rating: 4.7 },
    { rank: 4, name: "젠하이저 모멘텀 TW4", price: "319,000", reviews: 3200, rating: 4.6 },
    { rank: 5, name: "JBL Tune Beam", price: "89,000", reviews: 6780, rating: 4.4 },
  ],
  seo: { score: 72, title: 8, desc: 6, tag: 9, review: 7, detail: 5 },
};

const MONTHS = ["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"];

// ========== 색상 팔레트 (개선) ==========
const C = {
  primary: "#4f46e5",      // 인디고
  primaryLight: "#eef2ff",
  secondary: "#7c3aed",    // 퍼플
  accent: "#f59e0b",       // 앰버
  success: "#10b981",
  danger: "#ef4444",
  warning: "#f59e0b",
  bg: "#f8fafc",
  card: "#ffffff",
  border: "#e2e8f0",
  text: "#0f172a",
  textSub: "#64748b",
  textMuted: "#94a3b8",
};

// ========== 공통 컴포넌트 ==========

function SectionHeader({ icon, title, subtitle, badge }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{
          width: 40, height: 40, borderRadius: 12,
          background: `linear-gradient(135deg, ${C.primaryLight}, #dbeafe)`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 20, flexShrink: 0
        }}>
          {icon}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: C.text, margin: 0 }}>{title}</h2>
            {badge && (
              <span style={{
                fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 999,
                background: badge.bg || "#dcfce7", color: badge.color || "#166534"
              }}>{badge.text}</span>
            )}
          </div>
          {subtitle && <p style={{ fontSize: 13, color: C.textSub, margin: "2px 0 0" }}>{subtitle}</p>}
        </div>
      </div>
      <div style={{ height: 3, background: `linear-gradient(90deg, ${C.primary}, ${C.secondary}, transparent)`, borderRadius: 2, marginTop: 12 }} />
    </div>
  );
}

function Card({ children, style, hover = true }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: C.card, borderRadius: 16, padding: 24,
        border: `1px solid ${hovered && hover ? C.primary + "40" : C.border}`,
        boxShadow: hovered && hover
          ? "0 8px 25px rgba(79,70,229,0.08)"
          : "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06)",
        transition: "all 0.2s ease",
        ...style
      }}
    >
      {children}
    </div>
  );
}

function MetricCard({ icon, label, value, unit, trend, color }) {
  return (
    <Card style={{ padding: "20px 16px", textAlign: "center" }}>
      <div style={{ fontSize: 24, marginBottom: 8 }}>{icon}</div>
      <div style={{ fontSize: 11, fontWeight: 600, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 800, color: color || C.text, lineHeight: 1.2 }}>{value}</div>
      {unit && <div style={{ fontSize: 12, color: C.textSub, marginTop: 2 }}>{unit}</div>}
      {trend && (
        <div style={{ fontSize: 12, fontWeight: 600, marginTop: 8, color: trend > 0 ? C.success : C.danger }}>
          {trend > 0 ? "▲" : "▼"} {Math.abs(trend)}% vs 전월
        </div>
      )}
    </Card>
  );
}

function ProgressBar({ value, max = 100, color, height = 8, showLabel = false }) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div>
      <div style={{ height, borderRadius: height, background: "#f1f5f9", overflow: "hidden" }}>
        <div style={{
          width: `${pct}%`, height: "100%", borderRadius: height,
          background: color || `linear-gradient(90deg, ${C.primary}, ${C.secondary})`,
          transition: "width 0.8s ease"
        }} />
      </div>
      {showLabel && <div style={{ fontSize: 11, color: C.textMuted, textAlign: "right", marginTop: 2 }}>{pct.toFixed(0)}%</div>}
    </div>
  );
}

function MiniChart({ data, color = C.primary, height = 60 }) {
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const w = 100 / (data.length - 1);

  const points = data.map((v, i) => `${i * w},${height - ((v - min) / range) * (height - 8)}`).join(" ");
  const areaPoints = `0,${height} ${points} ${(data.length - 1) * w},${height}`;

  return (
    <svg viewBox={`0 0 ${(data.length - 1) * w} ${height}`} style={{ width: "100%", height }} preserveAspectRatio="none">
      <defs>
        <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.2" />
          <stop offset="100%" stopColor={color} stopOpacity="0.01" />
        </linearGradient>
      </defs>
      <polygon points={areaPoints} fill="url(#chartGrad)" />
      <polyline points={points} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ========== 앵커 네비 (개선) ==========
function AnchorNav({ activeSection, onNavigate }) {
  const sections = [
    { id: "summary", label: "종합요약", icon: "📊" },
    { id: "volume", label: "검색량", icon: "🔍" },
    { id: "market", label: "시장규모", icon: "💰" },
    { id: "competition", label: "경쟁강도", icon: "⚔️" },
    { id: "trend", label: "트렌드", icon: "📈" },
    { id: "related", label: "연관키워드", icon: "🔗" },
    { id: "competitors", label: "경쟁사", icon: "🏆" },
    { id: "seo", label: "SEO", icon: "🎯" },
  ];

  return (
    <div style={{
      position: "sticky", top: 64, zIndex: 40,
      background: "rgba(255,255,255,0.95)", backdropFilter: "blur(12px)",
      borderBottom: `1px solid ${C.border}`, padding: "0"
    }}>
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "0 24px", overflowX: "auto" }}>
        <div style={{ display: "flex", gap: 4, padding: "8px 0" }}>
          {sections.map(s => (
            <button
              key={s.id}
              onClick={() => onNavigate(s.id)}
              style={{
                display: "flex", alignItems: "center", gap: 6,
                padding: "8px 16px", borderRadius: 10, border: "none",
                background: activeSection === s.id ? C.primary : "transparent",
                color: activeSection === s.id ? "#fff" : C.textSub,
                fontSize: 13, fontWeight: 600, cursor: "pointer",
                transition: "all 0.2s", whiteSpace: "nowrap",
                fontFamily: "inherit"
              }}
            >
              <span style={{ fontSize: 14 }}>{s.icon}</span>
              {s.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ========== 섹션들 ==========

function SummarySection() {
  const d = DUMMY.summary;
  return (
    <div id="sec-summary" style={{ marginBottom: 32 }}>
      <SectionHeader icon="📊" title="종합 요약" subtitle={`"${DUMMY.keyword}" 키워드 분석 결과`} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
        <MetricCard icon="🔍" label="월간 검색량" value={d.totalVolume} unit="회/월" trend={12.5} color={C.primary} />
        <MetricCard icon="📦" label="등록 상품수" value={d.productCount} unit="개" color="#7c3aed" />
        <MetricCard icon="💎" label="골든 키워드" value={d.goldenCount} unit="개 발견" color={C.accent} />
        <MetricCard icon="⚡" label="경쟁강도" value={d.compLevel} color={C.danger} />
      </div>
    </div>
  );
}

function VolumeSection() {
  const d = DUMMY.volume;
  const pcPct = Math.round((d.pc / d.total) * 100);
  const mobPct = 100 - pcPct;

  return (
    <div id="sec-volume" style={{ marginBottom: 32 }}>
      <SectionHeader icon="🔍" title="키워드 검색량" subtitle="네이버 검색광고 API 기준 월간 검색량" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* 검색량 수치 */}
        <Card>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 20 }}>
            <span style={{ fontSize: 40, fontWeight: 800, color: C.primary }}>{d.total.toLocaleString()}</span>
            <span style={{ fontSize: 14, color: C.textSub }}>회/월</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div style={{ background: "#f0f4ff", borderRadius: 12, padding: 16 }}>
              <div style={{ fontSize: 11, color: C.textSub, fontWeight: 600, marginBottom: 4 }}>PC 검색</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.primary }}>{d.pc.toLocaleString()}</div>
              <div style={{ fontSize: 12, color: C.textMuted }}>{pcPct}%</div>
            </div>
            <div style={{ background: "#fffbeb", borderRadius: 12, padding: 16 }}>
              <div style={{ fontSize: 11, color: C.textSub, fontWeight: 600, marginBottom: 4 }}>모바일 검색</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: C.accent }}>{d.mobile.toLocaleString()}</div>
              <div style={{ fontSize: 12, color: C.textMuted }}>{mobPct}%</div>
            </div>
          </div>
        </Card>
        {/* 비율 시각화 */}
        <Card>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 16 }}>검색 기기별 비율</div>
          {/* 도넛 차트 대체 — 가로 바 */}
          <div style={{ display: "flex", height: 48, borderRadius: 12, overflow: "hidden", marginBottom: 16 }}>
            <div style={{
              width: `${pcPct}%`, background: `linear-gradient(135deg, ${C.primary}, #818cf8)`,
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "#fff", fontSize: 13, fontWeight: 700
            }}>
              PC {pcPct}%
            </div>
            <div style={{
              width: `${mobPct}%`, background: `linear-gradient(135deg, ${C.accent}, #fbbf24)`,
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "#fff", fontSize: 13, fontWeight: 700
            }}>
              모바일 {mobPct}%
            </div>
          </div>
          <div style={{
            background: "#f0fdf4", borderRadius: 10, padding: "12px 16px",
            border: "1px solid #bbf7d0", fontSize: 13, color: "#166534", lineHeight: 1.6
          }}>
            💡 모바일 비중이 {mobPct}%로 높은 키워드입니다. 모바일 최적화된 상세페이지가 중요합니다.
          </div>
        </Card>
      </div>
    </div>
  );
}

function MarketSection() {
  const d = DUMMY.market;
  return (
    <div id="sec-market" style={{ marginBottom: 32 }}>
      <SectionHeader icon="💰" title="시장 규모 & 매출 추정" subtitle="검색량 × 클릭률 × 전환율 × 평균 단가 기반 추정" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
        <Card style={{ textAlign: "center", padding: "28px 20px" }}>
          <div style={{ fontSize: 14, marginBottom: 12 }}>💰</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.textMuted, marginBottom: 8 }}>월간 시장 규모</div>
          <div style={{ fontSize: 32, fontWeight: 800, color: C.primary }}>{d.totalRevenue}</div>
        </Card>
        <Card style={{ textAlign: "center", padding: "28px 20px" }}>
          <div style={{ fontSize: 14, marginBottom: 12 }}>🏷️</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.textMuted, marginBottom: 8 }}>평균 판매가</div>
          <div style={{ fontSize: 32, fontWeight: 800, color: "#7c3aed" }}>{d.avgPrice}</div>
        </Card>
        <Card style={{ textAlign: "center", padding: "28px 20px" }}>
          <div style={{ fontSize: 14, marginBottom: 12 }}>🥇</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.textMuted, marginBottom: 8 }}>상위 10개 평균</div>
          <div style={{ fontSize: 32, fontWeight: 800, color: C.accent }}>{d.top10Avg}</div>
        </Card>
      </div>
    </div>
  );
}

function CompetitionSection() {
  const d = DUMMY.competition;
  return (
    <div id="sec-competition" style={{ marginBottom: 32 }}>
      <SectionHeader icon="⚔️" title="키워드 경쟁강도" subtitle="상품수 대비 검색량으로 산출된 경쟁 지수" />
      <Card>
        {/* 상단 수치 */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <div style={{
              width: 72, height: 72, borderRadius: "50%",
              background: `conic-gradient(${d.color} ${d.pct * 3.6}deg, #f1f5f9 0deg)`,
              display: "flex", alignItems: "center", justifyContent: "center"
            }}>
              <div style={{
                width: 56, height: 56, borderRadius: "50%", background: "#fff",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 22, fontWeight: 800, color: d.color
              }}>
                {d.pct}
              </div>
            </div>
            <div>
              <span style={{
                display: "inline-block", background: d.color, color: "#fff",
                padding: "5px 16px", borderRadius: 999, fontSize: 14, fontWeight: 700
              }}>
                {d.label}
              </span>
              <div style={{ fontSize: 12, color: C.textSub, marginTop: 4 }}>경쟁지수: {d.index}</div>
            </div>
          </div>
        </div>

        {/* 3구간 바 */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ position: "relative", height: 36, borderRadius: 18, overflow: "hidden" }}>
            <div style={{ position: "absolute", top: 0, left: 0, width: "30%", height: "100%", background: "linear-gradient(90deg, #d1fae5, #a7f3d0)" }} />
            <div style={{ position: "absolute", top: 0, left: "30%", width: "40%", height: "100%", background: "linear-gradient(90deg, #fef3c7, #fde68a)" }} />
            <div style={{ position: "absolute", top: 0, left: "70%", width: "30%", height: "100%", background: "linear-gradient(90deg, #fecaca, #fca5a5)" }} />
            <div style={{
              position: "absolute", top: 2, left: `calc(${d.pct}% - 16px)`,
              width: 32, height: 32, borderRadius: 16,
              background: d.color, border: "3px solid #fff",
              boxShadow: "0 2px 8px rgba(0,0,0,0.2)",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "#fff", fontSize: 11, fontWeight: 800,
              transition: "left 0.8s ease"
            }}>
              {d.pct}
            </div>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 11, color: C.textMuted }}>
            <span style={{ color: C.success }}>블루오션</span>
            <span style={{ color: C.accent }}>보통</span>
            <span style={{ color: C.danger }}>레드오션</span>
          </div>
        </div>

        {/* 핵심 지표 */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
          {[
            { label: "등록 상품수", value: d.products.toLocaleString(), unit: "개", bg: "#fef2f2", color: "#dc2626" },
            { label: "월간 검색량", value: d.searches.toLocaleString(), unit: "회", bg: "#eff6ff", color: "#2563eb" },
            { label: "평균 클릭수", value: d.avgCtr, unit: "회", bg: "#f0fdf4", color: "#16a34a" }
          ].map((m, i) => (
            <div key={i} style={{ background: m.bg, borderRadius: 12, padding: "16px", textAlign: "center" }}>
              <div style={{ fontSize: 11, color: C.textSub, fontWeight: 600, marginBottom: 6 }}>{m.label}</div>
              <div style={{ fontSize: 24, fontWeight: 800, color: m.color }}>
                {m.value}<span style={{ fontSize: 12, fontWeight: 400 }}>{m.unit}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function TrendSection() {
  return (
    <div id="sec-trend" style={{ marginBottom: 32 }}>
      <SectionHeader icon="📈" title="키워드 트렌드" subtitle="최근 12개월 검색량 추이" badge={{ text: "상승세", bg: "#dcfce7", color: "#166534" }} />
      <Card>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <span style={{ fontSize: 28, fontWeight: 800, color: C.primary }}>158,400</span>
            <span style={{ fontSize: 14, color: C.textSub, marginLeft: 8 }}>이번 달</span>
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: C.success }}>▲ 8.9% 상승</div>
        </div>
        <MiniChart data={DUMMY.trend} height={120} />
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 11, color: C.textMuted }}>
          {MONTHS.map(m => <span key={m}>{m}</span>)}
        </div>
      </Card>
    </div>
  );
}

function RelatedSection() {
  const compColor = { "높음": C.danger, "보통": C.accent, "낮음": C.success };
  const compBg = { "높음": "#fef2f2", "보통": "#fffbeb", "낮음": "#f0fdf4" };

  return (
    <div id="sec-related" style={{ marginBottom: 32 }}>
      <SectionHeader icon="🔗" title="연관 키워드" subtitle="검색 데이터 기반 관련 키워드 분석" />
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: `linear-gradient(135deg, ${C.primary}, ${C.secondary})` }}>
              {["키워드", "월간 검색량", "경쟁강도", "검색량 비율"].map(h => (
                <th key={h} style={{ padding: "14px 20px", color: "#fff", fontSize: 13, fontWeight: 600, textAlign: "left" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DUMMY.related.map((r, i) => (
              <tr key={i} style={{ borderBottom: `1px solid ${C.border}`, background: i % 2 === 0 ? "#fff" : "#f8fafc" }}>
                <td style={{ padding: "14px 20px", fontSize: 14, fontWeight: 600, color: C.text }}>{r.keyword}</td>
                <td style={{ padding: "14px 20px", fontSize: 14, color: C.text }}>{r.vol.toLocaleString()}</td>
                <td style={{ padding: "14px 20px" }}>
                  <span style={{
                    display: "inline-block", padding: "4px 12px", borderRadius: 999, fontSize: 12, fontWeight: 700,
                    background: compBg[r.comp], color: compColor[r.comp]
                  }}>{r.comp}</span>
                </td>
                <td style={{ padding: "14px 20px", width: "30%" }}>
                  <ProgressBar value={r.vol} max={89200} height={6} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function CompetitorSection() {
  const medalColors = ["#fbbf24", "#94a3b8", "#cd7f32"];
  return (
    <div id="sec-competitors" style={{ marginBottom: 32 }}>
      <SectionHeader icon="🏆" title="경쟁사 비교 분석" subtitle="상위 노출 상품 비교 (네이버 쇼핑 API 기준)" />
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: `linear-gradient(135deg, ${C.primary}, ${C.secondary})` }}>
              {["순위", "상품명", "가격", "리뷰수", "평점"].map(h => (
                <th key={h} style={{ padding: "14px 16px", color: "#fff", fontSize: 13, fontWeight: 600, textAlign: h === "상품명" ? "left" : "center" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DUMMY.competitors.map((c, i) => (
              <tr key={i} style={{ borderBottom: `1px solid ${C.border}`, background: i % 2 === 0 ? "#fff" : "#f8fafc" }}>
                <td style={{ padding: "14px 16px", textAlign: "center" }}>
                  {c.rank <= 3 ? (
                    <span style={{
                      display: "inline-flex", width: 28, height: 28, borderRadius: "50%",
                      background: medalColors[c.rank - 1], color: "#fff",
                      alignItems: "center", justifyContent: "center",
                      fontSize: 13, fontWeight: 800
                    }}>{c.rank}</span>
                  ) : (
                    <span style={{ fontSize: 14, fontWeight: 700, color: C.textSub }}>{c.rank}</span>
                  )}
                </td>
                <td style={{ padding: "14px 16px", fontSize: 14, fontWeight: 500, color: C.text }}>{c.name}</td>
                <td style={{ padding: "14px 16px", textAlign: "center", fontSize: 14, fontWeight: 600, color: C.text }}>₩{c.price}</td>
                <td style={{ padding: "14px 16px", textAlign: "center", fontSize: 14, color: C.text }}>{c.reviews.toLocaleString()}</td>
                <td style={{ padding: "14px 16px", textAlign: "center" }}>
                  <span style={{
                    display: "inline-block", padding: "4px 10px", borderRadius: 8,
                    background: "#fffbeb", fontSize: 13, fontWeight: 700, color: "#92400e"
                  }}>★ {c.rating}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function SeoSection() {
  const d = DUMMY.seo;
  const items = [
    { label: "상품명 SEO", score: d.title, max: 10 },
    { label: "상세설명", score: d.desc, max: 10 },
    { label: "태그/카테고리", score: d.tag, max: 10 },
    { label: "리뷰 점수", score: d.review, max: 10 },
    { label: "상세페이지 품질", score: d.detail, max: 10 },
  ];
  const scoreColor = d.score >= 70 ? C.success : d.score >= 40 ? C.accent : C.danger;

  return (
    <div id="sec-seo" style={{ marginBottom: 32 }}>
      <SectionHeader icon="🎯" title="SEO 종합 진단" subtitle="검색 최적화 요소별 진단 결과" />
      <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 16 }}>
        {/* 점수 원형 */}
        <Card style={{ textAlign: "center", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div style={{
            width: 120, height: 120, borderRadius: "50%",
            background: `conic-gradient(${scoreColor} ${d.score * 3.6}deg, #f1f5f9 0deg)`,
            display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12
          }}>
            <div style={{
              width: 96, height: 96, borderRadius: "50%", background: "#fff",
              display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center"
            }}>
              <div style={{ fontSize: 36, fontWeight: 800, color: scoreColor }}>{d.score}</div>
              <div style={{ fontSize: 11, color: C.textSub }}>/ 100</div>
            </div>
          </div>
          <div style={{ fontSize: 14, fontWeight: 700, color: scoreColor }}>
            {d.score >= 70 ? "양호" : d.score >= 40 ? "개선 필요" : "위험"}
          </div>
        </Card>
        {/* 항목별 바 */}
        <Card>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {items.map((item, i) => (
              <div key={i}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{item.label}</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: item.score >= 7 ? C.success : item.score >= 4 ? C.accent : C.danger }}>
                    {item.score}/{item.max}
                  </span>
                </div>
                <ProgressBar
                  value={item.score}
                  max={item.max}
                  height={10}
                  color={item.score >= 7 ? C.success : item.score >= 4 ? C.accent : C.danger}
                />
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

// ========== 메인 앱 ==========
export default function AnalysisMockupV5() {
  const [activeSection, setActiveSection] = useState("summary");
  const [darkMode, setDarkMode] = useState(false);

  return (
    <div style={{ background: C.bg, minHeight: "100vh", fontFamily: "'Noto Sans KR', -apple-system, sans-serif" }}>
      {/* 헤더 */}
      <div style={{
        background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
        position: "sticky", top: 0, zIndex: 50,
        boxShadow: "0 2px 12px rgba(0,0,0,0.25)"
      }}>
        <div style={{ maxWidth: 1200, margin: "0 auto", padding: "0 24px", display: "flex", alignItems: "center", justifyContent: "space-between", height: 64 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#fbbf24", boxShadow: "0 0 8px rgba(251,191,36,0.5)" }} />
            <span style={{ fontSize: 18, fontWeight: 700, color: "#fff" }}>로직분석</span>
            <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 999, background: "rgba(99,102,241,0.3)", color: "#c7d2fe" }}>v5.0 시안</span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {["홈", "분석", "업체관리", "사용가이드"].map((tab, i) => (
              <button key={tab} style={{
                padding: "8px 16px", borderRadius: 8, border: "none",
                background: i === 1 ? "rgba(99,102,241,0.3)" : "transparent",
                color: i === 1 ? "#fff" : "rgba(255,255,255,0.6)",
                fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit"
              }}>
                {tab}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 검색바 */}
      <div style={{ background: "#fff", padding: "20px 0 24px", borderRadius: "0 0 16px 16px", boxShadow: "0 2px 12px rgba(0,0,0,0.06)", marginBottom: 8 }}>
        <div style={{ maxWidth: 1200, margin: "0 auto", padding: "0 24px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "140px 1fr 1fr", gap: 10, marginBottom: 10 }}>
            <div>
              <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: C.textSub, marginBottom: 4 }}>업체명</label>
              <input style={{ width: "100%", height: 44, padding: "0 14px", border: `2px solid ${C.border}`, borderRadius: 10, fontSize: 13, fontFamily: "inherit", outline: "none", background: "#f9fafb" }} placeholder="보고서 표지용" />
            </div>
            <div>
              <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: C.textSub, marginBottom: 4 }}>키워드</label>
              <input defaultValue="무선 이어폰" style={{ width: "100%", height: 44, padding: "0 14px", border: `2px solid ${C.primary}`, borderRadius: 10, fontSize: 15, fontWeight: 600, fontFamily: "inherit", outline: "none", background: "#fff", boxShadow: `0 0 0 3px ${C.primary}20`, color: C.text }} />
            </div>
            <div>
              <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: C.textSub, marginBottom: 4 }}>상품 URL (선택)</label>
              <input style={{ width: "100%", height: 44, padding: "0 14px", border: `2px solid ${C.border}`, borderRadius: 10, fontSize: 12, fontFamily: "inherit", outline: "none", background: "#f9fafb" }} placeholder="광고주 상품 URL" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "end" }}>
            <div style={{ flex: 1 }}>
              <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: C.textSub, marginBottom: 4 }}>
                HTML 붙여넣기
                <span style={{ background: "#dcfce7", color: "#166534", fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 10, marginLeft: 6 }}>NEW</span>
              </label>
              <textarea style={{ width: "100%", height: 44, padding: "10px 14px", border: `2px solid ${C.border}`, borderRadius: 10, fontSize: 12, fontFamily: "inherit", outline: "none", background: "#f9fafb", resize: "none" }} placeholder="상세페이지 HTML 소스 붙여넣기 (선택)" />
            </div>
            <button style={{
              height: 44, padding: "0 32px",
              background: `linear-gradient(135deg, ${C.primary}, ${C.secondary})`,
              color: "#fff", border: "none", borderRadius: 10,
              fontSize: 15, fontWeight: 700, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap"
            }}>
              키워드 분석
            </button>
          </div>
        </div>
      </div>

      {/* 앵커 네비 */}
      <AnchorNav activeSection={activeSection} onNavigate={setActiveSection} />

      {/* 분석 결과 */}
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 24px 80px" }}>
        {/* 시안 비교 안내 배너 */}
        <div style={{
          background: "linear-gradient(135deg, #eef2ff, #e0e7ff)", borderRadius: 16,
          padding: "20px 24px", marginBottom: 32, border: "1px solid #c7d2fe"
        }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: C.primary, marginBottom: 6 }}>🎨 UI 개선 시안 v5.0</div>
          <div style={{ fontSize: 13, color: "#4338ca", lineHeight: 1.8 }}>
            이 시안은 데이터 더미로 만들어진 디자인 미리보기입니다. 실제 데이터나 기능에는 영향이 없습니다.
            <br />
            <strong>주요 변경점:</strong> 카드 호버 효과 · 그라데이션 섹션 헤더 · 도넛 경쟁강도 · SVG 트렌드 차트 · 앵커 네비 리디자인 · 테이블 스타일 통일 · 색상 팔레트 정리
          </div>
        </div>

        <SummarySection />
        <VolumeSection />
        <MarketSection />
        <CompetitionSection />
        <TrendSection />
        <RelatedSection />
        <CompetitorSection />
        <SeoSection />
      </div>
    </div>
  );
}
