import { useState, useRef } from "react";
import {
  LayoutDashboard, Users, Database, FileText, Search,
  MessageSquare, Play, Key, BarChart2, Upload, Plus,
  ChevronRight, CheckCircle, AlertCircle, XCircle, X,
  Eye, Trash2, RefreshCw, Send, Settings, Bell,
  Download, Clock, ChevronDown, Shield, Zap, BookOpen,
  Activity
} from "lucide-react";

// ── 색상 팔레트 ──────────────────────────────────────────────────
const COLOR = {
  navy: "#1F497D", blue: "#2E75B6", teal: "#0891B2",
  green: "#16A34A", amber: "#D97706", red: "#DC2626",
  purple: "#7C3AED", gray: "#6B7280",
};

// ── 공통 컴포넌트 ─────────────────────────────────────────────────
const Badge = ({ children, color = "blue" }) => {
  const cls = {
    blue:   "bg-blue-100 text-blue-800",
    green:  "bg-green-100 text-green-800",
    amber:  "bg-amber-100 text-amber-800",
    red:    "bg-red-100 text-red-800",
    purple: "bg-purple-100 text-purple-800",
    gray:   "bg-gray-100 text-gray-700",
  }[color] || "bg-gray-100 text-gray-700";
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>{children}</span>;
};

const Card = ({ children, className = "" }) => (
  <div className={`bg-white rounded-xl shadow-sm border border-gray-100 ${className}`}>{children}</div>
);

const Button = ({ children, variant = "primary", size = "md", onClick, icon: Icon, disabled = false }) => {
  const base = "inline-flex items-center gap-2 font-medium rounded-lg transition-all";
  const sizes = { sm: "px-3 py-1.5 text-sm", md: "px-4 py-2 text-sm", lg: "px-5 py-2.5 text-base" };
  const variants = {
    primary: "bg-blue-700 text-white hover:bg-blue-800 disabled:opacity-50",
    secondary: "bg-gray-100 text-gray-700 hover:bg-gray-200",
    danger: "bg-red-600 text-white hover:bg-red-700",
    ghost: "text-gray-600 hover:bg-gray-100",
    teal: "bg-teal-600 text-white hover:bg-teal-700",
  };
  return (
    <button className={`${base} ${sizes[size]} ${variants[variant]}`} onClick={onClick} disabled={disabled}>
      {Icon && <Icon size={16} />}{children}
    </button>
  );
};

const Input = ({ label, placeholder, type = "text", value, onChange, hint }) => (
  <div className="space-y-1">
    {label && <label className="block text-sm font-medium text-gray-700">{label}</label>}
    <input
      type={type}
      placeholder={placeholder}
      value={value || ""}
      onChange={onChange}
      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
    />
    {hint && <p className="text-xs text-gray-500">{hint}</p>}
  </div>
);

const ScoreBadge = ({ score }) => {
  const color = score >= 4 ? "text-green-600" : score >= 3 ? "text-amber-500" : "text-red-500";
  const bg    = score >= 4 ? "bg-green-50"   : score >= 3 ? "bg-amber-50"   : "bg-red-50";
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${color} ${bg}`}>
      {score.toFixed(1)}점
    </span>
  );
};

const SectionTitle = ({ icon: Icon, title, sub, color = COLOR.navy }) => (
  <div className="flex items-center gap-3 mb-6">
    <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: color + "15" }}>
      <Icon size={20} style={{ color }} />
    </div>
    <div>
      <h2 className="text-lg font-bold text-gray-900">{title}</h2>
      {sub && <p className="text-sm text-gray-500">{sub}</p>}
    </div>
  </div>
);

// ── 목 데이터 ─────────────────────────────────────────────────────
const SUBSCRIBERS = [
  { id: "sub_001", name: "한국통신(주)", industry: "통신", status: "active", docsCount: 12, logsCount: 48, avgScore: 4.2, lastEval: "2026-04-03" },
  { id: "sub_002", name: "서울은행",     industry: "금융", status: "active", docsCount: 8,  logsCount: 32, avgScore: 3.7, lastEval: "2026-04-02" },
  { id: "sub_003", name: "현대보험",     industry: "보험", status: "active", docsCount: 15, logsCount: 60, avgScore: 4.5, lastEval: "2026-04-03" },
  { id: "sub_004", name: "온라인마트",   industry: "유통", status: "pending", docsCount: 3,  logsCount: 0,  avgScore: 0,   lastEval: "-" },
];

const CHUNKS = [
  { id: "c001", text: "Q: 해지 위약금은 얼마인가요?\nA: 계약 잔여 기간에 따라 월 요금의 10~30%가 부과됩니다.", type: "FAQ",    score: 0.94, tokens: 42 },
  { id: "c002", text: "인터넷 요금제 변경은 고객센터(1588-0000) 또는 온라인 마이페이지에서 신청 가능합니다.", type: "매뉴얼",  score: 0.87, tokens: 38 },
  { id: "c003", text: "5G 무제한 프리미엄 요금제는 월 89,000원이며, 데이터 무제한 및 부가서비스 3종이 포함됩니다.", type: "FAQ",   score: 0.91, tokens: 51 },
  { id: "c004", text: "유심 재발급은 가까운 대리점 방문 또는 택배 서비스를 이용할 수 있습니다. 수수료는 5,000원입니다.", type: "매뉴얼", score: 0.78, tokens: 46 },
  { id: "c005", text: "로밍 서비스 신청은 출국 전 최소 24시간 전에 완료하는 것을 권장합니다.", type: "웹사이트", score: 0.83, tokens: 35 },
];

const EVAL_RESULTS = [
  { logFile: "call_log_001.txt", turns: 8, accAvg: 4.3, fluAvg: 4.1, uncertain: 0, status: "completed" },
  { logFile: "call_log_002.txt", turns: 12, accAvg: 3.6, fluAvg: 3.9, uncertain: 2, status: "completed" },
  { logFile: "call_log_003.txt", turns: 6,  accAvg: 4.8, fluAvg: 4.5, uncertain: 0, status: "completed" },
  { logFile: "call_log_004.txt", turns: 10, accAvg: 2.9, fluAvg: 3.2, uncertain: 3, status: "warning" },
];

// ── 1. 대시보드 ───────────────────────────────────────────────────
const Dashboard = ({ setPage, setSelectedSub }) => {
  const stats = [
    { label: "전체 가입자", value: "4개사", sub: "+1 이번 달",          icon: Users,     color: COLOR.blue   },
    { label: "평균 정확성", value: "4.1점", sub: "전월 대비 +0.2",     icon: BarChart2,  color: COLOR.green  },
    { label: "이번 주 평가", value: "156건", sub: "자동화 처리 완료",   icon: CheckCircle, color: COLOR.teal  },
    { label: "불확실 케이스", value: "12건", sub: "전체의 7.7%",       icon: AlertCircle, color: COLOR.amber  },
  ];
  return (
    <div className="space-y-6">
      <SectionTitle icon={LayoutDashboard} title="대시보드" sub="콜봇 품질 자동 검증 시스템 현황" />
      {/* 지표 카드 */}
      <div className="grid grid-cols-4 gap-4">
        {stats.map((s, i) => (
          <Card key={i} className="p-4">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm text-gray-500">{s.label}</p>
                <p className="text-2xl font-bold text-gray-900 mt-1">{s.value}</p>
                <p className="text-xs text-gray-400 mt-0.5">{s.sub}</p>
              </div>
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: s.color + "15" }}>
                <s.icon size={20} style={{ color: s.color }} />
              </div>
            </div>
          </Card>
        ))}
      </div>
      {/* 가입자별 현황 */}
      <Card>
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <h3 className="font-semibold text-gray-800">가입자별 품질 현황</h3>
          <Button variant="ghost" size="sm" icon={RefreshCw}>새로고침</Button>
        </div>
        <div className="divide-y divide-gray-50">
          {SUBSCRIBERS.filter(s => s.status === "active").map(sub => (
            <div key={sub.id} className="p-4 flex items-center gap-4 hover:bg-gray-50 cursor-pointer"
              onClick={() => { setSelectedSub(sub.id); setPage("results"); }}>
              <div className="w-9 h-9 rounded-lg flex items-center justify-center text-white text-sm font-bold"
                style={{ background: COLOR.navy }}>
                {sub.name[0]}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{sub.name}</span>
                  <Badge color="gray">{sub.industry}</Badge>
                </div>
                <p className="text-xs text-gray-500 mt-0.5">마지막 평가: {sub.lastEval} · 콜 로그 {sub.logsCount}건</p>
              </div>
              <div className="flex items-center gap-6">
                <div className="text-center">
                  <p className="text-xs text-gray-500">정확성</p>
                  <ScoreBadge score={sub.avgScore} />
                </div>
                <div className="w-24 h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${sub.avgScore / 5 * 100}%`, background: sub.avgScore >= 4 ? COLOR.green : sub.avgScore >= 3 ? COLOR.amber : COLOR.red }} />
                </div>
              </div>
              <ChevronRight size={16} className="text-gray-400" />
            </div>
          ))}
        </div>
      </Card>
      {/* 빠른 액션 */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "지식 베이스 등록",   icon: Database,      page: "knowledge",   color: COLOR.blue,   desc: "매뉴얼·FAQ·웹 문서 업로드" },
          { label: "콜봇 시뮬레이터",    icon: MessageSquare, page: "simulator",   color: COLOR.teal,   desc: "답변 품질 즉시 테스트" },
          { label: "평가 실행",          icon: Play,          page: "evaluation",  color: COLOR.green,  desc: "Multi-LLM 자동 평가 시작" },
        ].map((a, i) => (
          <Card key={i} className="p-4 cursor-pointer hover:shadow-md transition-shadow" onClick={() => setPage(a.page)}>
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: a.color + "15" }}>
                <a.icon size={20} style={{ color: a.color }} />
              </div>
              <div>
                <p className="font-semibold text-gray-800 text-sm">{a.label}</p>
                <p className="text-xs text-gray-500">{a.desc}</p>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};

// ── 2. 가입자 관리 ────────────────────────────────────────────────
const SubscriberManagement = () => {
  const [showForm, setShowForm] = useState(false);
  const [subs, setSubs] = useState(SUBSCRIBERS);
  const [form, setForm] = useState({ name: "", industry: "", contact: "", desc: "" });

  const handleAdd = () => {
    if (!form.name) return;
    setSubs(prev => [...prev, {
      id: `sub_00${prev.length + 1}`, name: form.name, industry: form.industry || "기타",
      status: "pending", docsCount: 0, logsCount: 0, avgScore: 0, lastEval: "-"
    }]);
    setForm({ name: "", industry: "", contact: "", desc: "" });
    setShowForm(false);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <SectionTitle icon={Users} title="가입자 관리" sub="콜봇 서비스 가입자 등록 및 관리" />
        <Button icon={Plus} onClick={() => setShowForm(true)}>가입자 추가</Button>
      </div>

      {showForm && (
        <Card className="p-5 border-2 border-blue-200">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-800">신규 가입자 등록</h3>
            <button onClick={() => setShowForm(false)}><X size={18} className="text-gray-400" /></button>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Input label="가입자명 *" placeholder="예: 한국통신(주)" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
            <Input label="업종" placeholder="예: 통신, 금융, 보험" value={form.industry} onChange={e => setForm(f => ({ ...f, industry: e.target.value }))} />
            <Input label="담당자 연락처" placeholder="예: 02-1234-5678" value={form.contact} onChange={e => setForm(f => ({ ...f, contact: e.target.value }))} />
            <Input label="메모" placeholder="특이사항 입력" value={form.desc} onChange={e => setForm(f => ({ ...f, desc: e.target.value }))} />
          </div>
          <div className="flex gap-2 mt-4">
            <Button onClick={handleAdd}>등록</Button>
            <Button variant="secondary" onClick={() => setShowForm(false)}>취소</Button>
          </div>
        </Card>
      )}

      <Card>
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {["가입자명", "업종", "상태", "도메인 문서", "콜 로그", "평균 점수", "마지막 평가", ""].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {subs.map(sub => (
              <tr key={sub.id} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-sm font-bold" style={{ background: COLOR.navy }}>{sub.name[0]}</div>
                    <div>
                      <p className="font-medium text-gray-900 text-sm">{sub.name}</p>
                      <p className="text-xs text-gray-400">{sub.id}</p>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3"><Badge color="gray">{sub.industry}</Badge></td>
                <td className="px-4 py-3">
                  <Badge color={sub.status === "active" ? "green" : "amber"}>
                    {sub.status === "active" ? "운영중" : "준비중"}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">{sub.docsCount}개</td>
                <td className="px-4 py-3 text-sm text-gray-600">{sub.logsCount}건</td>
                <td className="px-4 py-3">{sub.avgScore > 0 ? <ScoreBadge score={sub.avgScore} /> : <span className="text-xs text-gray-400">-</span>}</td>
                <td className="px-4 py-3 text-xs text-gray-500">{sub.lastEval}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-1">
                    <Button variant="ghost" size="sm" icon={Eye}>관리</Button>
                    <Button variant="ghost" size="sm" icon={Trash2}></Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
};

// ── 3. 지식 베이스 등록 ───────────────────────────────────────────
const KnowledgeBase = () => {
  const [selectedSub, setSelectedSub] = useState("sub_001");
  const [uploadedDocs, setUploadedDocs] = useState([
    { name: "서비스_이용약관_v3.pdf",  type: "매뉴얼",  size: "2.1MB", status: "indexed",  chunks: 48, date: "2026-04-01" },
    { name: "요금제_FAQ_2026.txt",    type: "FAQ",    size: "0.3MB", status: "indexed",  chunks: 32, date: "2026-04-01" },
    { name: "홈페이지_상품안내.html", type: "웹사이트", size: "1.8MB", status: "indexed",  chunks: 27, date: "2026-04-02" },
    { name: "로밍_서비스_안내.pdf",   type: "매뉴얼",  size: "0.9MB", status: "indexing", chunks: 0,  date: "2026-04-03" },
  ]);
  const [urlInput, setUrlInput] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef();

  const handleFileDrop = (e) => {
    e.preventDefault(); setDragOver(false);
    const files = Array.from(e.dataTransfer?.files || e.target.files || []);
    files.forEach(f => {
      const ext = f.name.split(".").pop().toLowerCase();
      const type = ext === "pdf" ? "매뉴얼" : ext === "txt" ? "FAQ" : "웹사이트";
      setUploadedDocs(prev => [...prev, {
        name: f.name, type, size: `${(f.size / 1048576).toFixed(1)}MB`,
        status: "indexing", chunks: 0, date: new Date().toISOString().slice(0, 10)
      }]);
    });
  };

  const statusIcon = (s) => s === "indexed"
    ? <CheckCircle size={14} className="text-green-500" />
    : <RefreshCw size={14} className="text-amber-500 animate-spin" />;

  return (
    <div className="space-y-6">
      <SectionTitle icon={Database} title="지식 베이스 등록" sub="가입자별 도메인 문서 업로드 및 임베딩 관리" color={COLOR.blue} />

      {/* 가입자 선택 */}
      <Card className="p-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">가입자 선택</label>
        <select className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={selectedSub} onChange={e => setSelectedSub(e.target.value)}>
          {SUBSCRIBERS.map(s => <option key={s.id} value={s.id}>{s.name} ({s.id})</option>)}
        </select>
      </Card>

      <div className="grid grid-cols-2 gap-6">
        {/* 파일 업로드 */}
        <div className="space-y-4">
          <h3 className="font-semibold text-gray-800">문서 업로드</h3>
          <div
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${dragOver ? "border-blue-400 bg-blue-50" : "border-gray-300 hover:border-blue-400"}`}
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleFileDrop}
            onClick={() => fileRef.current?.click()}
          >
            <Upload size={32} className="mx-auto mb-3 text-gray-400" />
            <p className="font-medium text-gray-700">파일을 드래그하거나 클릭하여 업로드</p>
            <p className="text-sm text-gray-500 mt-1">PDF, TXT, HTML 지원 · 최대 50MB</p>
            <input ref={fileRef} type="file" multiple accept=".pdf,.txt,.html,.htm" className="hidden" onChange={handleFileDrop} />
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2 p-3 bg-blue-50 rounded-lg border border-blue-100 mb-1">
              <BookOpen size={14} className="text-blue-600" />
              <span className="text-xs font-medium text-blue-700">문서 유형별 자동 청킹 적용</span>
            </div>
            {[["PDF/매뉴얼", "계층적 3단계 청킹 (섹션→문단→문장)"],
              ["FAQ(TXT)", "Q&A 쌍 단위 보존"],
              ["웹사이트(HTML)", "Semantic Chunking (의미 경계 탐지)"]].map(([t, d]) => (
              <div key={t} className="flex items-start gap-2">
                <ChevronRight size={14} className="text-blue-500 mt-0.5 flex-shrink-0" />
                <div><span className="text-sm font-medium text-gray-700">{t}: </span>
                  <span className="text-sm text-gray-500">{d}</span></div>
              </div>
            ))}
          </div>

          {/* URL 등록 */}
          <div className="pt-2 border-t border-gray-100">
            <p className="text-sm font-medium text-gray-700 mb-2">웹사이트 URL 등록</p>
            <div className="flex gap-2">
              <input value={urlInput} onChange={e => setUrlInput(e.target.value)}
                placeholder="https://www.example.com/support"
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <Button size="sm" onClick={() => setUrlInput("")}>크롤링</Button>
            </div>
          </div>
        </div>

        {/* 등록된 문서 목록 */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-800">등록된 문서 ({uploadedDocs.length}개)</h3>
            <Button variant="secondary" size="sm" icon={RefreshCw}>전체 재인덱싱</Button>
          </div>
          <div className="space-y-2">
            {uploadedDocs.map((doc, i) => (
              <Card key={i} className="p-3">
                <div className="flex items-center gap-3">
                  <FileText size={16} className="text-gray-400 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-gray-800 truncate">{doc.name}</p>
                      <Badge color={doc.type === "FAQ" ? "blue" : doc.type === "매뉴얼" ? "purple" : "green"}>{doc.type}</Badge>
                    </div>
                    <div className="flex items-center gap-3 mt-0.5">
                      <span className="text-xs text-gray-400">{doc.size}</span>
                      {doc.status === "indexed" && <span className="text-xs text-green-600">청크 {doc.chunks}개</span>}
                      <span className="text-xs text-gray-400">{doc.date}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {statusIcon(doc.status)}
                    <span className="text-xs text-gray-500">{doc.status === "indexed" ? "완료" : "처리중"}</span>
                    <button className="text-gray-400 hover:text-red-500"><Trash2 size={14} /></button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// ── 4. 콜봇 이력 등록 ────────────────────────────────────────────
const CallLogRegistration = () => {
  const [selectedSub, setSelectedSub] = useState("sub_001");
  const [logs, setLogs] = useState([
    { name: "call_log_20260401_001.txt", turns: 14, date: "2026-04-01", status: "ready" },
    { name: "call_log_20260401_002.txt", turns: 9,  date: "2026-04-01", status: "evaluated" },
    { name: "call_log_20260402_003.txt", turns: 18, date: "2026-04-02", status: "ready" },
  ]);
  const [textInput, setTextInput] = useState("");
  const [preview, setPreview] = useState([
    { role: "고객", text: "안녕하세요. 요금제 변경하고 싶어요." },
    { role: "콜봇", text: "안녕하세요! 고객님, 요금제 변경을 도와드리겠습니다. 어떤 요금제로 변경을 원하시나요?" },
    { role: "고객", text: "5G 무제한으로 바꾸고 싶은데 얼마예요?" },
    { role: "콜봇", text: "5G 무제한 프리미엄 요금제는 월 89,000원입니다. 데이터 무제한 및 부가서비스 3종이 포함됩니다." },
  ]);

  return (
    <div className="space-y-6">
      <SectionTitle icon={FileText} title="콜봇 답변 이력 등록" sub="평가 대상 콜 로그 업로드 및 관리" color={COLOR.purple} />

      <Card className="p-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">가입자 선택</label>
        <select className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={selectedSub} onChange={e => setSelectedSub(e.target.value)}>
          {SUBSCRIBERS.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </Card>

      <div className="grid grid-cols-2 gap-6">
        <div className="space-y-4">
          <h3 className="font-semibold text-gray-800">로그 파일 업로드</h3>
          <div className="border-2 border-dashed border-gray-300 rounded-xl p-6 text-center hover:border-purple-400 cursor-pointer transition-colors">
            <Upload size={28} className="mx-auto mb-2 text-gray-400" />
            <p className="font-medium text-gray-700 text-sm">콜 로그 파일 업로드</p>
            <p className="text-xs text-gray-500 mt-1">TXT, JSON 지원</p>
          </div>

          {/* 형식 안내 */}
          <Card className="p-4 bg-gray-50">
            <p className="text-xs font-semibold text-gray-600 mb-2">📋 지원 파일 형식</p>
            <div className="bg-white rounded-lg p-3 font-mono text-xs text-gray-700 space-y-1 border border-gray-200">
              <p className="text-purple-600"># 텍스트 형식 (권장)</p>
              <p>고객|안녕하세요. 요금제 변경...</p>
              <p>콜봇|안녕하세요! 요금제 변경을...</p>
              <p>고객|5G 무제한으로 바꾸고 싶...</p>
            </div>
          </Card>

          {/* 직접 입력 */}
          <div>
            <p className="text-sm font-medium text-gray-700 mb-2">직접 붙여넣기</p>
            <textarea value={textInput} onChange={e => setTextInput(e.target.value)}
              placeholder={"고객|질문 내용\n콜봇|답변 내용\n고객|추가 질문"}
              rows={5}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-400" />
            <Button size="sm" className="mt-2" onClick={() => {}}>파싱 미리보기</Button>
          </div>
        </div>

        <div className="space-y-4">
          {/* 미리보기 */}
          <div>
            <h3 className="font-semibold text-gray-800 mb-3">파싱 미리보기</h3>
            <Card className="p-4">
              <div className="space-y-3 max-h-48 overflow-y-auto">
                {preview.map((t, i) => (
                  <div key={i} className={`flex gap-2 ${t.role === "콜봇" ? "flex-row-reverse" : ""}`}>
                    <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${t.role === "콜봇" ? "bg-blue-700 text-white" : "bg-gray-200 text-gray-700"}`}>
                      {t.role[0]}
                    </div>
                    <div className={`px-3 py-2 rounded-lg text-xs max-w-xs ${t.role === "콜봇" ? "bg-blue-50 text-blue-900" : "bg-gray-100 text-gray-800"}`}>
                      {t.text}
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-3 pt-3 border-t border-gray-100 flex items-center justify-between text-xs text-gray-500">
                <span>총 {preview.length}턴 파싱됨</span>
                <Badge color="green">파싱 성공</Badge>
              </div>
            </Card>
          </div>

          {/* 등록된 로그 */}
          <div>
            <h3 className="font-semibold text-gray-800 mb-3">등록된 로그 ({logs.length}건)</h3>
            <div className="space-y-2">
              {logs.map((log, i) => (
                <Card key={i} className="p-3 flex items-center gap-3">
                  <FileText size={14} className="text-gray-400" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-gray-800">{log.name}</p>
                    <p className="text-xs text-gray-500">{log.turns}턴 · {log.date}</p>
                  </div>
                  <Badge color={log.status === "evaluated" ? "green" : "blue"}>
                    {log.status === "evaluated" ? "평가완료" : "대기중"}
                  </Badge>
                </Card>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// ── 5. 임베딩 검증 ────────────────────────────────────────────────
const EmbeddingVerification = () => {
  const [selectedSub, setSelectedSub] = useState("sub_001");
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState(false);
  const [searchResults, setSearchResults] = useState([]);

  const handleSearch = () => {
    if (!query) return;
    setSearched(true);
    setSearchResults([
      { ...CHUNKS[0], similarity: 0.94, stage: "HyDE + Dense" },
      { ...CHUNKS[2], similarity: 0.88, stage: "멀티쿼리" },
      { ...CHUNKS[1], similarity: 0.82, stage: "Dense" },
    ]);
  };

  return (
    <div className="space-y-6">
      <SectionTitle icon={Search} title="임베딩 검증" sub="문서 임베딩 품질 확인 및 유사도 검색 테스트" color={COLOR.teal} />

      <Card className="p-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">가입자 선택</label>
        <select className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={selectedSub} onChange={e => setSelectedSub(e.target.value)}>
          {SUBSCRIBERS.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </Card>

      {/* 인덱스 현황 */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "전체 청크", value: "107개", icon: Database, color: COLOR.blue },
          { label: "자식 청크 (검색용)", value: "89개", icon: Search,   color: COLOR.teal },
          { label: "부모 청크 (컨텍스트용)", value: "18개", icon: BookOpen, color: COLOR.purple },
        ].map((s, i) => (
          <Card key={i} className="p-4 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: s.color + "15" }}>
              <s.icon size={18} style={{ color: s.color }} />
            </div>
            <div>
              <p className="text-xs text-gray-500">{s.label}</p>
              <p className="text-xl font-bold text-gray-900">{s.value}</p>
            </div>
          </Card>
        ))}
      </div>

      {/* 청크 목록 */}
      <Card>
        <div className="p-4 border-b border-gray-100">
          <h3 className="font-semibold text-gray-800">청크 목록</h3>
        </div>
        <div className="divide-y divide-gray-50">
          {CHUNKS.map(c => (
            <div key={c.id} className="p-4 hover:bg-gray-50">
              <div className="flex items-start gap-3">
                <Badge color={c.type === "FAQ" ? "blue" : c.type === "매뉴얼" ? "purple" : "green"}>{c.type}</Badge>
                <p className="text-sm text-gray-700 flex-1 whitespace-pre-line">{c.text}</p>
                <div className="text-right flex-shrink-0">
                  <p className="text-xs text-gray-500">{c.tokens}토큰</p>
                  <div className="flex items-center gap-1 mt-1">
                    <div className="w-16 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full bg-teal-500 rounded-full" style={{ width: `${c.score * 100}%` }} />
                    </div>
                    <span className="text-xs font-medium text-teal-600">{(c.score * 100).toFixed(0)}%</span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* 유사도 검색 테스트 */}
      <Card className="p-5">
        <h3 className="font-semibold text-gray-800 mb-4">🔍 유사도 검색 테스트 (HyDE + 2단계 리랭킹)</h3>
        <div className="flex gap-2 mb-4">
          <input value={query} onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSearch()}
            placeholder="검색 쿼리 입력 예: 해지 위약금은 얼마인가요?"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-400" />
          <Button variant="teal" icon={Search} onClick={handleSearch}>검색</Button>
        </div>
        {searched && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 p-2 bg-teal-50 rounded-lg text-xs text-teal-700">
              <Zap size={12} />
              HyDE 가상 답변 생성 완료 → Dense+BM25 Top-20 검색 → Cross-Encoder 리랭킹 → Top-3 결과
            </div>
            {searchResults.map((r, i) => (
              <div key={i} className="flex items-start gap-3 p-3 border border-gray-100 rounded-lg">
                <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: i === 0 ? COLOR.teal : "#f3f4f6", color: i === 0 ? "white" : COLOR.gray }}>
                  {i + 1}
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge color={r.type === "FAQ" ? "blue" : r.type === "매뉴얼" ? "purple" : "green"}>{r.type}</Badge>
                    <Badge color="gray">{r.stage}</Badge>
                  </div>
                  <p className="text-sm text-gray-700 whitespace-pre-line">{r.text}</p>
                </div>
                <div className="text-right flex-shrink-0">
                  <p className="text-lg font-bold" style={{ color: r.similarity > 0.9 ? COLOR.green : COLOR.amber }}>
                    {(r.similarity * 100).toFixed(0)}%
                  </p>
                  <p className="text-xs text-gray-400">유사도</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};

// ── 6. 콜봇 시뮬레이터 ────────────────────────────────────────────
const Simulator = () => {
  const [selectedSub, setSelectedSub] = useState("sub_001");
  const [messages, setMessages] = useState([
    { role: "bot", text: "안녕하세요! 무엇을 도와드릴까요?" }
  ]);
  const [input, setInput] = useState("");
  const [showRef, setShowRef] = useState(null);

  const BOT_RESPONSES = [
    { text: "5G 무제한 프리미엄 요금제는 월 89,000원이며, 데이터 무제한과 부가서비스 3종이 포함됩니다.", ref: CHUNKS[2], acc: 4.8, flu: 4.5 },
    { text: "해지 위약금은 계약 잔여 기간에 따라 월 요금의 10~30%가 부과됩니다. 자세한 금액은 마이페이지에서 확인하실 수 있습니다.", ref: CHUNKS[0], acc: 4.6, flu: 4.3 },
    { text: "요금제 변경은 고객센터(1588-0000) 또는 온라인 마이페이지에서 신청 가능합니다.", ref: CHUNKS[1], acc: 4.4, flu: 4.1 },
    { text: "죄송합니다. 해당 내용은 저희 서비스 범위 밖입니다. 다른 도움이 필요하신가요?", ref: null, acc: 3.2, flu: 3.8 },
  ];
  let botIdx = 0;

  const sendMessage = () => {
    if (!input.trim()) return;
    const userMsg = { role: "user", text: input };
    const botResp = BOT_RESPONSES[botIdx % BOT_RESPONSES.length];
    botIdx++;
    setMessages(prev => [...prev, userMsg, {
      role: "bot", text: botResp.text, ref: botResp.ref,
      scores: { acc: botResp.acc, flu: botResp.flu }
    }]);
    setInput("");
  };

  return (
    <div className="space-y-6">
      <SectionTitle icon={MessageSquare} title="콜봇 시뮬레이터" sub="지식 베이스 기반 콜봇 답변 실시간 테스트" color={COLOR.teal} />

      <div className="grid grid-cols-3 gap-6">
        {/* 채팅창 */}
        <div className="col-span-2 space-y-4">
          <Card className="p-4">
            <div className="flex items-center justify-between mb-3">
              <select className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
                value={selectedSub} onChange={e => setSelectedSub(e.target.value)}>
                {SUBSCRIBERS.filter(s => s.status === "active").map(s => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
              <Badge color="green">지식 베이스 연결됨</Badge>
            </div>
            {/* 대화창 */}
            <div className="h-72 overflow-y-auto space-y-3 p-2 bg-gray-50 rounded-lg">
              {messages.map((m, i) => (
                <div key={i} className={`flex gap-2 ${m.role === "bot" ? "" : "flex-row-reverse"}`}>
                  <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${m.role === "bot" ? "bg-blue-700 text-white" : "bg-gray-300 text-gray-700"}`}>
                    {m.role === "bot" ? "B" : "U"}
                  </div>
                  <div className="max-w-xs">
                    <div className={`px-3 py-2 rounded-lg text-sm ${m.role === "bot" ? "bg-white border border-gray-200" : "bg-blue-700 text-white"}`}>
                      {m.text}
                    </div>
                    {m.scores && (
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-gray-400">정확성</span>
                        <ScoreBadge score={m.scores.acc} />
                        <span className="text-xs text-gray-400">흐름</span>
                        <ScoreBadge score={m.scores.flu} />
                        {m.ref && (
                          <button className="text-xs text-blue-500 hover:underline" onClick={() => setShowRef(showRef === i ? null : i)}>
                            참조 보기
                          </button>
                        )}
                      </div>
                    )}
                    {showRef === i && m.ref && (
                      <div className="mt-2 p-2 bg-teal-50 rounded text-xs text-teal-800 border border-teal-200">
                        <p className="font-semibold mb-1">📄 참조 문서 ({m.ref.type})</p>
                        <p>{m.ref.text}</p>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex gap-2 mt-3">
              <input value={input} onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === "Enter" && sendMessage()}
                placeholder="고객 질문을 입력하세요..."
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <Button icon={Send} onClick={sendMessage}>전송</Button>
            </div>
          </Card>

          {/* 빠른 테스트 질문 */}
          <Card className="p-4">
            <p className="text-sm font-medium text-gray-700 mb-2">빠른 테스트 질문</p>
            <div className="flex flex-wrap gap-2">
              {["해지 위약금 얼마예요?", "5G 요금제 가격?", "요금제 변경 방법?", "유심 재발급 방법?", "로밍 신청은?"].map(q => (
                <button key={q} onClick={() => { setInput(q); }}
                  className="px-3 py-1.5 bg-gray-100 hover:bg-blue-50 hover:text-blue-700 rounded-full text-xs text-gray-600 transition-colors">
                  {q}
                </button>
              ))}
            </div>
          </Card>
        </div>

        {/* 실시간 평가 정보 */}
        <div className="space-y-4">
          <Card className="p-4">
            <h4 className="font-semibold text-gray-800 mb-3">⚡ 실시간 평가 정보</h4>
            <div className="space-y-3">
              <div>
                <p className="text-xs text-gray-500 mb-1">검색 파이프라인</p>
                {["대화 인식 쿼리 구성", "HyDE 가상 답변 생성", "멀티쿼리 확장", "Top-20 검색", "Cross-Encoder 리랭킹"].map((s, i) => (
                  <div key={i} className="flex items-center gap-2 py-1">
                    <CheckCircle size={12} className="text-green-500" />
                    <span className="text-xs text-gray-600">{s}</span>
                  </div>
                ))}
              </div>
              <div className="pt-3 border-t border-gray-100">
                <p className="text-xs text-gray-500 mb-2">세션 통계</p>
                <div className="grid grid-cols-2 gap-2">
                  {[["메시지", `${messages.filter(m => m.role === "bot").length}건`],
                    ["평균 정확성", "4.3점"],
                    ["평균 흐름", "4.2점"],
                    ["참조 청크", "3.1개"],
                  ].map(([k, v]) => (
                    <div key={k} className="bg-gray-50 rounded-lg p-2 text-center">
                      <p className="text-xs text-gray-500">{k}</p>
                      <p className="text-sm font-bold text-gray-800">{v}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};

// ── 7. 평가 실행 ──────────────────────────────────────────────────
const EvaluationRunner = () => {
  const [status, setStatus] = useState("idle"); // idle | running | done
  const [progress, setProgress] = useState({ step: 0, pct: 0 });
  const [selectedSub, setSelectedSub] = useState("sub_001");

  const STEPS = [
    { label: "CP1 데이터 전처리",            desc: "콜 로그 파싱 및 구조화" },
    { label: "CP2 지식 베이스 확인",          desc: "변경된 문서 재인덱싱" },
    { label: "CP3 컨텍스트 검색",             desc: "HyDE · 멀티쿼리 · 리랭킹" },
    { label: "CP4 Multi-LLM 합의 평가",       desc: "Claude · GPT-4o · Gemini 병렬 호출" },
    { label: "CP5 결과 집계 및 분석",         desc: "점수 집계 · 패턴 분석" },
    { label: "CP6 Confluence 보고서 발행",    desc: "자동 보고서 게시" },
  ];

  const handleRun = () => {
    setStatus("running");
    setProgress({ step: 0, pct: 0 });
    let step = 0; let pct = 0;
    const iv = setInterval(() => {
      pct += 4;
      if (pct >= 100) { pct = 0; step++; }
      if (step >= STEPS.length) { clearInterval(iv); setStatus("done"); setProgress({ step: STEPS.length, pct: 100 }); return; }
      setProgress({ step, pct });
    }, 120);
  };

  return (
    <div className="space-y-6">
      <SectionTitle icon={Play} title="평가 실행" sub="Multi-LLM 자동 평가 파이프라인 실행" color={COLOR.green} />

      <div className="grid grid-cols-2 gap-6">
        <div className="space-y-4">
          <Card className="p-5">
            <h3 className="font-semibold text-gray-800 mb-4">실행 설정</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">가입자 선택</label>
                <select className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
                  value={selectedSub} onChange={e => setSelectedSub(e.target.value)}>
                  <option value="all">전체 가입자</option>
                  {SUBSCRIBERS.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">평가 대상 로그</label>
                <select className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm">
                  <option>미평가 로그 전체 (3건)</option>
                  <option>전체 로그 재평가</option>
                  <option>날짜 범위 선택</option>
                </select>
              </div>
              <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                <input type="checkbox" id="reindex" className="rounded" />
                <label htmlFor="reindex" className="text-sm text-gray-700">지식 베이스 재구축 포함</label>
              </div>
              <Button
                icon={status === "running" ? RefreshCw : Play}
                disabled={status === "running"}
                onClick={handleRun}
                className="w-full justify-center"
              >
                {status === "running" ? "실행 중..." : status === "done" ? "재실행" : "평가 시작"}
              </Button>
            </div>
          </Card>
        </div>

        {/* 진행 상황 */}
        <Card className="p-5">
          <h3 className="font-semibold text-gray-800 mb-4">진행 현황</h3>
          <div className="space-y-3">
            {STEPS.map((step, i) => {
              const done   = i < progress.step;
              const active = i === progress.step && status === "running";
              const pend   = i > progress.step || status === "idle";
              return (
                <div key={i} className={`flex items-start gap-3 p-3 rounded-lg transition-colors ${active ? "bg-blue-50" : done ? "bg-green-50" : "bg-gray-50"}`}>
                  <div className="mt-0.5">
                    {done   ? <CheckCircle size={16} className="text-green-500" /> :
                     active ? <RefreshCw size={16} className="text-blue-500 animate-spin" /> :
                              <div className="w-4 h-4 rounded-full border-2 border-gray-300" />}
                  </div>
                  <div className="flex-1">
                    <p className={`text-sm font-medium ${done ? "text-green-700" : active ? "text-blue-700" : "text-gray-500"}`}>
                      {step.label}
                    </p>
                    <p className="text-xs text-gray-400">{step.desc}</p>
                    {active && (
                      <div className="mt-2 h-1.5 bg-blue-100 rounded-full overflow-hidden">
                        <div className="h-full bg-blue-500 rounded-full transition-all" style={{ width: `${progress.pct}%` }} />
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {status === "done" && (
            <div className="mt-4 p-3 bg-green-50 rounded-lg border border-green-200 text-sm text-green-700 text-center font-medium">
              ✅ 평가 완료! Confluence 보고서가 발행되었습니다.
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};

// ── 8. 평가 결과 ──────────────────────────────────────────────────
const EvaluationResults = ({ selectedSub }) => {
  const sub = SUBSCRIBERS.find(s => s.id === selectedSub) || SUBSCRIBERS[0];
  const [activeLog, setActiveLog] = useState(null);
  const TURNS = [
    { idx: 1, q: "요금제 변경 방법이 어떻게 되나요?", a: "고객센터 또는 마이페이지에서 가능합니다.", acc: 4.3, flu: 4.1, uncertain: false },
    { idx: 3, q: "해지 위약금이 얼마예요?",            a: "잔여 기간에 따라 10~30%가 부과됩니다.",    acc: 4.6, flu: 4.2, uncertain: false },
    { idx: 5, q: "5G 무제한 요금제 가격은?",           a: "월 89,000원입니다.",                       acc: 4.8, flu: 4.5, uncertain: false },
    { idx: 7, q: "유심 분실 신고 방법은?",             a: "홈페이지나 고객센터로 문의하세요.",         acc: 2.8, flu: 3.1, uncertain: true  },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <SectionTitle icon={BarChart2} title={`평가 결과 — ${sub.name}`} sub="Multi-LLM 합의 평가 상세 결과" color={COLOR.blue} />
        <Button variant="secondary" icon={Download}>결과 다운로드</Button>
      </div>

      {/* 요약 */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "평균 정확성", value: `${sub.avgScore}점`, color: COLOR.blue },
          { label: "평균 흐름",   value: "4.1점",             color: COLOR.teal },
          { label: "평가 대화",   value: `${sub.logsCount}건`, color: COLOR.green },
          { label: "불확실 케이스", value: "12건 (7.7%)",     color: COLOR.amber },
        ].map((s, i) => (
          <Card key={i} className="p-4 text-center">
            <p className="text-xs text-gray-500">{s.label}</p>
            <p className="text-2xl font-bold mt-1" style={{ color: s.color }}>{s.value}</p>
          </Card>
        ))}
      </div>

      {/* 로그별 결과 */}
      <div className="grid grid-cols-2 gap-6">
        <div>
          <h3 className="font-semibold text-gray-800 mb-3">대화별 점수</h3>
          <div className="space-y-2">
            {EVAL_RESULTS.map((log, i) => (
              <Card key={i} className={`p-3 cursor-pointer hover:shadow-md transition-shadow ${activeLog === i ? "border-blue-300 border" : ""}`}
                onClick={() => setActiveLog(activeLog === i ? null : i)}>
                <div className="flex items-center gap-3">
                  <FileText size={14} className="text-gray-400" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-gray-800">{log.logFile}</p>
                    <p className="text-xs text-gray-500">{log.turns}턴</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <ScoreBadge score={log.accAvg} />
                    {log.uncertain > 0 && <Badge color="amber">불확실 {log.uncertain}건</Badge>}
                    {log.status === "warning" && <AlertCircle size={14} className="text-amber-500" />}
                  </div>
                </div>
                {activeLog === i && (
                  <div className="mt-3 pt-3 border-t border-gray-100 space-y-2">
                    {TURNS.map((t, ti) => (
                      <div key={ti} className={`p-2 rounded-lg text-xs ${t.uncertain ? "bg-amber-50 border border-amber-200" : "bg-gray-50"}`}>
                        <p className="text-gray-600 mb-1">Turn {t.idx}: {t.q}</p>
                        <p className="text-gray-800">{t.a}</p>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-gray-400">정확성</span><ScoreBadge score={t.acc} />
                          <span className="text-gray-400">흐름</span><ScoreBadge score={t.flu} />
                          {t.uncertain && <Badge color="amber">⚠ 불확실</Badge>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            ))}
          </div>
        </div>
        {/* 패턴 분석 */}
        <div>
          <h3 className="font-semibold text-gray-800 mb-3">낮은 점수 패턴 분석</h3>
          <Card className="p-4 space-y-3">
            {[
              { issue: "유심/단말 관련 오정보",  count: 7, avg: 2.4, color: COLOR.red    },
              { issue: "요금 계산 오류",         count: 4, avg: 2.8, color: COLOR.amber  },
              { issue: "정책 변경 미반영",        count: 3, avg: 3.1, color: COLOR.amber  },
            ].map((p, i) => (
              <div key={i}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm text-gray-700">{p.issue}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">{p.count}건</span>
                    <ScoreBadge score={p.avg} />
                  </div>
                </div>
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${p.avg / 5 * 100}%`, background: p.color }} />
                </div>
              </div>
            ))}
          </Card>
          <Card className="p-4 mt-4">
            <h4 className="font-semibold text-gray-800 mb-3">불확실 케이스 목록</h4>
            <div className="space-y-2">
              {[
                { q: "유심 분실 신고 방법", claude: 3, gpt: 5, gemini: 2 },
                { q: "요금 환불 기간",      claude: 2, gpt: 4, gemini: 3 },
              ].map((c, i) => (
                <div key={i} className="p-3 bg-amber-50 border border-amber-200 rounded-lg">
                  <p className="text-xs font-medium text-amber-800 mb-2">⚠ {c.q}</p>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    {[["Claude", c.claude], ["GPT-4o", c.gpt], ["Gemini", c.gemini]].map(([m, sc]) => (
                      <div key={m}>
                        <p className="text-xs text-gray-500">{m}</p>
                        <ScoreBadge score={sc} />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};

// ── 9. AI API 키 설정 ─────────────────────────────────────────────
const APIKeySettings = () => {
  const [keys, setKeys] = useState({
    anthropic: "", openai: "", google: "",
    confluenceUrl: "", confluenceUser: "", confluenceToken: "", confluenceSpace: "",
  });
  const [show, setShow] = useState({});
  const [saved, setSaved] = useState(false);

  const handleSave = () => { setSaved(true); setTimeout(() => setSaved(false), 2000); };

  const KeyField = ({ id, label, placeholder, hint }) => (
    <div className="space-y-1">
      <label className="block text-sm font-medium text-gray-700">{label}</label>
      <div className="relative">
        <input
          type={show[id] ? "text" : "password"}
          value={keys[id]}
          onChange={e => setKeys(k => ({ ...k, [id]: e.target.value }))}
          placeholder={placeholder}
          className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
        />
        <button className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400"
          onClick={() => setShow(s => ({ ...s, [id]: !s[id] }))}>
          <Eye size={14} />
        </button>
      </div>
      {hint && <p className="text-xs text-gray-400">{hint}</p>}
    </div>
  );

  return (
    <div className="space-y-6">
      <SectionTitle icon={Key} title="AI API 키 설정" sub="LLM 평가 및 Confluence 연동에 필요한 API 키 관리" color={COLOR.navy} />

      <div className="grid grid-cols-2 gap-6">
        {/* LLM API */}
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center"><Shield size={16} className="text-blue-600" /></div>
            <h3 className="font-semibold text-gray-800">LLM API 키 (CP4 평가 심판)</h3>
          </div>
          <div className="space-y-4">
            <KeyField id="anthropic" label="Anthropic API Key (Claude — 주 평가 모델)"
              placeholder="sk-ant-api03-..." hint="claude-opus-4-6 사용" />
            <KeyField id="openai" label="OpenAI API Key (GPT-4o)"
              placeholder="sk-proj-..." hint="gpt-4o, text-embedding-3-large 사용" />
            <KeyField id="google" label="Google AI API Key (Gemini 1.5 Pro)"
              placeholder="AIza..." hint="gemini-1.5-pro-latest 사용" />
          </div>
          {/* 연결 상태 */}
          <div className="mt-4 pt-4 border-t border-gray-100 space-y-2">
            {[["Claude", keys.anthropic, COLOR.navy], ["GPT-4o", keys.openai, "#10A37F"], ["Gemini", keys.google, COLOR.amber]].map(([m, k, c]) => (
              <div key={m} className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${k ? "bg-green-500" : "bg-gray-300"}`} />
                <span className="text-xs" style={{ color: k ? c : COLOR.gray }}>{m}</span>
                <span className="text-xs text-gray-400">{k ? "연결됨" : "미설정"}</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Confluence */}
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-lg bg-teal-50 flex items-center justify-center"><Activity size={16} className="text-teal-600" /></div>
            <h3 className="font-semibold text-gray-800">Confluence 연동 (CP6 보고서 발행)</h3>
          </div>
          <div className="space-y-4">
            <KeyField id="confluenceUrl"   label="Confluence URL"       placeholder="https://company.atlassian.net" />
            <KeyField id="confluenceUser"  label="사용자 이메일"         placeholder="admin@company.com" />
            <KeyField id="confluenceToken" label="API Token"            placeholder="ATATT3x..." hint="Atlassian 계정 설정에서 발급" />
            <Input label="스페이스 키" placeholder="QA" />
          </div>
          <div className="mt-4">
            <Button variant="secondary" size="sm" icon={RefreshCw}>연결 테스트</Button>
          </div>
        </Card>
      </div>

      {/* 환경 변수 미리보기 */}
      <Card className="p-5">
        <h3 className="font-semibold text-gray-800 mb-3">.env 파일 미리보기</h3>
        <div className="bg-gray-900 rounded-lg p-4 font-mono text-sm">
          {[
            ["# Anthropic", ""],
            ["ANTHROPIC_API_KEY", keys.anthropic || "sk-ant-api03-..."],
            ["# OpenAI", ""],
            ["OPENAI_API_KEY", keys.openai || "sk-proj-..."],
            ["# Google AI", ""],
            ["GOOGLE_API_KEY", keys.google || "AIza..."],
            ["# Confluence", ""],
            ["CONFLUENCE_URL", keys.confluenceUrl || "https://company.atlassian.net"],
            ["CONFLUENCE_API_TOKEN", keys.confluenceToken || "ATATT3x..."],
          ].map(([k, v], i) => (
            <div key={i} className={k.startsWith("#") ? "text-gray-500 mt-2" : "text-green-300"}>
              {k.startsWith("#") ? k : <><span className="text-blue-300">{k}</span>=<span className="text-yellow-200">{v}</span></>}
            </div>
          ))}
        </div>
      </Card>

      <div className="flex gap-3">
        <Button icon={CheckCircle} onClick={handleSave}>
          {saved ? "저장 완료!" : "설정 저장"}
        </Button>
        <Button variant="secondary" icon={Download}>
          .env 파일 다운로드
        </Button>
      </div>
    </div>
  );
};

// ── 10. 알림 & 모니터링 ───────────────────────────────────────────
const Monitoring = () => {
  const alerts = [
    { type: "error",   sub: "서울은행",   msg: "평균 정확성 3.7점 → 2.9점 급락 감지",       time: "10분 전" },
    { type: "warning", sub: "한국통신(주)", msg: "불확실 케이스 비율 12% (임계값 10% 초과)", time: "1시간 전" },
    { type: "info",    sub: "현대보험",   msg: "평가 완료 — 평균 4.5점 (우수)",              time: "3시간 전" },
    { type: "warning", sub: "온라인마트",  msg: "지식 베이스 미구축. 평가 불가 상태",         time: "1일 전" },
  ];
  const iconMap = { error: XCircle, warning: AlertCircle, info: CheckCircle };
  const colorMap = { error: "text-red-500", warning: "text-amber-500", info: "text-green-500" };
  const bgMap    = { error: "bg-red-50",    warning: "bg-amber-50",    info: "bg-green-50"    };

  return (
    <div className="space-y-6">
      <SectionTitle icon={Bell} title="알림 & 모니터링" sub="품질 이상 감지 및 자동 알림" color={COLOR.amber} />
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "미해결 알림", value: "3건",  color: COLOR.red,   icon: XCircle },
          { label: "경고",        value: "2건",  color: COLOR.amber, icon: AlertCircle },
          { label: "정상",        value: "2개사", color: COLOR.green, icon: CheckCircle },
        ].map((s, i) => (
          <Card key={i} className="p-4 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: s.color + "15" }}>
              <s.icon size={18} style={{ color: s.color }} />
            </div>
            <div>
              <p className="text-xs text-gray-500">{s.label}</p>
              <p className="text-xl font-bold text-gray-900">{s.value}</p>
            </div>
          </Card>
        ))}
      </div>
      <Card>
        <div className="p-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="font-semibold text-gray-800">최근 알림</h3>
          <Button variant="ghost" size="sm">모두 읽음 처리</Button>
        </div>
        <div className="divide-y divide-gray-50">
          {alerts.map((a, i) => {
            const Icon = iconMap[a.type];
            return (
              <div key={i} className={`p-4 flex items-start gap-3 ${bgMap[a.type]}`}>
                <Icon size={16} className={colorMap[a.type] + " mt-0.5 flex-shrink-0"} />
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm font-medium text-gray-900">{a.sub}</span>
                    <Badge color={a.type === "error" ? "red" : a.type === "warning" ? "amber" : "green"}>
                      {a.type === "error" ? "오류" : a.type === "warning" ? "경고" : "정상"}
                    </Badge>
                  </div>
                  <p className="text-sm text-gray-600">{a.msg}</p>
                </div>
                <span className="text-xs text-gray-400 flex-shrink-0">{a.time}</span>
              </div>
            );
          })}
        </div>
      </Card>
      {/* 알림 임계값 설정 */}
      <Card className="p-5">
        <h3 className="font-semibold text-gray-800 mb-4">알림 임계값 설정</h3>
        <div className="grid grid-cols-2 gap-4">
          <Input label="정확성 점수 하한 알림" placeholder="예: 3.0" hint="이 점수 이하로 떨어지면 알림 발송" />
          <Input label="불확실 케이스 비율 상한" placeholder="예: 10%" hint="이 비율 초과 시 경고 알림" />
          <Input label="평가 미실시 경과일" placeholder="예: 3일" hint="마지막 평가 후 N일 경과 시 알림" />
          <Input label="Slack 웹훅 URL (선택)" placeholder="https://hooks.slack.com/..." hint="알림을 Slack으로도 수신" />
        </div>
        <Button className="mt-4" icon={CheckCircle}>임계값 저장</Button>
      </Card>
    </div>
  );
};

// ── 메인 앱 ──────────────────────────────────────────────────────
const NAV = [
  { id: "dashboard",   label: "대시보드",          icon: LayoutDashboard, group: "overview" },
  { id: "subscribers", label: "가입자 관리",        icon: Users,           group: "overview" },
  { id: "knowledge",   label: "지식 베이스 등록",   icon: Database,        group: "data" },
  { id: "calllogs",    label: "콜봇 이력 등록",     icon: FileText,        group: "data" },
  { id: "embedding",   label: "임베딩 검증",        icon: Search,          group: "data" },
  { id: "simulator",   label: "콜봇 시뮬레이터",    icon: MessageSquare,   group: "eval" },
  { id: "evaluation",  label: "평가 실행",          icon: Play,            group: "eval" },
  { id: "results",     label: "평가 결과",          icon: BarChart2,       group: "eval" },
  { id: "monitoring",  label: "알림 & 모니터링",    icon: Bell,            group: "eval" },
  { id: "apikeys",     label: "AI API 키 설정",     icon: Key,             group: "settings" },
];

const GROUP_LABELS = {
  overview: "개요",
  data:     "데이터 관리",
  eval:     "평가",
  settings: "설정",
};

export default function App() {
  const [page, setPage]                 = useState("dashboard");
  const [selectedSub, setSelectedSub]  = useState("sub_001");

  const renderPage = () => {
    switch (page) {
      case "dashboard":    return <Dashboard setPage={setPage} setSelectedSub={setSelectedSub} />;
      case "subscribers":  return <SubscriberManagement />;
      case "knowledge":    return <KnowledgeBase />;
      case "calllogs":     return <CallLogRegistration />;
      case "embedding":    return <EmbeddingVerification />;
      case "simulator":    return <Simulator />;
      case "evaluation":   return <EvaluationRunner />;
      case "results":      return <EvaluationResults selectedSub={selectedSub} />;
      case "monitoring":   return <Monitoring />;
      case "apikeys":      return <APIKeySettings />;
      default:             return <Dashboard setPage={setPage} setSelectedSub={setSelectedSub} />;
    }
  };

  const groups = ["overview", "data", "eval", "settings"];

  return (
    <div className="flex h-screen bg-gray-100 font-sans overflow-hidden">
      {/* 사이드바 */}
      <div className="w-56 bg-white border-r border-gray-100 flex flex-col shadow-sm flex-shrink-0">
        {/* 로고 */}
        <div className="p-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: COLOR.navy }}>
              <Activity size={16} className="text-white" />
            </div>
            <div>
              <p className="text-sm font-bold text-gray-900">CallBot QA</p>
              <p className="text-xs text-gray-400">품질 자동 검증</p>
            </div>
          </div>
        </div>
        {/* 네비게이션 */}
        <nav className="flex-1 p-3 space-y-4 overflow-y-auto">
          {groups.map(grp => (
            <div key={grp}>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider px-2 mb-1">
                {GROUP_LABELS[grp]}
              </p>
              {NAV.filter(n => n.group === grp).map(n => {
                const active = page === n.id;
                return (
                  <button key={n.id} onClick={() => setPage(n.id)}
                    className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-sm transition-colors ${
                      active ? "bg-blue-700 text-white font-medium" : "text-gray-600 hover:bg-gray-100"
                    }`}>
                    <n.icon size={15} />
                    {n.label}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>
        {/* 하단 */}
        <div className="p-3 border-t border-gray-100">
          <div className="flex items-center gap-2 px-2 py-1.5">
            <div className="w-6 h-6 rounded-full bg-blue-700 flex items-center justify-center text-white text-xs font-bold">Q</div>
            <div>
              <p className="text-xs font-medium text-gray-800">품질관리팀</p>
              <p className="text-xs text-gray-400">admin</p>
            </div>
          </div>
        </div>
      </div>

      {/* 메인 콘텐츠 */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-6 max-w-5xl mx-auto">
          {renderPage()}
        </div>
      </div>
    </div>
  );
}
