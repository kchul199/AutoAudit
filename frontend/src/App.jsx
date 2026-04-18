import { useEffect, useState, useTransition } from "react";
import {
  Activity,
  BarChart3,
  Bot,
  Database,
  FileUp,
  FolderOpen,
  PlayCircle,
  RefreshCw,
  ShieldCheck,
  Upload,
  Users,
} from "lucide-react";
import {
  apiBase,
  createSubscriber,
  getDocuments,
  getHealth,
  getLatestResults,
  getLogs,
  getSubscribers,
  runPipeline,
  runSimulator,
  uploadFiles,
} from "./api";

const NAV = [
  { id: "dashboard", label: "대시보드", icon: Activity },
  { id: "workspace", label: "데이터 관리", icon: FolderOpen },
  { id: "run", label: "파이프라인", icon: PlayCircle },
  { id: "results", label: "결과 보기", icon: BarChart3 },
];

function App() {
  const [page, setPage] = useState("dashboard");
  const [health, setHealth] = useState(null);
  const [subscribers, setSubscribers] = useState([]);
  const [selected, setSelected] = useState("");
  const [documents, setDocuments] = useState([]);
  const [logs, setLogs] = useState([]);
  const [latestResults, setLatestResults] = useState(null);
  const [pipelineResult, setPipelineResult] = useState(null);
  const [simulatorResult, setSimulatorResult] = useState(null);
  const [error, setError] = useState("");
  const [isPending, startTransition] = useTransition();

  const [subscriberForm, setSubscriberForm] = useState({
    name: "",
    industry: "",
    contact: "",
    desc: "",
  });
  const [runForm, setRunForm] = useState({
    until: "cp6",
    reindex: false,
    allowSampleData: false,
  });
  const [simulatorForm, setSimulatorForm] = useState({
    userQuery: "",
    botAnswer: "",
  });

  useEffect(() => {
    loadBootstrap();
  }, []);

  useEffect(() => {
    if (!selected) return;
    startTransition(() => {
      Promise.all([
        getDocuments(selected),
        getLogs(selected),
        getLatestResults(selected).catch(() => null),
      ])
        .then(([docs, logItems, latest]) => {
          setDocuments(docs);
          setLogs(logItems);
          setLatestResults(latest);
        })
        .catch((err) => setError(normalizeError(err)));
    });
  }, [selected]);

  async function loadBootstrap() {
    try {
      setError("");
      const [healthInfo, subscriberList] = await Promise.all([getHealth(), getSubscribers()]);
      setHealth(healthInfo);
      setSubscribers(subscriberList);
      if (subscriberList[0]) {
        setSelected(subscriberList[0].name);
      }
    } catch (err) {
      setError(normalizeError(err));
    }
  }

  async function handleCreateSubscriber(event) {
    event.preventDefault();
    if (!subscriberForm.name.trim()) return;
    try {
      setError("");
      const created = await createSubscriber(subscriberForm);
      const next = [...subscribers.filter((item) => item.name !== created.name), created];
      next.sort((a, b) => a.name.localeCompare(b.name, "ko"));
      setSubscribers(next);
      setSelected(created.name);
      setSubscriberForm({ name: "", industry: "", contact: "", desc: "" });
    } catch (err) {
      setError(normalizeError(err));
    }
  }

  async function handleUpload(subscriber, kind, fileList) {
    if (!subscriber || !fileList?.length) return;
    const path =
      kind === "documents"
        ? `/api/subscribers/${encodeURIComponent(subscriber)}/documents/upload`
        : `/api/subscribers/${encodeURIComponent(subscriber)}/logs/upload`;
    try {
      setError("");
      await uploadFiles(path, Array.from(fileList));
      const [docs, logItems] = await Promise.all([getDocuments(subscriber), getLogs(subscriber)]);
      setDocuments(docs);
      setLogs(logItems);
      const refreshed = await getSubscribers();
      setSubscribers(refreshed);
    } catch (err) {
      setError(normalizeError(err));
    }
  }

  async function handleRunPipeline(event) {
    event.preventDefault();
    if (!selected) return;
    try {
      setError("");
      setPipelineResult(null);
      const result = await runPipeline({
        subscriber: selected,
        until: runForm.until,
        reindex: runForm.reindex,
        allow_sample_data: runForm.allowSampleData,
      });
      setPipelineResult(result);
      const [refreshedSubscribers, latest] = await Promise.all([
        getSubscribers(),
        getLatestResults(selected).catch(() => null),
      ]);
      setSubscribers(refreshedSubscribers);
      setLatestResults(latest);
      setPage("results");
    } catch (err) {
      setError(normalizeError(err));
    }
  }

  async function handleRunSimulator(event) {
    event.preventDefault();
    if (!selected) return;
    try {
      setError("");
      const result = await runSimulator({
        subscriber: selected,
        user_query: simulatorForm.userQuery,
        bot_answer: simulatorForm.botAnswer,
        conversation_history: [],
      });
      setSimulatorResult(result);
    } catch (err) {
      setError(normalizeError(err));
    }
  }

  const selectedSubscriber = subscribers.find((item) => item.name === selected);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <ShieldCheck size={18} />
          </div>
          <div>
            <div className="eyebrow">AutoAudit</div>
            <h1>Callbot Quality Console</h1>
          </div>
        </div>

        <nav className="nav">
          {NAV.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${page === item.id ? "active" : ""}`}
              onClick={() => setPage(item.id)}
            >
              <item.icon size={16} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <p>Backend</p>
          <strong>{apiBase}</strong>
          <span>{health?.status === "ok" ? "연결됨" : "확인 필요"}</span>
        </div>
      </aside>

      <main className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">Workspace</p>
            <h2>{selected || "가입자를 선택하세요"}</h2>
          </div>
          <div className="topbar-actions">
            <button className="ghost-button" onClick={loadBootstrap}>
              <RefreshCw size={16} />
              새로고침
            </button>
            <select value={selected} onChange={(event) => setSelected(event.target.value)}>
              <option value="">가입자 선택</option>
              {subscribers.map((item) => (
                <option key={item.id} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
        </header>

        {error ? <div className="alert error">{error}</div> : null}
        {isPending ? <div className="alert">데이터를 불러오는 중입니다.</div> : null}

        {page === "dashboard" ? (
          <Dashboard subscribers={subscribers} health={health} />
        ) : null}

        {page === "workspace" ? (
          <WorkspacePage
            subscriberForm={subscriberForm}
            setSubscriberForm={setSubscriberForm}
            onCreateSubscriber={handleCreateSubscriber}
            selected={selected}
            documents={documents}
            logs={logs}
            onUpload={handleUpload}
          />
        ) : null}

        {page === "run" ? (
          <RunPage
            selected={selected}
            runForm={runForm}
            setRunForm={setRunForm}
            onRunPipeline={handleRunPipeline}
            simulatorForm={simulatorForm}
            setSimulatorForm={setSimulatorForm}
            onRunSimulator={handleRunSimulator}
            simulatorResult={simulatorResult}
          />
        ) : null}

        {page === "results" ? (
          <ResultsPage
            selectedSubscriber={selectedSubscriber}
            latestResults={latestResults}
            pipelineResult={pipelineResult}
          />
        ) : null}
      </main>
    </div>
  );
}

function Dashboard({ subscribers, health }) {
  const metrics = [
    { label: "가입자", value: subscribers.length, icon: Users },
    {
      label: "평균 종합 점수",
      value:
        subscribers.length > 0
          ? (
              subscribers.reduce((sum, item) => sum + (item.avgOverall || 0), 0) /
              subscribers.length
            ).toFixed(2)
          : "0.00",
      icon: BarChart3,
    },
    { label: "백엔드 상태", value: health?.status || "unknown", icon: ShieldCheck },
  ];

  return (
    <section className="stack">
      <div className="hero">
        <div>
          <p className="eyebrow">Live control surface</p>
          <h3>문서 업로드부터 보고서 발행까지 한 흐름으로 관리합니다.</h3>
          <p className="muted">
            현재 백엔드는 CP1~CP6, 로컬 HTML 보고서, Confluence 베스트에포트 발행, 시뮬레이터 평가를 지원합니다.
          </p>
        </div>
        <Bot size={64} />
      </div>

      <div className="metric-grid">
        {metrics.map((metric) => (
          <div className="metric-card" key={metric.label}>
            <metric.icon size={18} />
            <p>{metric.label}</p>
            <strong>{metric.value}</strong>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h4>가입자 현황</h4>
        </div>
        <div className="list">
          {subscribers.map((item) => (
            <div className="list-row" key={item.id}>
              <div>
                <strong>{item.name}</strong>
                <p>{item.industry} · 문서 {item.docsCount}개 · 로그 {item.logsCount}건</p>
              </div>
              <div className="list-metric">
                <span>종합 {Number(item.avgOverall || 0).toFixed(2)}</span>
                <small>{item.lastEval || "아직 실행 없음"}</small>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function WorkspacePage({
  subscriberForm,
  setSubscriberForm,
  onCreateSubscriber,
  selected,
  documents,
  logs,
  onUpload,
}) {
  return (
    <section className="stack two-col">
      <div className="panel">
        <div className="panel-head">
          <h4>가입자 등록</h4>
        </div>
        <form className="stack compact" onSubmit={onCreateSubscriber}>
          <label>
            가입자명
            <input
              value={subscriberForm.name}
              onChange={(event) =>
                setSubscriberForm((prev) => ({ ...prev, name: event.target.value }))
              }
            />
          </label>
          <label>
            업종
            <input
              value={subscriberForm.industry}
              onChange={(event) =>
                setSubscriberForm((prev) => ({ ...prev, industry: event.target.value }))
              }
            />
          </label>
          <label>
            연락처
            <input
              value={subscriberForm.contact}
              onChange={(event) =>
                setSubscriberForm((prev) => ({ ...prev, contact: event.target.value }))
              }
            />
          </label>
          <label>
            메모
            <textarea
              rows="3"
              value={subscriberForm.desc}
              onChange={(event) =>
                setSubscriberForm((prev) => ({ ...prev, desc: event.target.value }))
              }
            />
          </label>
          <button className="primary-button" type="submit">
            <Users size={16} />
            가입자 저장
          </button>
        </form>
      </div>

      <div className="stack">
        <UploadPanel
          title="도메인 문서 업로드"
          description="PDF, TXT, HTML, DOCX, Markdown 문서를 올리면 CP2 인덱싱 대상으로 사용합니다."
          disabled={!selected}
          onChange={(event) => onUpload(selected, "documents", event.target.files)}
        />
        <UploadPanel
          title="콜 로그 업로드"
          description="TXT, JSON, CSV 형식 로그를 올리면 CP1 전처리 대상으로 사용합니다."
          disabled={!selected}
          onChange={(event) => onUpload(selected, "logs", event.target.files)}
        />
        <ArtifactPanel title="문서 목록" icon={Database} items={documents} />
        <ArtifactPanel title="로그 목록" icon={FileUp} items={logs} />
      </div>
    </section>
  );
}

function UploadPanel({ title, description, onChange, disabled }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h4>{title}</h4>
      </div>
      <label className={`upload-zone ${disabled ? "disabled" : ""}`}>
        <Upload size={22} />
        <strong>{disabled ? "가입자를 먼저 선택하세요" : "파일 선택 또는 드래그"}</strong>
        <span>{description}</span>
        <input disabled={disabled} type="file" multiple onChange={onChange} />
      </label>
    </div>
  );
}

function ArtifactPanel({ title, icon: Icon, items }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h4>{title}</h4>
      </div>
      <div className="list">
        {items.length ? (
          items.map((item) => (
            <div className="list-row" key={item.path}>
              <div>
                <strong>{item.name}</strong>
                <p>{item.docType ? `${item.docType} · ` : ""}{(item.size / 1024).toFixed(1)} KB</p>
              </div>
              <Icon size={16} />
            </div>
          ))
        ) : (
          <div className="empty-state">등록된 항목이 없습니다.</div>
        )}
      </div>
    </div>
  );
}

function RunPage({
  selected,
  runForm,
  setRunForm,
  onRunPipeline,
  simulatorForm,
  setSimulatorForm,
  onRunSimulator,
  simulatorResult,
}) {
  return (
    <section className="stack two-col">
      <div className="panel">
        <div className="panel-head">
          <h4>파이프라인 실행</h4>
        </div>
        <form className="stack compact" onSubmit={onRunPipeline}>
          <label>
            마지막 단계
            <select
              value={runForm.until}
              onChange={(event) => setRunForm((prev) => ({ ...prev, until: event.target.value }))}
            >
              {["cp1", "cp2", "cp3", "cp4", "cp5", "cp6"].map((stage) => (
                <option value={stage} key={stage}>
                  {stage.toUpperCase()}
                </option>
              ))}
            </select>
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={runForm.reindex}
              onChange={(event) => setRunForm((prev) => ({ ...prev, reindex: event.target.checked }))}
            />
            인덱스 재구축
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={runForm.allowSampleData}
              onChange={(event) =>
                setRunForm((prev) => ({ ...prev, allowSampleData: event.target.checked }))
              }
            />
            입력이 없으면 샘플 데이터 허용
          </label>
          <button className="primary-button" type="submit" disabled={!selected}>
            <PlayCircle size={16} />
            {selected ? `${selected} 실행` : "가입자 선택 필요"}
          </button>
        </form>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h4>콜봇 시뮬레이터</h4>
        </div>
        <form className="stack compact" onSubmit={onRunSimulator}>
          <label>
            고객 질문
            <textarea
              rows="3"
              value={simulatorForm.userQuery}
              onChange={(event) =>
                setSimulatorForm((prev) => ({ ...prev, userQuery: event.target.value }))
              }
            />
          </label>
          <label>
            콜봇 답변
            <textarea
              rows="4"
              value={simulatorForm.botAnswer}
              onChange={(event) =>
                setSimulatorForm((prev) => ({ ...prev, botAnswer: event.target.value }))
              }
            />
          </label>
          <button className="primary-button" type="submit" disabled={!selected}>
            <Bot size={16} />
            즉시 평가
          </button>
        </form>

        {simulatorResult ? (
          <div className="simulator-result">
            <strong>합의 점수</strong>
            <p>
              정확성 {simulatorResult.consensus.accuracy_mean} / 자연스러움{" "}
              {simulatorResult.consensus.fluency_mean}
            </p>
            <small>
              참조 {simulatorResult.context.top_chunks?.length || 0}개 ·{" "}
              {simulatorResult.consensus.flag || "안정"}
            </small>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ResultsPage({ selectedSubscriber, latestResults, pipelineResult }) {
  const summary = latestResults?.summary?.summary;
  const reportUrl = latestResults?.report_url ? `${apiBase}${latestResults.report_url}` : null;

  return (
    <section className="stack">
      <div className="metric-grid">
        <div className="metric-card">
          <p>평균 정확성</p>
          <strong>{summary?.avg_accuracy ?? "-"}</strong>
        </div>
        <div className="metric-card">
          <p>평균 자연스러움</p>
          <strong>{summary?.avg_fluency ?? "-"}</strong>
        </div>
        <div className="metric-card">
          <p>불확실 턴</p>
          <strong>{summary?.uncertain_count ?? 0}</strong>
        </div>
      </div>

      {pipelineResult ? (
        <div className="panel">
          <div className="panel-head">
            <h4>최근 실행 결과</h4>
          </div>
          <pre className="code-block">{JSON.stringify(pipelineResult, null, 2)}</pre>
        </div>
      ) : null}

      <div className="panel">
        <div className="panel-head">
          <h4>{selectedSubscriber?.name || "가입자"} 최신 보고서</h4>
          {reportUrl ? (
            <a className="ghost-button" href={reportUrl} target="_blank" rel="noreferrer">
              보고서 열기
            </a>
          ) : null}
        </div>
        {latestResults?.summary?.conversations?.length ? (
          <div className="list">
            {latestResults.summary.conversations.slice(0, 8).map((item) => (
              <div className="list-row" key={`${item.conv_id}-${item.turn_count}`}>
                <div>
                  <strong>{item.source_file || item.conv_id}</strong>
                  <p>턴 {item.turn_count} · 불확실 {item.uncertain_count}</p>
                </div>
                <div className="list-metric">
                  <span>{item.avg_overall}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">아직 생성된 결과가 없습니다.</div>
        )}
      </div>
    </section>
  );
}

function normalizeError(error) {
  return error?.message?.replace(/^"|"$/g, "") || "요청 처리 중 오류가 발생했습니다.";
}

export default App;
