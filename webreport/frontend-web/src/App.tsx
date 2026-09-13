import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import {
  ArrowDown,
  Database,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  X,
} from "lucide-react";
import type { Chat, Job, Source, Workspace } from "./types";
import { api, ApiError, post } from "./api";
import { Sidebar } from "./Sidebar";
import { Composer } from "./Composer";
import { JobView, MessageView } from "./Conversation";
import { SourcePreview, SourcesDialog } from "./SourceDialog";
import { SettingsDialog } from "./SettingsDialog";
import { Alert, Logo, Modal, Spinner } from "./ui";
import { useAccent, useMotion } from "./theme";
import { Atmosphere } from "./Atmosphere";
import type { Activity } from "./mascot/Expedition";
import { CompanionStage, useCompanion, type CompanionSpeech } from "./mascot/Companion";
import { Trapezoid } from "./Trapezoid";
import { ProjectInfoPanel, MIN_PROJECT_INFO_WIDTH } from "./ProjectInfoPanel";
import { AnalysisPanel } from "./AnalysisPanel";
import { PanelResizeHandle, usePanelResize } from "./PanelResizeHandle";

type Edit = {
  type: "projects" | "chats";
  id: string;
  name: string;
  remove?: boolean;
};
type Pending = {
  message: string;
  request_id: string;
  model_id: string;
  effort: string;
};
export default function App() {
  const [accent, setAccent] = useAccent();
  const [motion, setMotion] = useMotion();
  const [companion, setCompanion] = useCompanion();
  const [addressing, setAddressing] = useState(false);
  const heroAnchor = useRef<HTMLDivElement>(null), dockAnchor = useRef<HTMLDivElement>(null);
  const [reaction, setReaction] = useState<Activity>("rest");
  const [workspace, setWorkspace] = useState<Workspace>();
  const [projectId, setProjectId] = useState("");
  const [chatId, setChatId] = useState("");
  const [chat, setChat] = useState<Chat>();
  const [draft, setDraft] = useState("");
  const [modelId, setModelId] = useState("system");
  const [effort, setEffort] = useState("auto");
  const [sidebar, setSidebar] = useState(() => window.innerWidth > 850);
  const [dialog, setDialog] = useState("");
  const [preview, setPreview] = useState<Source>();
  const [infoOpen, setInfoOpen] = useState(false);
  const [analysisId, setAnalysisId] = useState("");
  useEffect(() => { setAnalysisId(""); }, [chatId, projectId]);
  useEffect(() => { if (infoOpen) setAnalysisId(""); }, [infoOpen]);
  const [infoHighlight, setInfoHighlight] = useState(0);
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);
  const narrowInfo = viewportWidth <= 760;
  const reservedPanelWidth = infoOpen ? MIN_PROJECT_INFO_WIDTH
    : analysisId ? Math.min(860, Math.max(450, viewportWidth * 0.48)) : 0;
  const sidebarResize = usePanelResize({
    storageKey: "wr-sidebar-width",
    minWidth: 264,
    maxWidth: Math.max(264, Math.min(480, viewportWidth - 400 - reservedPanelWidth)),
    defaultWidth: () => 264,
    edge: "right",
    disabled: !sidebar || viewportWidth <= 850 || (infoOpen && viewportWidth <= 1150),
  });
  const [editingSource, setEditingSource] = useState<Source>();
  const [edit, setEdit] = useState<Edit>();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [connection, setConnection] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingChat, setLoadingChat] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const [saving, setSaving] = useState(false);
  const [bootError, setBootError] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null),
    scrollRef = useRef<HTMLDivElement>(null),
    bottomRef = useRef<HTMLDivElement>(null);
  const selection = useRef({ chatId: "", projectId: "" });
  const draftKey = chatId || "project:" + projectId;
  const pending = useRef<Record<string, Pending>>(
    (() => {
      try {
        return JSON.parse(sessionStorage.getItem("wr-pending") || "{}");
      } catch {
        return {};
      }
    })(),
  );
  const savePending = () => {
    try {
      sessionStorage.setItem("wr-pending", JSON.stringify(pending.current));
    } catch {}
  };
  const refresh = useCallback(async () => {
    const data = await api<Workspace>("/workspace");
    setWorkspace(data);
    return data;
  }, []);
  const manageSource = (source: Source) => {
    setPreview(undefined);
    setEditingSource(source);
    setDialog("source-edit");
  };
  const openSource = async (source: Source) => {
    let latest = source;
    try {
      const data = await refresh();
      const found = data.sources.find((s) => s.id === source.id);
      if (!found) return;
      latest = found;
    } catch {
      /* The report provides a retry if the server is unreachable. */
    }
    if (latest.connected) setPreview(latest);
    else manageSource(latest);
  };
  const connectionChanged = (source: Source, needsKey = false) => {
    setWorkspace(
      (current) =>
        current && {
          ...current,
          sources: current.sources.map((s) =>
            s.id === source.id ? source : s,
          ),
        },
    );
    if (needsKey) manageSource(source);
  };
  useEffect(() => {
    const check = () => {
      if (document.visibilityState === "visible")
        void refresh().catch(() => {});
    };
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
    return () => {
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", check);
    };
  }, [refresh]);
  const selectProject = useCallback((id: string) => {
    setInfoOpen(false);
    setInfoHighlight(0);
    setReaction("rest");
    setProjectId(id);
    setChatId("");
    setChat(undefined);
    setJobId("");
    setJob(null);
    setError("");
    setLoadingChat(false);
    selection.current = { chatId: "", projectId: id };
    localStorage.setItem("wr-selection", JSON.stringify(selection.current));
  }, []);
  const loadChat = useCallback(async (id: string) => {
    setInfoOpen(false);
    setInfoHighlight(0);
    setReaction("rest");
    selection.current.chatId = id;
    setChatId(id);
    setLoadingChat(true);
    setChat(undefined);
    setJobId("");
    setJob(null);
    setError("");
    try {
      const next = await api<Chat>("/chats/" + id);
      if (selection.current.chatId !== id) return;
      setChat(next);
      setProjectId(next.project_id);
      selection.current = { chatId: id, projectId: next.project_id };
      setJobId(next.active_job || "");
      const previous = pending.current[id];
      if (
        previous &&
        (next.active_job === previous.request_id ||
          next.messages?.some((m) => m.request_id === previous.request_id))
      ) {
        delete pending.current[id];
        try {
          sessionStorage.setItem("wr-pending", JSON.stringify(pending.current));
        } catch {}
      } else if (previous)
        setError("Проверьте отправку предыдущего сообщения.");
      setModelId(next.model_id || "system");
      setEffort(next.effort || "auto");
      localStorage.setItem("wr-selection", JSON.stringify(selection.current));
      setAtBottom(true);
      if (window.innerWidth < 850) setSidebar(false);
    } catch (e) {
      if (selection.current.chatId === id) setError((e as Error).message);
    } finally {
      if (selection.current.chatId === id) setLoadingChat(false);
    }
  }, []);
  const boot = useCallback(async () => {
    setBootError("");
    try {
      const data = await refresh();
      let saved: { chatId?: string; projectId?: string } = {};
      try {
        saved = JSON.parse(localStorage.getItem("wr-selection") || "{}");
      } catch {}
      if (saved.chatId && data.chats.some((c) => c.id === saved.chatId))
        await loadChat(saved.chatId);
      else
        selectProject(
          data.projects.find((p) => p.id === saved.projectId)?.id ||
            data.projects[0]?.id ||
            "",
        );
    } catch (e) {
      setBootError((e as Error).message);
    }
  }, [refresh, loadChat, selectProject]);
  useEffect(() => {
    void boot();
  }, [boot]);
  useEffect(() => {
    if (workspace && !workspace.models.some((m) => m.id === modelId)) {
      setModelId("system");
      setEffort("auto");
    }
  }, [workspace, modelId]);
  useEffect(() => {
    try {
      setDraft(localStorage.getItem("wr-draft:" + draftKey) || "");
    } catch {
      setDraft("");
    }
  }, [draftKey]);
  const changeDraft = (value: string) => {
    setDraft(value);
    try {
      localStorage.setItem("wr-draft:" + draftKey, value);
    } catch {}
  };
  useEffect(() => {
    if (!infoHighlight) return;
    const timer = setTimeout(() => setInfoHighlight(0), 3200);
    return () => clearTimeout(timer);
  }, [infoHighlight]);
  useEffect(() => {
    const update = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  const startProjectInterview = async () => {
    if (!projectId || sending || jobId || loadingChat) return;
    const origin = { ...selection.current };
    let id = chatId;
    setSending(true);
    setError("");
    setDialog("");
    setInfoOpen(false);
    try {
      if (!id) {
        const created = await post<Chat>("/chats", { project_id: origin.projectId });
        id = created.id;
        if (selection.current.projectId !== origin.projectId || selection.current.chatId !== origin.chatId) return;
        localStorage.setItem("wr-draft:" + id, draft);
        selection.current = { chatId: id, projectId: origin.projectId };
        localStorage.setItem("wr-selection", JSON.stringify(selection.current));
        setChatId(id);
        setChat(created);
      }
      const updated = await post<Chat>("/chats/" + id + "/project-interview");
      if (selection.current.chatId === id && selection.current.projectId === origin.projectId) {
        setChat(updated);
        setAtBottom(true);
        setInfoHighlight(Date.now());
        setTimeout(() => inputRef.current?.focus(), 0);
      }
      await refresh();
    } catch (e) {
      if (selection.current.projectId === origin.projectId) setError((e as Error).message);
    } finally { setSending(false); }
  };
  const endProjectInterview = async () => {
    const id = chatId;
    try {
      const updated = await api<Chat>("/chats/" + id + "/project-interview", { method: "DELETE" });
      if (selection.current.chatId === id) { setChat(updated); inputRef.current?.focus(); }
    } catch (e) { setError((e as Error).message); }
  };
  useEffect(() => {
    if (atBottom)
      bottomRef.current?.scrollIntoView({ behavior: "instant", block: "end" });
  }, [chat?.messages?.length, job?.events, atBottom]);
  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    let timeout: ReturnType<typeof setTimeout>;
    let retries = 0;
    const poll = async () => {
      try {
        const next = await api<Job>("/jobs/" + jobId);
        if (stopped) return;
        setJob(next);
        setConnection("");
        retries = 0;
        if (next.status !== "running") {
          const latest = await api<Chat>("/chats/" + selection.current.chatId);
          if (stopped) return;
          setChat(latest);
          setReaction(
            next.status === "completed"
              ? "success"
              : next.status === "failed"
                ? "error"
                : "rest",
          );
          setJobId("");
          setJob(null);
          await refresh();
          return;
        }
      } catch (e) {
        if (stopped) return;
        retries++;
        setConnection(
          navigator.onLine
            ? `Восстанавливаю связь · попытка ${retries}`
            : "Нет интернета · ответ продолжает готовиться на сервере",
        );
      }
      if (!stopped)
        timeout = setTimeout(
          poll,
          Math.min(1000 * 2 ** Math.min(retries, 3), 8000),
        );
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timeout);
    };
  }, [jobId, refresh]);
  const newChat = (id = projectId) => {
    selectProject(id);
    setDraft("");
    localStorage.removeItem("wr-draft:project:" + id);
    setTimeout(() => inputRef.current?.focus(), 0);
    if (window.innerWidth < 850) setSidebar(false);
  };
  const setModel = (id: string) => {
    setModelId(id);
    if (!workspace?.models.find((m) => m.id === id)?.efforts.includes(effort))
      setEffort("auto");
  };
  const send = async (retryMessage?: string) => {
    const content = pending.current[chatId]?.message || retryMessage || draft;
    if (!content.trim() || sending || jobId || loadingChat || !projectId)
      return;
    setSending(true);
    setReaction("rest");
    setError("");
    setConnection("");
    let id = chatId;
    const origin = { ...selection.current };
    const isCurrent = () =>
      selection.current.chatId === id &&
      selection.current.projectId === origin.projectId;
    try {
      if (!pending.current[id]) {
        if (!id) {
          const created = await post<Chat>("/chats", { project_id: projectId });
          id = created.id;
          localStorage.setItem("wr-draft:" + id, content);
          if (
            selection.current.chatId === origin.chatId &&
            selection.current.projectId === origin.projectId
          ) {
            selection.current = { chatId: id, projectId };
            setChatId(id);
            setChat(created);
            localStorage.setItem(
              "wr-selection",
              JSON.stringify(selection.current),
            );
          }
        }
        pending.current[id] = {
          message: content.trim(),
          request_id: crypto.randomUUID().replaceAll("-", ""),
          model_id: modelId,
          effort,
        };
        savePending();
      }
      const request = pending.current[id];
      const { job_id } = await post<{ job_id: string }>(
        "/chats/" + id + "/messages",
        request,
      );
      delete pending.current[id];
      savePending();
      localStorage.removeItem("wr-draft:" + id);
      if (
        !origin.chatId &&
        localStorage.getItem("wr-draft:project:" + projectId) === content
      )
        localStorage.removeItem("wr-draft:project:" + projectId);
      if (isCurrent()) {
        setDraft("");
        setJobId(job_id);
        setAtBottom(true);
      }
      const latest = await api<Chat>("/chats/" + id);
      if (isCurrent()) setChat(latest);
      await refresh();
    } catch (e) {
      const err = e as ApiError;
      if (err.status !== 0 && err.status < 500) {
        delete pending.current[id];
        savePending();
      }
      if (isCurrent())
        setError(
          err.status === 0
            ? "Нет связи с сервером. Повторная отправка проверит этот же запрос."
            : err.message,
        );
    } finally {
      setSending(false);
    }
  };
  const retry = () => {
    const last = chat?.messages?.findLast((m) => m.role === "user");
    if (last) void send(last.content);
  };
  const cancel = async () => {
    try {
      await post("/jobs/" + jobId + "/cancel");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const editObject = (
    type: Edit["type"],
    id: string,
    currentName: string,
    remove = false,
  ) => {
    setEdit({ type, id, name: currentName, remove });
    setName(currentName);
    setError("");
  };
  const submitObject = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      if (edit) {
        await api("/" + edit.type + "/" + edit.id, {
          method: edit.remove ? "DELETE" : "PATCH",
          body: edit.remove ? undefined : JSON.stringify({ name }),
        });
        const data = await refresh();
        if (
          edit.remove &&
          ((edit.type === "projects" && edit.id === projectId) ||
            (edit.type === "chats" && edit.id === chatId))
        )
          selectProject(
            data.projects.find((p) => p.id === projectId)?.id ||
              data.projects[0]?.id ||
              "",
          );
        setEdit(undefined);
      } else {
        const created = await post<{ id: string }>("/projects", { name });
        await refresh();
        selectProject(created.id);
        setDialog("");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  if (!workspace)
    return (
      <main className="boot">
        <Logo />
        {bootError ? (
          <>
            <p>{bootError}</p>
            <button className="secondary-button" onClick={() => void boot()}>
              <RefreshCw size={16} />
              Повторить подключение
            </button>
          </>
        ) : (
          <Spinner label="Открываю рабочее пространство…" />
        )}
      </main>
    );
  const project =
    workspace.projects.find((p) => p.id === projectId) || workspace.projects[0];
  const sources = workspace.sources.filter((s) => s.project_id === project?.id);
  const empty = !chat?.messages?.length && !jobId;
  const hasDataset = !!project?.dataset_module && !sources.length;
  const hasProjectInfo = !!project?.info?.content.trim();
  const hasData = sources.length > 0 || hasDataset || hasProjectInfo;
  const activity: Activity =
    error || connection
      ? "error"
      : loadingChat
        ? "thinking"
        : sending || jobId
          ? "working"
          : empty
            ? "welcome"
            : reaction;
  const speech: CompanionSpeech | undefined = activity === "working"
    ? { title: "Копаю…", text: "Сейчас найду самое интересное." }
    : chat?.project_interview
    ? { title: "Расскажи о проекте", text: "Чем вы занимаетесь и что хотите узнать? Я запомню главное.", action: { label: "Перейти к вопросам", onClick: () => void endProjectInterview(), disabled: sending || !!jobId } }
    : empty
      ? hasData
        ? { title: "Хей!", text: "Какие вопросы по проекту?" }
        : { title: "Давай знакомиться!", text: "Расскажи о проекте или подключи данные — и начнём.", action: { label: "Подключить данные", onClick: () => setDialog("source-add") } }
      : activity === "thinking"
          ? { title: "Так-так…", text: "Сейчас разберусь." }
          : undefined;
  return (
    <div
      className={"app " + (sidebar ? "sidebar-visible" : "sidebar-hidden") + (infoOpen ? " info-visible" : "") + (analysisId ? " analysis-visible" : "")}
      data-motion={motion}
    >
      <div
        className="mobile-scrim"
        onClick={() => setSidebar(false)}
        aria-hidden="true"
      />
      <div
        className={"sidebar-shell" + (sidebarResize.resizing ? " is-resizing" : "")}
        style={{ "--sidebar-width": `${sidebarResize.width}px` } as CSSProperties}
        inert={(infoOpen || !!analysisId) && narrowInfo}
      >
        <Sidebar
          visible={sidebar}
          projects={workspace.projects}
          chats={workspace.chats}
          projectId={projectId}
          chatId={chatId}
          onProject={selectProject}
          onChat={(id) => void loadChat(id)}
          onNewChat={newChat}
          onNewProject={() => {
            setDialog("project");
            setName("");
            setError("");
          }}
          onSettings={() => setDialog("settings")}
          onClose={() => setSidebar(false)}
          onRename={(type, id, name) => editObject(type, id, name)}
          onDelete={(type, id, name) => editObject(type, id, name, true)}
          activeChatIds={workspace.active_jobs.map((j) => j.chat_id)}
        />
        <PanelResizeHandle resize={sidebarResize} label="Ширина панели проектов и чатов" controls="project-sidebar" />
      </div>
      <main
        onFocusCapture={(event) => { if (event.target instanceof HTMLTextAreaElement) setAddressing(true); }}
        onBlurCapture={(event) => { if (event.target instanceof HTMLTextAreaElement) setAddressing(false); }}
        inert={(infoOpen || !!analysisId) && narrowInfo}
        className={
          "main-panel " + (empty ? "new-expedition" : "reading-expedition")
        }
      >
        <Atmosphere />
        <header className="workspace-header">
          <div className="sidebar-control">
            {!sidebar && (
              <button
                className="icon-button sidebar-toggle-button"
                aria-label="Показать боковую панель"
                title="Показать боковую панель"
                aria-expanded={false}
                aria-controls="project-sidebar"
                onClick={() => setSidebar(true)}
              >
                <PanelLeftOpen size={19} strokeWidth={1.8} />
              </button>
            )}
          </div>
          <div className="source-toolbar">
            <button
              className="sources-button"
              aria-label="Управление источниками"
              onClick={() => setDialog("sources")}
              disabled={!project}
            >
              <Database size={16} />
              <span>
                {sources.length > 2
                  ? `Все источники · ${sources.length}`
                  : sources.length
                    ? "Источники"
                    : "Подключить данные"}
              </span>
              <Plus size={15} />
            </button>
          </div>
        </header>
        <div
          className={"conversation-scroll " + (empty ? "is-empty" : "")}
          ref={scrollRef}
          onScroll={() => {
            const el = scrollRef.current;
            setAtBottom(
              !!el && el.scrollHeight - el.scrollTop - el.clientHeight < 100,
            );
          }}
        >
          <div className="conversation">
            {loadingChat ? (
              <div className="chat-loading">
                <Spinner label="Открываю чат…" />
              </div>
            ) : empty ? (
              <section className="welcome">
                {companion !== "none" && <div className="companion-anchor hero" ref={heroAnchor} aria-hidden="true" />}
                {companion === "none" && <><h1>{hasData ? "Хей!" : "Давай знакомиться!"}</h1>
                <p>
                  {hasData
                    ? "Какие вопросы по проекту?"
                    : "Мне нужна инфа, чтобы дать тебе толковые советы"}
                </p></>}
                {!hasData && companion === "none" && (
                  <button
                    className="welcome-connect primary-button shaped-control"
                    onClick={() => setDialog("source-add")}
                  >
                    <Trapezoid radius={13} />
                    <Plus size={20} />
                    Добавить источник
                  </button>
                )}
              </section>
            ) : (
              <>
                {chat?.messages?.map((message) => (
                <MessageView
                    key={message.id}
                    message={message}
                  onRetry={retry}
                  onProjectInfo={() => setInfoOpen(true)}
                  onAnalysis={id => { setInfoOpen(false); setAnalysisId(id); }}
                  />
                ))}
                {jobId && <JobView job={job} connection={connection} />}
              </>
            )}
            <div ref={bottomRef} />
          </div>
        </div>
        <div className="composer-dock">
          {!empty && companion !== "none" && (
            <div className="companion-slot">
              <div className="companion-anchor compact" ref={dockAnchor} aria-hidden="true" />
            </div>
          )}
          {!atBottom && !empty && (
            <button
              className="scroll-bottom"
              aria-label="К последнему сообщению"
              onClick={() => {
                setAtBottom(true);
                bottomRef.current?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              <ArrowDown size={17} />
            </button>
          )}
          {error && !edit && dialog !== "project" && (
            <div className="send-error">
              <Alert>
                {error}
                {pending.current[chatId] && (
                  <button className="text-button" onClick={() => void send()}>
                    Проверить отправку
                  </button>
                )}
              </Alert>
              <button
                className="icon-button"
                aria-label="Скрыть ошибку"
                onClick={() => setError("")}
              >
                <X size={15} />
              </button>
            </div>
          )}
          <Composer
            sources={sources}
            hasDataset={hasDataset}
            hasProjectInfo={hasProjectInfo}
            onProjectInfo={() => hasProjectInfo ? setInfoOpen(true) : void startProjectInterview()}
            interview={!!chat?.project_interview}
            companionPresent={companion !== "none"}
            onEndInterview={() => void endProjectInterview()}
            highlight={infoHighlight}
            onSource={(source) => void openSource(source)}
            onManageSources={() => setDialog("sources")}
            value={draft}
            onChange={changeDraft}
            onSend={() => void send()}
            onCancel={() => void cancel()}
            running={!!jobId}
            disabled={sending || loadingChat || !project}
            models={workspace.models}
            modelId={modelId}
            onModel={setModel}
            effort={effort}
            onEffort={setEffort}
            onAddModel={() => setDialog("model-add")}
            onAddSource={() => setDialog("source-add")}
            inputRef={inputRef}
          />
        </div>
        <CompanionStage kind={companion} compact={!empty} active={!loadingChat} heroAnchor={heroAnchor} dockAnchor={dockAnchor} activity={activity} motion={motion} accent={accent} engaged={addressing} speech={speech} />
      </main>
      {analysisId && chatId && <AnalysisPanel key={chatId + analysisId} chatId={chatId} resultId={analysisId} onClose={() => setAnalysisId("")} modal={narrowInfo} />}
      {infoOpen && project && (
        <ProjectInfoPanel
          key={project.id}
          project={project}
          onClose={() => setInfoOpen(false)}
          onRefresh={refresh}
          onInterview={() => void startProjectInterview()}
          busy={sending || !!jobId || loadingChat}
          modal={narrowInfo}
        />
      )}
      {(dialog === "settings" || dialog === "model-add") && (
        <SettingsDialog
          accent={accent}
          onAccent={setAccent}
          motion={motion}
          onMotion={setMotion}
          companion={companion}
          onCompanion={setCompanion}
          workspace={workspace}
          onRefresh={refresh}
          onClose={() => setDialog("")}
          initialAdd={dialog === "model-add"}
          onSelect={setModel}
        />
      )}
      {(dialog === "sources" ||
        dialog === "source-add" ||
        dialog === "source-edit") &&
        project && (
          <SourcesDialog
            key={dialog + (dialog === "source-edit" ? editingSource?.id : "")}
            workspace={workspace}
            project={project}
            onRefresh={refresh}
            onClose={() => setDialog("")}
            initialAdd={dialog === "source-add"}
            initialSource={dialog === "source-edit" ? editingSource : undefined}
            onProjectInfo={() => { setDialog(""); setInfoOpen(true); }}
            onDescribeProject={() => void startProjectInterview()}
            busy={sending || !!jobId || loadingChat}
            onPreview={(s) => {
              setDialog("");
              void openSource(s);
            }}
          />
        )}
      {preview && (
        <SourcePreview
          key={preview.id}
          source={preview}
          provider={workspace.providers.find((p) => p.id === preview.provider)!}
          defaultPeriod={workspace.default_period}
          onClose={() => setPreview(undefined)}
          onManage={() =>
            manageSource(
              workspace.sources.find((s) => s.id === preview.id) || preview,
            )
          }
          onConnectionChange={connectionChanged}
        />
      )}
      {(dialog === "project" || edit) && (
        <Modal
          title={
            edit
              ? edit.remove
                ? "Удалить " + (edit.type === "projects" ? "проект" : "чат")
                : "Переименовать"
              : "Новый проект"
          }
          onClose={() => {
            setDialog("");
            setEdit(undefined);
            setError("");
          }}
        >
          <form className="connection-form" onSubmit={submitObject}>
            {edit?.remove ? (
              <p className="delete-copy">
                «{edit.name}» будет удалён
                {edit.type === "projects"
                  ? " вместе с чатами и подключениями"
                  : ""}
                . Данные в системах аналитики сохранятся.
              </p>
            ) : (
              <div className="field">
                <label htmlFor="project-name">Название</label>
                <input
                  id="project-name"
                  autoFocus
                  required
                  maxLength={100}
                  placeholder="Например, Аналитика сайта"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
            )}
            {error && <Alert>{error}</Alert>}
            <div className="form-bottom align-right">
              <button
                type="button"
                className="secondary-button"
                onClick={() => {
                  setDialog("");
                  setEdit(undefined);
                  setError("");
                }}
              >
                Отмена
              </button>
              <button
                className={edit?.remove ? "danger-button" : "primary-button"}
                disabled={saving || (!edit?.remove && !name.trim())}
              >
                {saving ? (
                  <Spinner />
                ) : edit ? (
                  edit.remove ? (
                    "Удалить"
                  ) : (
                    "Сохранить"
                  )
                ) : (
                  "Создать проект"
                )}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
