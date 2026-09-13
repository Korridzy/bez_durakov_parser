import { useCallback, useEffect, useRef, useState } from "react";
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
import { useAccent } from "./theme";

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
  const hasData = sources.length > 0 || hasDataset;
  return (
    <div className={"app " + (sidebar ? "sidebar-visible" : "sidebar-hidden")}>
      <div
        className="mobile-scrim"
        onClick={() => setSidebar(false)}
        aria-hidden="true"
      />
      <div className="sidebar-shell">
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
      </div>
      <main className="main-panel">
        <header className="workspace-header">
          <div className="sidebar-control">
            {!sidebar && (
              <button
                className="icon-button"
                aria-label="Показать боковую панель"
                onClick={() => setSidebar(true)}
              >
                <PanelLeftOpen size={19} />
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
                <h1>{hasData ? "Хей" : "Yo, чел"}</h1>
                <p>
                  {hasData
                    ? "Какие вопросы по проекту?"
                    : "Мне нужна инфа, чтобы дать тебе толковые советы"}
                </p>
                {!hasData && (
                  <button
                    className="welcome-connect primary-button"
                    onClick={() => setDialog("source-add")}
                  >
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
                  />
                ))}
                {jobId && <JobView job={job} connection={connection} />}
              </>
            )}
            <div ref={bottomRef} />
          </div>
        </div>
        <div className="composer-dock">
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
            onSource={(source) => void openSource(source)}
            onManageSources={() =>
              setDialog(sources.length ? "sources" : "source-add")
            }
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
      </main>
      {(dialog === "settings" || dialog === "model-add") && (
        <SettingsDialog
          accent={accent}
          onAccent={setAccent}
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
