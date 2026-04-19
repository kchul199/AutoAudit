import { useEffect, useState, useTransition } from "react";
import {
  Activity,
  BarChart3,
  Bot,
  Database,
  FileUp,
  FolderOpen,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  CheckCircle2,
  Upload,
  Users,
} from "lucide-react";
import {
  apiBase,
  createAnchorEvalJob,
  createPipelineJob,
  createSubscriber,
  getDocuments,
  getHealth,
  getLiveConsensusReadiness,
  getLatestAnchorEval,
  getLatestResults,
  getLogs,
  getReviewOpsDashboard,
  getSubscribers,
  getTurnDetail,
  listAnchorEvalJobs,
  listPipelineJobs,
  probeLiveConsensus,
  runSimulator,
  streamAnchorEvalJob,
  streamPipelineJob,
  submitReviewAction,
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
  const [liveReadiness, setLiveReadiness] = useState(null);
  const [subscribers, setSubscribers] = useState([]);
  const [selected, setSelected] = useState("");
  const [documents, setDocuments] = useState([]);
  const [logs, setLogs] = useState([]);
  const [latestResults, setLatestResults] = useState(null);
  const [pipelineResult, setPipelineResult] = useState(null);
  const [pipelineJob, setPipelineJob] = useState(null);
  const [pipelineJobs, setPipelineJobs] = useState([]);
  const [latestAnchorEval, setLatestAnchorEval] = useState(null);
  const [anchorEvalJob, setAnchorEvalJob] = useState(null);
  const [anchorEvalJobs, setAnchorEvalJobs] = useState([]);
  const [reviewOps, setReviewOps] = useState(null);
  const [simulatorResult, setSimulatorResult] = useState(null);
  const [error, setError] = useState("");
  const [probePending, setProbePending] = useState(false);
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
  const [anchorEvalForm, setAnchorEvalForm] = useState({
    datasetPath: "examples/anchor_eval.sample.jsonl",
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
        listPipelineJobs(selected).catch(() => []),
        getLatestAnchorEval(selected).catch(() => null),
        listAnchorEvalJobs(selected).catch(() => []),
      ])
        .then(([docs, logItems, latest, jobs, anchorReport, anchorJobs]) => {
          setDocuments(docs);
          setLogs(logItems);
          setLatestResults(latest);
          setLatestAnchorEval(anchorReport);
          setPipelineJobs(jobs);
          setPipelineJob((prev) => pickActiveJob(jobs, prev));
          setAnchorEvalJobs(anchorJobs);
          setAnchorEvalJob((prev) => pickActiveJob(anchorJobs, prev));
        })
        .catch((err) => setError(normalizeError(err)));
    });
  }, [selected]);

  useEffect(() => {
    if (!pipelineJob?.id || !["queued", "running"].includes(pipelineJob.status)) {
      return undefined;
    }

    const stream = streamPipelineJob(
      pipelineJob.id,
      async (job) => {
        setPipelineJob(job);
        setPipelineJobs((prev) => mergeJobs(prev, job));
        if (!["queued", "running"].includes(job.status)) {
          if (job.result && job.subscriber === selected) {
            setPipelineResult(job.result);
          }
          const [refreshedSubscribers, latest, jobs] = await Promise.all([
            getSubscribers(),
            getLatestResults(job.subscriber).catch(() => null),
            listPipelineJobs(job.subscriber).catch(() => []),
          ]);
          setSubscribers(refreshedSubscribers);
          const reviewOpsData = await getReviewOpsDashboard().catch(() => null);
          setReviewOps(reviewOpsData);
          if (job.subscriber === selected) {
            setLatestResults(latest);
            setPipelineJobs(jobs);
            setPage("results");
          }
        }
      },
      () => {},
    );

    return () => stream.close();
  }, [pipelineJob?.id, pipelineJob?.status, selected]);

  useEffect(() => {
    if (!anchorEvalJob?.id || !["queued", "running"].includes(anchorEvalJob.status)) {
      return undefined;
    }

    const stream = streamAnchorEvalJob(
      anchorEvalJob.id,
      async (job) => {
        setAnchorEvalJob(job);
        setAnchorEvalJobs((prev) => mergeJobs(prev, job));
        if (!["queued", "running"].includes(job.status)) {
          if (job.result && job.subscriber === selected) {
            setLatestAnchorEval(job.result);
          }
          const [jobs, latest] = await Promise.all([
            listAnchorEvalJobs(job.subscriber).catch(() => []),
            getLatestAnchorEval(job.subscriber).catch(() => job.result || null),
          ]);
          if (job.subscriber === selected) {
            setAnchorEvalJobs(jobs);
            setLatestAnchorEval(latest);
          }
        }
      },
      () => {},
    );

    return () => stream.close();
  }, [anchorEvalJob?.id, anchorEvalJob?.status, selected]);

  async function loadBootstrap() {
    try {
      setError("");
      const [healthInfo, readinessInfo, subscriberList, reviewOpsData] = await Promise.all([
        getHealth(),
        getLiveConsensusReadiness().catch(() => null),
        getSubscribers(),
        getReviewOpsDashboard().catch(() => null),
      ]);
      setHealth(healthInfo);
      setLiveReadiness(readinessInfo);
      setSubscribers(subscriberList);
      setReviewOps(reviewOpsData);
      if (subscriberList[0]) {
        setSelected(subscriberList[0].name);
      }
    } catch (err) {
      setError(normalizeError(err));
    }
  }

  async function handleProbeLiveConsensus() {
    try {
      setError("");
      setProbePending(true);
      const result = await probeLiveConsensus();
      setLiveReadiness(result);
      const healthInfo = await getHealth().catch(() => null);
      if (healthInfo) {
        setHealth(healthInfo);
      }
    } catch (err) {
      setError(normalizeError(err));
    } finally {
      setProbePending(false);
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
      const job = await createPipelineJob({
        subscriber: selected,
        until: runForm.until,
        reindex: runForm.reindex,
        allow_sample_data: runForm.allowSampleData,
      });
      setPipelineJob(job);
      setPipelineJobs((prev) => mergeJobs(prev, job));
    } catch (err) {
      setError(normalizeError(err));
    }
  }

  async function handleRunAnchorEval(event) {
    event.preventDefault();
    if (!selected || !anchorEvalForm.datasetPath.trim()) return;
    try {
      setError("");
      const job = await createAnchorEvalJob({
        subscriber: selected,
        dataset_path: anchorEvalForm.datasetPath.trim(),
      });
      setAnchorEvalJob(job);
      setAnchorEvalJobs((prev) => mergeJobs(prev, job));
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

  async function handleReviewAction(payload) {
    if (!selected) return null;
    try {
      setError("");
      const result = await submitReviewAction(selected, payload);
      const [latest, jobs, reviewOpsData] = await Promise.all([
        getLatestResults(selected).catch(() => null),
        listPipelineJobs(selected).catch(() => []),
        getReviewOpsDashboard().catch(() => null),
      ]);
      setLatestResults(latest);
      setPipelineJobs(jobs);
      setReviewOps(reviewOpsData);
      if (result?.pipeline_job) {
        setPipelineJob(result.pipeline_job);
        setPipelineJobs((prev) => mergeJobs(prev, result.pipeline_job));
      }
      return result;
    } catch (err) {
      setError(normalizeError(err));
      throw err;
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
          <Dashboard
            subscribers={subscribers}
            health={health}
            reviewOps={reviewOps}
            liveReadiness={liveReadiness}
            onProbeLiveConsensus={handleProbeLiveConsensus}
            probePending={probePending}
          />
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
            liveReadiness={liveReadiness}
            onProbeLiveConsensus={handleProbeLiveConsensus}
            probePending={probePending}
            runForm={runForm}
            setRunForm={setRunForm}
            onRunPipeline={handleRunPipeline}
            pipelineJob={pipelineJob}
            pipelineJobs={pipelineJobs}
            anchorEvalForm={anchorEvalForm}
            setAnchorEvalForm={setAnchorEvalForm}
            onRunAnchorEval={handleRunAnchorEval}
            anchorEvalJob={anchorEvalJob}
            anchorEvalJobs={anchorEvalJobs}
            latestAnchorEval={latestAnchorEval}
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
            latestAnchorEval={latestAnchorEval}
            pipelineResult={pipelineResult}
            onReviewAction={handleReviewAction}
          />
        ) : null}
      </main>
    </div>
  );
}

function Dashboard({ subscribers, health, reviewOps, liveReadiness, onProbeLiveConsensus, probePending }) {
  const metrics = [
    { label: "가입자", value: subscribers.length, icon: Users },
    {
      label: "평균 신뢰 평가율",
      value:
        subscribers.length > 0
          ? `${(
              (subscribers.reduce((sum, item) => sum + (item.trustedRate || 0), 0) /
                subscribers.length) *
              100
            ).toFixed(1)}%`
          : "0.00",
      icon: BarChart3,
    },
    {
      label: "검토 큐",
      value: subscribers.reduce((sum, item) => sum + (item.reviewQueueSize || 0), 0),
      icon: FileUp,
    },
    {
      label: "재평가 완료",
      value: reviewOps?.overview?.completed_recheck_count ?? 0,
      icon: RotateCcw,
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
                <p>
                  {item.industry} · 문서 {item.docsCount}개 · 로그 {item.logsCount}건 · 상태 {item.status}
                </p>
              </div>
              <div className="list-metric">
                <span>신뢰 {((item.trustedRate || 0) * 100).toFixed(1)}%</span>
                <small>
                  검토 {item.reviewQueueSize || 0}건 · {item.lastEval || "아직 실행 없음"}
                </small>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h4>담당자별 검토 큐</h4>
          <small>
            미할당 {reviewOps?.overview?.pending_unassigned_count ?? 0}건
          </small>
        </div>
        {reviewOps?.assignees?.length ? (
          <div className="list">
            {reviewOps.assignees.slice(0, 8).map((item) => (
              <div className="list-row" key={item.assignee}>
                <div>
                  <strong>{item.assignee}</strong>
                  <p>{item.subscribers?.join(", ") || "구독자 없음"}</p>
                </div>
                <div className="list-metric">
                  <span>
                    대기 {item.pending_count} · 재평가 {item.recheck_count}
                  </span>
                  <small>
                    보류 {item.hold_count} · 완료알림 {item.completed_recheck_count}
                  </small>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">아직 할당된 검토 항목이 없습니다.</div>
        )}
      </div>

      <LiveConsensusPanel
        readiness={liveReadiness}
        onProbe={onProbeLiveConsensus}
        probePending={probePending}
      />

      <div className="panel">
        <div className="panel-head">
          <h4>재평가 완료 알림</h4>
          <small>{reviewOps?.overview?.completed_recheck_count ?? 0}건</small>
        </div>
        {reviewOps?.recent_rechecks?.length ? (
          <div className="list">
            {reviewOps.recent_rechecks.map((item) => (
              <div className="list-row" key={`${item.job_id}-${item.conv_id}-${item.turn_index}`}>
                <div>
                  <strong>{item.subscriber} · {item.assignee || "미할당"}</strong>
                  <p>
                    턴 {item.turn_index} · {item.user_query}
                  </p>
                </div>
                <div className="list-metric">
                  <span>재평가 완료</span>
                  <small>{formatDateTime(item.finished_at)}</small>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">아직 완료된 재평가 알림이 없습니다.</div>
        )}
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
  liveReadiness,
  onProbeLiveConsensus,
  probePending,
  runForm,
  setRunForm,
  onRunPipeline,
  pipelineJob,
  pipelineJobs,
  anchorEvalForm,
  setAnchorEvalForm,
  onRunAnchorEval,
  anchorEvalJob,
  anchorEvalJobs,
  latestAnchorEval,
  simulatorForm,
  setSimulatorForm,
  onRunSimulator,
  simulatorResult,
}) {
  return (
    <section className="stack two-col">
      <div className="stack">
        <LiveConsensusPanel
          readiness={liveReadiness}
          onProbe={onProbeLiveConsensus}
          probePending={probePending}
          compact
        />

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
                onChange={(event) =>
                  setRunForm((prev) => ({ ...prev, reindex: event.target.checked }))
                }
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

          <JobStatusCard
            title="현재 파이프라인 Job"
            job={pipelineJob}
            emptyLabel="아직 실행 중인 파이프라인 job이 없습니다."
          />
          <JobHistory title="Recent Pipeline Jobs" jobs={pipelineJobs} />
        </div>

        <div className="panel">
          <div className="panel-head">
            <h4>앵커 Eval</h4>
          </div>
          <form className="stack compact" onSubmit={onRunAnchorEval}>
            <label>
              데이터셋 경로
              <input
                value={anchorEvalForm.datasetPath}
                onChange={(event) =>
                  setAnchorEvalForm((prev) => ({ ...prev, datasetPath: event.target.value }))
                }
                placeholder="examples/anchor_eval.sample.jsonl"
              />
            </label>
            <button className="primary-button" type="submit" disabled={!selected}>
              <BarChart3 size={16} />
              {selected ? `${selected} 앵커 Eval` : "가입자 선택 필요"}
            </button>
          </form>

          <JobStatusCard
            title="현재 앵커 Eval Job"
            job={anchorEvalJob}
            emptyLabel="아직 실행 중인 앵커 eval job이 없습니다."
          />
          <JobHistory title="Recent Anchor Eval Jobs" jobs={anchorEvalJobs} />

          {latestAnchorEval ? (
            <div className="job-history">
              <p className="eyebrow">Latest Anchor Eval</p>
              <div className="detail-grid anchor-summary-grid">
                <div className="detail-block">
                  <strong>{latestAnchorEval.case_count || 0} cases</strong>
                  <p>{latestAnchorEval.dataset_path}</p>
                </div>
                <div className="detail-block">
                  <div className="chip-row">
                    <span className="chip">
                      retrieval {formatRatio(latestAnchorEval.summary?.retrieval_hit_rate)}
                    </span>
                    <span className="chip">
                      state {formatRatio(latestAnchorEval.summary?.state_match_rate)}
                    </span>
                    <span className="chip">
                      score {formatRatio(latestAnchorEval.summary?.score_match_rate)}
                    </span>
                    <span className="chip">
                      risk {formatRatio(latestAnchorEval.summary?.risk_flag_match_rate)}
                    </span>
                  </div>
                  <small>
                    보조 점수 평균 {latestAnchorEval.summary?.avg_support_overall ?? "-"}
                  </small>
                </div>
              </div>
            </div>
          ) : null}
        </div>
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
            <strong>평가 상태 {simulatorResult.consensus.state}</strong>
            <p>
              {simulatorResult.consensus.overall_mean != null
                ? `운영 점수 ${simulatorResult.consensus.overall_mean}`
                : `보조 점수 ${simulatorResult.consensus.support_overall_mean}`}
            </p>
            <small>
              참조 {simulatorResult.context.top_chunks?.length || 0}개 · 검토 필요{" "}
              {simulatorResult.consensus.review_required ? "예" : "아니오"}
            </small>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function LiveConsensusPanel({ readiness, onProbe, probePending, compact = false }) {
  const summary = readiness?.summary;
  const providers = readiness?.providers || [];
  const lastProbe = readiness?.last_probe;

  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <h4>Live Multi-LLM Readiness</h4>
          <small>
            {summary?.trusted_possible ? "TRUSTED 가능" : "추가 확인 필요"} ·{" "}
            {summary?.providers_ready_count ?? 0}/{summary?.provider_count ?? 3} ready
          </small>
        </div>
        <button className="ghost-button" type="button" onClick={onProbe} disabled={probePending}>
          <RefreshCw size={16} className={probePending ? "spin" : ""} />
          {probePending ? "Live probe 중" : "Live probe 실행"}
        </button>
      </div>

      {lastProbe?.checked_at ? (
        <div className="chip-row compact">
          <span className={`chip ${lastProbe.summary?.trusted_possible ? "" : "warning"}`}>
            최근 probe {formatDateTime(lastProbe.checked_at)}
          </span>
          <span className={`chip ${lastProbe.summary?.trusted_possible ? "" : "danger"}`}>
            {lastProbe.summary?.status || "unknown"}
          </span>
        </div>
      ) : null}

      <div className={`provider-grid ${compact ? "compact" : ""}`}>
        {providers.map((item) => (
          <div className="provider-card" key={item.provider}>
            <div className="provider-head">
              <strong>{item.label}</strong>
              <span className={`chip ${providerChipTone(item.status)}`}>{providerStatusLabel(item.status)}</span>
            </div>
            <p>{item.model}</p>
            <small>
              SDK {item.sdk_package} {item.sdk_version || "not installed"} · {item.client_mode}
            </small>
            <small>{item.reason}</small>
            <div className="chip-row compact">
              <span className={`chip ${item.configured ? "" : "warning"}`}>
                key {item.configured ? "configured" : "missing"}
              </span>
              <span className={`chip ${item.sdk_available ? "" : "warning"}`}>
                sdk {item.sdk_available ? "ok" : "missing"}
              </span>
              {item.probe_attempted ? (
                <span className={`chip ${item.live_success ? "" : "danger"}`}>
                  live {item.live_success ? "ok" : "failed"}
                </span>
              ) : null}
              {item.latency_ms != null ? <span className="chip">{Math.round(item.latency_ms)} ms</span> : null}
            </div>
            {item.error_reason ? <small>error: {item.error_reason}</small> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function ResultsPage({
  selectedSubscriber,
  latestResults,
  latestAnchorEval,
  pipelineResult,
  onReviewAction,
}) {
  const summary = latestResults?.summary?.summary;
  const reportUrl = latestResults?.report_url ? `${apiBase}${latestResults.report_url}` : null;
  const reviewQueue = latestResults?.summary?.review_queue || [];
  const [reviewFilters, setReviewFilters] = useState({
    search: "",
    status: "all",
    state: "all",
    owner: "",
  });
  const [selectedReviewItem, setSelectedReviewItem] = useState(null);
  const [reviewDetail, setReviewDetail] = useState(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [reviewAssignee, setReviewAssignee] = useState("");
  const [actionPending, setActionPending] = useState(false);
  const [actionFeedback, setActionFeedback] = useState("");
  const filteredReviewQueue = filterReviewQueue(reviewQueue, reviewFilters);

  useEffect(() => {
    if (!filteredReviewQueue.length) {
      setSelectedReviewItem(null);
      setReviewDetail(null);
      setReviewError("");
      return;
    }

    setSelectedReviewItem((prev) => {
      if (
        prev &&
        filteredReviewQueue.some(
          (item) => item.conv_id === prev.conv_id && item.turn_index === prev.turn_index,
        )
      ) {
        return prev;
      }
      return filteredReviewQueue[0];
    });
  }, [
    selectedSubscriber?.name,
    latestResults,
    reviewFilters.search,
    reviewFilters.status,
    reviewFilters.state,
    reviewFilters.owner,
  ]);

  useEffect(() => {
    if (!selectedSubscriber?.name || !selectedReviewItem) {
      setReviewDetail(null);
      return;
    }

    let cancelled = false;
    setReviewLoading(true);
    setReviewError("");

    getTurnDetail(
      selectedSubscriber.name,
      selectedReviewItem.conv_id,
      selectedReviewItem.turn_index,
    )
      .then((detail) => {
        if (!cancelled) {
          setReviewDetail(detail);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setReviewError(normalizeError(error));
          setReviewDetail(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setReviewLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedSubscriber?.name, selectedReviewItem, latestResults]);

  useEffect(() => {
    setActionFeedback("");
    setReviewNote(reviewDetail?.review_action?.note || "");
    setReviewAssignee(reviewDetail?.assignee || "");
  }, [
    selectedReviewItem?.conv_id,
    selectedReviewItem?.turn_index,
    reviewDetail?.review_action?.updated_at,
    reviewDetail?.assignee,
  ]);

  async function handleReviewDecision(action) {
    if (!selectedSubscriber?.name || !selectedReviewItem) return;
    if (action === "assign" && !reviewAssignee.trim()) {
      setActionFeedback("담당자를 입력한 뒤 지정해 주세요.");
      return;
    }
    try {
      setActionPending(true);
      const result = await onReviewAction?.({
        conv_id: selectedReviewItem.conv_id,
        turn_index: selectedReviewItem.turn_index,
        action,
        note: reviewNote,
        assignee: reviewAssignee,
      });
      const actionLabel = REVIEW_ACTION_LABELS[action] || action;
      if (result?.pipeline_job) {
        setActionFeedback(`${actionLabel} 처리 후 재평가 job ${result.pipeline_job.id}를 시작했습니다.`);
      } else {
        setActionFeedback(`${actionLabel} 처리되었습니다.`);
      }
    } catch (error) {
      setActionFeedback(normalizeError(error));
    } finally {
      setActionPending(false);
    }
  }

  return (
    <section className="stack">
      <div className="metric-grid">
        <div className="metric-card">
          <p>신뢰 평가율</p>
          <strong>{summary ? `${((summary.trusted_rate || 0) * 100).toFixed(1)}%` : "-"}</strong>
        </div>
        <div className="metric-card">
          <p>검토 큐</p>
          <strong>{summary?.review_queue_size ?? 0}</strong>
        </div>
        <div className="metric-card">
          <p>승인 완료</p>
          <strong>{summary?.approved_review_count ?? 0}</strong>
        </div>
        <div className="metric-card">
          <p>보류</p>
          <strong>{summary?.hold_review_count ?? 0}</strong>
        </div>
        <div className="metric-card">
          <p>Degraded 비율</p>
          <strong>{summary ? `${((summary.degraded_ratio || 0) * 100).toFixed(1)}%` : "-"}</strong>
        </div>
        <div className="metric-card">
          <p>재평가 대기</p>
          <strong>{summary?.recheck_review_count ?? 0}</strong>
        </div>
        <div className="metric-card">
          <p>미할당 검토</p>
          <strong>{summary?.pending_unassigned_count ?? 0}</strong>
        </div>
        <div className="metric-card">
          <p>신뢰 종합 점수</p>
          <strong>{summary?.trusted_avg_overall ?? "-"}</strong>
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
          <h4>최신 앵커 Eval</h4>
        </div>
        {latestAnchorEval ? (
          <div className="stack compact">
            <div className="detail-grid anchor-summary-grid">
              <div className="detail-block">
                <p className="eyebrow">Dataset</p>
                <strong>{latestAnchorEval.case_count || 0} cases</strong>
                <p>{latestAnchorEval.dataset_path}</p>
              </div>
              <div className="detail-block">
                <p className="eyebrow">Summary</p>
                <div className="chip-row">
                  <span className="chip">
                    retrieval {formatRatio(latestAnchorEval.summary?.retrieval_hit_rate)}
                  </span>
                  <span className="chip">
                    state {formatRatio(latestAnchorEval.summary?.state_match_rate)}
                  </span>
                  <span className="chip">
                    score {formatRatio(latestAnchorEval.summary?.score_match_rate)}
                  </span>
                  <span className="chip">
                    risk {formatRatio(latestAnchorEval.summary?.risk_flag_match_rate)}
                  </span>
                </div>
                <small>보조 점수 평균 {latestAnchorEval.summary?.avg_support_overall ?? "-"}</small>
              </div>
            </div>

            {latestAnchorEval.cases?.length ? (
              <div className="list">
                {latestAnchorEval.cases
                  .filter(
                    (item) =>
                      item.retrieval_hit === false ||
                      item.state_match === false ||
                      item.score_match === false ||
                      item.risk_flag_match === false,
                  )
                  .slice(0, 5)
                  .map((item) => (
                    <div className="list-row" key={item.case_id || item.user_query}>
                      <div>
                        <strong>{item.case_id || item.user_query}</strong>
                        <p>
                          state {item.actual_state || "-"} · grounding {item.grounding_risk || "unknown"}
                        </p>
                        <small>
                          retrieval {formatVerdict(item.retrieval_hit)} · state{" "}
                          {formatVerdict(item.state_match)} · score {formatVerdict(item.score_match)} ·
                          risk {formatVerdict(item.risk_flag_match)}
                        </small>
                      </div>
                      <div className="list-metric">
                        <span>{item.support_overall_mean ?? "-"}</span>
                      </div>
                    </div>
                  ))}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="empty-state">아직 저장된 앵커 eval 결과가 없습니다.</div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h4>검토 큐</h4>
          <small>
            {filteredReviewQueue.length} / {reviewQueue.length} 건
          </small>
        </div>
        <div className="filter-grid">
          <label>
            검색
            <input
              value={reviewFilters.search}
              onChange={(event) =>
                setReviewFilters((prev) => ({ ...prev, search: event.target.value }))
              }
              placeholder="질문, 파일명, conv id"
            />
          </label>
          <label>
            검토 상태
            <select
              value={reviewFilters.status}
              onChange={(event) =>
                setReviewFilters((prev) => ({ ...prev, status: event.target.value }))
              }
            >
              <option value="all">전체</option>
              <option value="pending">대기</option>
              <option value="approved">승인 완료</option>
              <option value="hold">보류</option>
              <option value="recheck">재평가 요청</option>
            </select>
          </label>
          <label>
            평가 상태
            <select
              value={reviewFilters.state}
              onChange={(event) =>
                setReviewFilters((prev) => ({ ...prev, state: event.target.value }))
              }
            >
              <option value="all">전체</option>
              <option value="DEGRADED">DEGRADED</option>
              <option value="UNCERTAIN">UNCERTAIN</option>
              <option value="INCOMPLETE">INCOMPLETE</option>
              <option value="TRUSTED">TRUSTED</option>
            </select>
          </label>
          <label>
            담당자
            <input
              value={reviewFilters.owner}
              onChange={(event) =>
                setReviewFilters((prev) => ({ ...prev, owner: event.target.value }))
              }
              placeholder="이름 또는 이메일"
            />
          </label>
        </div>
        {filteredReviewQueue.length ? (
          <div className="list">
            {filteredReviewQueue.slice(0, 12).map((item) => (
              <button
                type="button"
                className={`list-row review-row ${
                  selectedReviewItem?.conv_id === item.conv_id &&
                  selectedReviewItem?.turn_index === item.turn_index
                    ? "active"
                    : ""
                }`}
                key={`${item.conv_id}-${item.turn_index}`}
                onClick={() => setSelectedReviewItem(item)}
              >
                <div>
                  <strong>{item.source_file || item.conv_id}</strong>
                  <p>
                    {item.state} · 턴 {item.turn_index} · {item.user_query}
                  </p>
                  <small>
                    grounding {item.grounding_risk || "unknown"} · live {item.live_judge_count || 0} /
                    fallback {item.fallback_judge_count || 0}
                  </small>
                  <div className="chip-row compact">
                    <span className={`chip status-chip ${item.review_status || "pending"}`}>
                      {formatReviewStatus(item.review_status)}
                    </span>
                    <span className="chip owner-chip">
                      {item.assignee ? `담당 ${item.assignee}` : "미할당"}
                    </span>
                    {item.recheck_job ? (
                      <span className={`chip recheck-chip ${item.recheck_job.status || "unknown"}`}>
                        {formatRecheckJobStatus(item.recheck_job.status)}
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="list-metric">
                  <span>{item.overall_mean ?? item.support_overall_mean ?? "-"}</span>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <div className="empty-state">필터 조건에 맞는 검토 케이스가 없습니다.</div>
        )}
      </div>

      <ReviewDetailPanel
        detail={reviewDetail}
        loading={reviewLoading}
        error={reviewError}
        reviewNote={reviewNote}
        setReviewNote={setReviewNote}
        onReviewAction={handleReviewDecision}
        actionPending={actionPending}
        actionFeedback={actionFeedback}
        reviewAssignee={reviewAssignee}
        setReviewAssignee={setReviewAssignee}
      />

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
                  <p>
                    상태 {item.dominant_state} · 턴 {item.turn_count} · 검토 {item.review_turn_count}
                  </p>
                </div>
                <div className="list-metric">
                  <span>{item.avg_overall ?? item.avg_operational_overall ?? "-"}</span>
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

function JobStatusCard({ title, job, emptyLabel }) {
  if (!job) {
    return (
      <div className="job-status-card">
        <p>{emptyLabel}</p>
      </div>
    );
  }

  return (
    <div className="job-status-card">
      <p className="eyebrow">{title}</p>
      <strong>
        {job.status} · {job.current_checkpoint || "대기"}
      </strong>
      <p>
        진행률 {Math.round((job.progress || 0) * 100)}% · 생성 {formatDateTime(job.created_at)}
      </p>
      {job.error ? <small>{job.error}</small> : null}
    </div>
  );
}

function JobHistory({ title, jobs }) {
  if (!jobs.length) return null;
  return (
    <div className="job-history">
      <p className="eyebrow">{title}</p>
      <div className="list">
        {jobs.slice(0, 4).map((job) => (
          <div className="list-row" key={job.id}>
            <div>
              <strong>{job.payload?.until?.toUpperCase?.() || job.kind || "JOB"} · {job.status}</strong>
              <p>{job.current_checkpoint || "대기"} · {formatDateTime(job.updated_at)}</p>
            </div>
            <div className="list-metric">
              <span>{Math.round((job.progress || 0) * 100)}%</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReviewDetailPanel({
  detail,
  loading,
  error,
  reviewNote,
  setReviewNote,
  reviewAssignee,
  setReviewAssignee,
  onReviewAction,
  actionPending,
  actionFeedback,
}) {
  if (loading) {
    return <div className="panel"><div className="empty-state">검토 상세를 불러오는 중입니다.</div></div>;
  }

  if (error) {
    return <div className="alert error">{error}</div>;
  }

  if (!detail) {
    return (
      <div className="panel">
        <div className="empty-state">검토 큐에서 턴을 선택하면 근거와 Judge 판단을 볼 수 있습니다.</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h4>검토 상세</h4>
      </div>

      <div className="detail-grid">
        <div className="detail-block">
          <p className="eyebrow">State</p>
          <strong>
            {detail.state} · 운영 {detail.overall_mean ?? "-"} / 보조 {detail.support_overall_mean ?? "-"}
          </strong>
          <p>{detail.state_reason}</p>
          <div className="chip-row">
            <span className="chip">live {detail.live_judge_count || 0}</span>
            <span className="chip">fallback {detail.fallback_judge_count || 0}</span>
            <span className="chip">
              grounding {detail.grounding_signals?.grounding_risk || "unknown"}
            </span>
            <span className={`chip status-chip ${detail.review_status || "pending"}`}>
              {formatReviewStatus(detail.review_status)}
            </span>
            <span className="chip owner-chip">
              {detail.assignee ? `담당 ${detail.assignee}` : "미할당"}
            </span>
            {detail.recheck_job ? (
              <span className={`chip recheck-chip ${detail.recheck_job.status || "unknown"}`}>
                {formatRecheckJobStatus(detail.recheck_job.status)}
              </span>
            ) : null}
          </div>
          {detail.review_action ? (
            <small>
              최근 조치 {REVIEW_ACTION_LABELS[detail.review_action.action] || detail.review_action.action} ·{" "}
              {formatDateTime(detail.review_action.updated_at)}
            </small>
          ) : null}
        </div>

        <div className="detail-block">
          <p className="eyebrow">Conversation</p>
          <strong>고객 질문</strong>
          <p>{detail.user_query}</p>
          <strong>콜봇 답변</strong>
          <p>{detail.bot_answer}</p>
        </div>
      </div>

      <div className="detail-block">
        <p className="eyebrow">Review Actions</p>
        <input
          value={reviewAssignee}
          onChange={(event) => setReviewAssignee(event.target.value)}
          placeholder="담당자 이름 또는 이메일"
        />
        <textarea
          className="action-note"
          rows="3"
          value={reviewNote}
          onChange={(event) => setReviewNote(event.target.value)}
          placeholder="검토 메모 또는 후속 조치 기록"
        />
        <div className="action-row">
          <button
            type="button"
            className="ghost-button action-button assign"
            disabled={actionPending}
            onClick={() => onReviewAction?.("assign")}
          >
            <Users size={16} />
            담당자 지정
          </button>
          <button
            type="button"
            className="ghost-button action-button approve"
            disabled={actionPending}
            onClick={() => onReviewAction?.("approve")}
          >
            <CheckCircle2 size={16} />
            승인
          </button>
          <button
            type="button"
            className="ghost-button action-button hold"
            disabled={actionPending}
            onClick={() => onReviewAction?.("hold")}
          >
            <PauseCircle size={16} />
            보류
          </button>
          <button
            type="button"
            className="primary-button action-button"
            disabled={actionPending}
            onClick={() => onReviewAction?.("recheck")}
          >
            <RotateCcw size={16} />
            재평가
          </button>
        </div>
        {actionFeedback ? <small>{actionFeedback}</small> : null}
      </div>

      <div className="detail-block">
        <p className="eyebrow">Review Timeline</p>
        {detail.review_history?.length ? (
          <div className="timeline">
            {detail.review_history.map((item, index) => (
              <div className="timeline-item" key={`${item.updated_at || index}-${item.action}`}>
              <div className="timeline-head">
                <strong>{REVIEW_ACTION_LABELS[item.action] || item.action}</strong>
                <small>{formatDateTime(item.updated_at)}</small>
              </div>
              {item.assignee ? <small>담당자 {item.assignee}</small> : null}
              {item.note ? <p>{item.note}</p> : <p>메모 없음</p>}
              {item.pipeline_job_id ? <small>pipeline job {item.pipeline_job_id}</small> : null}
            </div>
          ))}
          </div>
        ) : (
          <div className="empty-state">아직 기록된 조치 이력이 없습니다.</div>
        )}
      </div>

      <div className="detail-block">
        <p className="eyebrow">Recheck Diff</p>
        {detail.recheck_comparison ? (
          <div className="stack compact">
            <div className="comparison-grid">
              <div className="comparison-card">
                <strong>재평가 요청 시점</strong>
                <p>{formatDateTime(detail.recheck_comparison.action_at)}</p>
                <small>변경 필드 {detail.recheck_comparison.changed_fields?.join(", ") || "없음"}</small>
              </div>
              <div className="comparison-card">
                <strong>상태 변화</strong>
                <p>
                  {detail.recheck_comparison.before?.state || "-"} →{" "}
                  {detail.recheck_comparison.after?.state || "-"}
                </p>
                <small>{detail.recheck_comparison.state_changed ? "상태가 변경됨" : "상태 변화 없음"}</small>
              </div>
              <div className="comparison-card">
                <strong>운영 점수 변화</strong>
                <p>
                  {detail.recheck_comparison.before?.overall_mean ?? "-"} →{" "}
                  {detail.recheck_comparison.after?.overall_mean ?? "-"}
                </p>
                <small className={deltaTone(detail.recheck_comparison.overall_delta)}>
                  Δ {formatDelta(detail.recheck_comparison.overall_delta)}
                </small>
              </div>
              <div className="comparison-card">
                <strong>보조 점수 변화</strong>
                <p>
                  {detail.recheck_comparison.before?.support_overall_mean ?? "-"} →{" "}
                  {detail.recheck_comparison.after?.support_overall_mean ?? "-"}
                </p>
                <small className={deltaTone(detail.recheck_comparison.support_overall_delta)}>
                  Δ {formatDelta(detail.recheck_comparison.support_overall_delta)}
                </small>
              </div>
              <div className="comparison-card">
                <strong>Grounding</strong>
                <p>
                  {detail.recheck_comparison.before?.grounding_risk || "-"} →{" "}
                  {detail.recheck_comparison.after?.grounding_risk || "-"}
                </p>
                <small>{detail.recheck_comparison.grounding_changed ? "grounding 변화" : "변화 없음"}</small>
              </div>
              <div className="comparison-card">
                <strong>Top Chunk</strong>
                <p>
                  {(detail.recheck_comparison.before?.top_chunk_ids || []).join(", ") || "-"} →{" "}
                  {(detail.recheck_comparison.after?.top_chunk_ids || []).join(", ") || "-"}
                </p>
                <small>{detail.recheck_comparison.top_chunk_changed ? "근거 문서가 변경됨" : "동일한 근거 유지"}</small>
              </div>
            </div>

            <div className="snapshot-grid">
              <SnapshotPanel title="Before Snapshot" snapshot={detail.recheck_comparison.before} />
              <SnapshotPanel title="After Snapshot" snapshot={detail.recheck_comparison.after} />
            </div>

            <JudgeDiffPanel comparison={detail.recheck_comparison} />
            <TopChunkDiffPanel comparison={detail.recheck_comparison} />
          </div>
        ) : (
          <div className="empty-state">아직 재평가 비교 기준선이 없습니다.</div>
        )}
      </div>

      <div className="detail-block">
        <p className="eyebrow">Top Chunks</p>
        {detail.top_chunks?.length ? (
          <div className="list">
            {detail.top_chunks.map((chunk) => (
              <div className="list-row detail-row" key={chunk.chunk_id || `${chunk.doc_id}-${chunk.score}`}>
                <div>
                  <strong>{chunk.doc_id || chunk.chunk_id || "unknown chunk"}</strong>
                  <p>{chunk.doc_type || "unknown"} · score {chunk.score ?? "-"}</p>
                  <small>{chunk.parent_text || chunk.text}</small>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state">검색 근거가 없습니다.</div>
        )}
      </div>

      <div className="detail-block">
        <p className="eyebrow">Judge Breakdown</p>
        <div className="judge-grid">
          {(detail.judges || []).map((judge) => (
            <div className="judge-card" key={judge.model}>
              <strong>
                {judge.model} · {judge.source}
              </strong>
              <p>
                overall {judge.overall_score} · acc {judge.accuracy} · grounding {judge.groundedness}
              </p>
              <small>{judge.reason_summary}</small>
              <ChipList items={judge.key_issues} tone="warning" />
              <ChipList items={judge.flow_issues} tone="neutral" />
              <ChipList items={judge.risk_flags} tone="danger" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ChipList({ items, tone = "neutral" }) {
  if (!items?.length) return null;
  return (
    <div className="chip-row">
      {items.map((item) => (
        <span className={`chip ${tone}`} key={`${tone}-${item}`}>
          {item}
        </span>
      ))}
    </div>
  );
}

function mergeJobs(items, incoming) {
  const next = [incoming, ...items.filter((item) => item.id !== incoming.id)];
  next.sort((left, right) => String(right.updated_at || "").localeCompare(String(left.updated_at || "")));
  return next;
}

const REVIEW_ACTION_LABELS = {
  assign: "담당자 지정",
  approve: "승인",
  hold: "보류",
  recheck: "재평가",
};

function pickActiveJob(jobs, previous) {
  if (previous && jobs.some((item) => item.id === previous.id)) {
    return jobs.find((item) => item.id === previous.id) || previous;
  }
  return jobs.find((item) => ["queued", "running"].includes(item.status)) || jobs[0] || null;
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ko-KR", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRatio(value) {
  if (value == null) return "-";
  return `${(value * 100).toFixed(1)}%`;
}

function formatVerdict(value) {
  if (value == null) return "-";
  return value ? "ok" : "miss";
}

function formatReviewStatus(value) {
  return {
    pending: "대기",
    approved: "승인 완료",
    hold: "보류",
    recheck: "재평가 요청",
  }[value || "pending"] || "대기";
}

function formatRecheckJobStatus(value) {
  return {
    queued: "재평가 대기",
    running: "재평가 진행중",
    completed: "재평가 완료",
    failed: "재평가 실패",
    error: "재평가 오류",
  }[value || ""] || "재평가 상태";
}

function filterReviewQueue(items, filters) {
  const query = (filters.search || "").trim().toLowerCase();
  const owner = (filters.owner || "").trim().toLowerCase();
  return items.filter((item) => {
    if (filters.status !== "all" && (item.review_status || "pending") !== filters.status) {
      return false;
    }
    if (filters.state !== "all" && item.state !== filters.state) {
      return false;
    }
    if (owner && !(item.assignee || "").toLowerCase().includes(owner)) {
      return false;
    }
    if (!query) {
      return true;
    }
    const haystack = [
      item.user_query,
      item.source_file,
      item.conv_id,
      item.state,
      item.review_status,
      item.assignee,
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  });
}

function formatDelta(value) {
  if (value == null) return "-";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function deltaTone(value) {
  if (value == null || value === 0) return "";
  return value > 0 ? "delta-positive" : "delta-negative";
}

function SnapshotPanel({ title, snapshot }) {
  if (!snapshot) {
    return (
      <div className="comparison-card">
        <strong>{title}</strong>
        <p>-</p>
      </div>
    );
  }

  return (
    <div className="comparison-card snapshot-panel">
      <strong>{title}</strong>
      <div className="chip-row compact">
        <span className="chip">{snapshot.state || "-"}</span>
        <span className="chip">overall {snapshot.overall_mean ?? "-"}</span>
        <span className="chip">support {snapshot.support_overall_mean ?? "-"}</span>
        <span className="chip">grounding {snapshot.grounding_risk || "-"}</span>
      </div>
      <small>top1 {snapshot.top1_score ?? "-"}</small>
      <small>live {snapshot.live_judge_count ?? 0} / fallback {snapshot.fallback_judge_count ?? 0}</small>
    </div>
  );
}

function JudgeDiffPanel({ comparison }) {
  const rows = mergeJudgeRows(comparison?.before?.judges, comparison?.after?.judges);
  return (
    <div className="detail-block">
      <p className="eyebrow">Judge Side-By-Side</p>
      {rows.length ? (
        <div className="judge-diff-grid">
          {rows.map((row) => (
            <div className="judge-card" key={row.model}>
              <strong>{row.model}</strong>
              <p>
                overall {row.before?.overall_score ?? "-"} → {row.after?.overall_score ?? "-"}
              </p>
              <small className={deltaTone(scoreDelta(row.after?.overall_score, row.before?.overall_score))}>
                Δ {formatDelta(scoreDelta(row.after?.overall_score, row.before?.overall_score))}
              </small>
              <small>
                grounding {row.before?.groundedness ?? "-"} → {row.after?.groundedness ?? "-"}
              </small>
              <small>
                {row.before?.reason_summary || "이전 요약 없음"} → {row.after?.reason_summary || "현재 요약 없음"}
              </small>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">비교 가능한 Judge 스냅샷이 없습니다.</div>
      )}
    </div>
  );
}

function TopChunkDiffPanel({ comparison }) {
  const beforeChunks = comparison?.before?.top_chunks || [];
  const afterChunks = comparison?.after?.top_chunks || [];
  return (
    <div className="detail-block">
      <p className="eyebrow">Top Chunk Side-By-Side</p>
      <div className="snapshot-grid">
        <ChunkColumn title="Before Chunks" chunks={beforeChunks} />
        <ChunkColumn title="After Chunks" chunks={afterChunks} />
      </div>
    </div>
  );
}

function ChunkColumn({ title, chunks }) {
  return (
    <div className="comparison-card chunk-column">
      <strong>{title}</strong>
      {chunks.length ? (
        <div className="stack compact">
          {chunks.map((chunk, index) => (
            <div className="chunk-mini" key={`${title}-${chunk.id || index}`}>
              <p>
                {chunk.id || "unknown"} · {chunk.doc_type || "unknown"} · {chunk.score ?? "-"}
              </p>
              <small>{chunk.text || "-"}</small>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">기록된 chunk가 없습니다.</div>
      )}
    </div>
  );
}

function mergeJudgeRows(beforeJudges, afterJudges) {
  const rows = new Map();
  (beforeJudges || []).forEach((judge) => {
    rows.set(judge.model, { model: judge.model, before: judge, after: null });
  });
  (afterJudges || []).forEach((judge) => {
    const existing = rows.get(judge.model) || { model: judge.model, before: null, after: null };
    existing.after = judge;
    rows.set(judge.model, existing);
  });
  return Array.from(rows.values());
}

function scoreDelta(current, previous) {
  if (current == null || previous == null) return null;
  return Number(current) - Number(previous);
}

function providerStatusLabel(status) {
  return {
    missing_key: "키 없음",
    sdk_missing: "SDK 없음",
    ready_to_probe: "probe 가능",
    live_ok: "live ok",
    degraded: "fallback",
  }[status || ""] || "unknown";
}

function providerChipTone(status) {
  if (status === "live_ok") return "";
  if (status === "ready_to_probe") return "warning";
  return "danger";
}

function normalizeError(error) {
  return error?.message?.replace(/^"|"$/g, "") || "요청 처리 중 오류가 발생했습니다.";
}

export default App;
