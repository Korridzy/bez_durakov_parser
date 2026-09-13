import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { FileText, MessageSquare, Pencil, RefreshCw, X } from "lucide-react";
import type { Project, ProjectInfo } from "./types";
import { api } from "./api";
import { MarkdownText } from "./Conversation";
import { Alert, Spinner } from "./ui";
import { PanelResizeHandle, usePanelResize } from "./PanelResizeHandle";
import "./project-info.css";

type Draft = { content: string; revision: number };
export const MIN_PROJECT_INFO_WIDTH = 360;
const MIN_CHAT_WIDTH = 400;
const defaultWidth = () =>
  Math.max(MIN_PROJECT_INFO_WIDTH, Math.min(580, window.innerWidth * 0.37));

export function ProjectInfoPanel({
  project,
  onClose,
  onRefresh,
  onInterview,
  busy,
  modal,
}: {
  project: Project;
  onClose: () => void;
  onRefresh: () => Promise<unknown>;
  onInterview: () => void;
  busy: boolean;
  modal: boolean;
}) {
  const [info, setInfo] = useState<ProjectInfo>();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>({ content: "", revision: 0 });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const panel = useRef<HTMLElement>(null);
  const [maxWidth, setMaxWidth] = useState(MIN_PROJECT_INFO_WIDTH);
  const resize = usePanelResize({
    storageKey: "wr-project-info-width",
    minWidth: MIN_PROJECT_INFO_WIDTH,
    maxWidth,
    defaultWidth,
    edge: "left",
    disabled: modal,
  });
  const heading = useRef<HTMLHeadingElement>(null);
  const draftKey = "wr-project-info-draft:" + project.id;
  const url = "/projects/" + project.id + "/info";

  useLayoutEffect(() => {
    const element = panel.current;
    const main = element?.parentElement?.querySelector(".main-panel");
    if (modal || !element || !main) return;
    // Reserve room for the chat, including when the left navigation collapses.
    const measure = () =>
      setMaxWidth(
        Math.max(
          MIN_PROJECT_INFO_WIDTH,
          Math.floor(
            element.parentElement!.getBoundingClientRect().right -
              main.getBoundingClientRect().left -
              MIN_CHAT_WIDTH,
          ),
        ),
      );
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(main);
    observer.observe(element.parentElement!);
    return () => observer.disconnect();
  }, [modal]);

  useEffect(() => {
    const previous = document.activeElement;
    heading.current?.focus();
    return () => {
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, []);

  useEffect(() => {
    let stopped = false;
    const read = async () => {
      try {
        const latest = await api<ProjectInfo>(url);
        if (!stopped) {
          setInfo((current) =>
            current && current.revision > latest.revision ? current : latest,
          );
          setLoadError("");
        }
      } catch (e) {
        if (!stopped) setLoadError((e as Error).message);
      }
    };
    void read();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void read();
    }, 4000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [url, project.info?.revision]);

  const rememberDraft = (next: Draft) => {
    setDraft(next);
    try {
      localStorage.setItem(draftKey, JSON.stringify(next));
    } catch {}
  };
  const startEdit = () => {
    if (!info) return;
    let next = {
      content: info.content || info.template || "",
      revision: info.revision,
    };
    try {
      const saved = JSON.parse(localStorage.getItem(draftKey) || "null");
      if (
        saved &&
        typeof saved.content === "string" &&
        typeof saved.revision === "number"
      )
        next = saved;
    } catch {}
    rememberDraft(next);
    setEditing(true);
    setError("");
  };
  const discard = () => {
    try {
      localStorage.removeItem(draftKey);
    } catch {}
    setEditing(false);
    setError("");
  };
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const saved = await api<ProjectInfo>(url, {
        method: "PUT",
        body: JSON.stringify(draft),
      });
      setInfo({ ...saved, template: info?.template });
      discard();
      await onRefresh();
    } catch (e) {
      setError((e as Error).message);
      try {
        setInfo(await api<ProjectInfo>(url));
      } catch {}
    } finally {
      setSaving(false);
    }
  };
  const conflict = !!info && editing && draft.revision !== info.revision;
  return (
    <aside
      ref={panel}
      id="project-info-panel"
      className="project-info-panel"
      style={modal ? undefined : { width: resize.width }}
      aria-labelledby="project-info-title"
      role={modal ? "dialog" : undefined}
      aria-modal={modal || undefined}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !saving) {
          e.stopPropagation();
          onClose();
        }
        if (modal && e.key === "Tab") {
          const focusable = Array.from(
            e.currentTarget.querySelectorAll<HTMLElement>(
              "button:not(:disabled), a[href], textarea:not(:disabled), summary",
            ),
          );
          const first = focusable[0],
            last = focusable.at(-1);
          if (
            e.shiftKey &&
            (document.activeElement === first ||
              document.activeElement === heading.current)
          ) {
            e.preventDefault();
            last?.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first?.focus();
          }
        }
      }}
    >
      <PanelResizeHandle
        resize={resize}
        label="Ширина информации о проекте"
        controls="project-info-panel"
      />
      <header className="project-info-header">
        <div className="project-info-heading">
          <FileText size={19} />
          <div>
            <h2 id="project-info-title" ref={heading} tabIndex={-1}>
              Информация о проекте
            </h2>
            <span>{project.name}</span>
          </div>
        </div>
        <button
          className="icon-button"
          aria-label="Закрыть информацию о проекте"
          disabled={saving}
          onClick={onClose}
        >
          <X size={19} />
        </button>
      </header>
      <div className="project-info-toolbar">
        <span>Источник для всех чатов проекта</span>
        {!editing && (
          <button
            className="secondary-button"
            onClick={startEdit}
            disabled={!info}
          >
            <Pencil size={14} />
            Редактировать
          </button>
        )}
      </div>
      <div className="project-info-body">
        {loadError && <Alert>{loadError}</Alert>}
        {error && <Alert>{error}</Alert>}
        {!info ? (
          <Spinner label="Открываю информацию о проекте…" />
        ) : editing ? (
          <>
            {conflict && (
              <div className="project-info-conflict" role="status">
                <strong>Появилась новая версия</strong>
                <p>
                  Ваш черновик сохранён. Скопируйте нужные правки, откройте
                  свежую версию ниже и добавьте их к ней.
                </p>
                <details>
                  <summary>Посмотреть свежую версию</summary>
                  <MarkdownText text={info.content || info.template || ""} />
                </details>
                <button
                  className="secondary-button"
                  onClick={() =>
                    rememberDraft({
                      content: info.content || info.template || "",
                      revision: info.revision,
                    })
                  }
                >
                  <RefreshCw size={14} />
                  Редактировать свежую версию
                </button>
              </div>
            )}
            <label
              className="project-info-editor-label"
              htmlFor="project-info-editor"
            >
              Сводка о проекте · Markdown
            </label>
            <textarea
              id="project-info-editor"
              className="project-info-editor"
              autoFocus
              value={draft.content}
              maxLength={30000}
              disabled={saving}
              onChange={(e) =>
                rememberDraft({ ...draft, content: e.target.value })
              }
            />
            <div className="project-info-edit-footer">
              <span>
                {draft.content.length.toLocaleString("ru-RU")} / 30 000 ·
                черновик в браузере
              </span>
              <div className="inline">
                <button
                  className="secondary-button"
                  disabled={saving}
                  onClick={discard}
                >
                  Отмена
                </button>
                <button
                  className="primary-button"
                  disabled={saving || conflict}
                  onClick={() => void save()}
                >
                  {saving ? "Сохраняю…" : "Сохранить"}
                </button>
              </div>
            </div>
          </>
        ) : info.content ? (
          <MarkdownText text={info.content} />
        ) : (
          <div className="project-info-empty">
            <FileText size={30} />
            <h3>Здесь будет контекст вашего проекта</h3>
            <p>
              Расскажите о нём в чате. Агент соберёт сводку и будет дополнять её
              по ходу разговора. Можно заполнить её и вручную.
            </p>
            <button
              className="primary-button"
              disabled={busy}
              onClick={onInterview}
            >
              <MessageSquare size={16} />
              Описать в чате
            </button>
          </div>
        )}
      </div>
      {!editing && (
        <footer className="project-info-footer">
          <span>
            {info?.updated_at
              ? `Обновлено ${new Date(info.updated_at).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} · ${info.updated_by === "agent" ? "агентом" : "вами"}`
              : "Агент учитывает сводку в каждом запросе"}
          </span>
          {!!info?.content && (
            <button
              className="text-button"
              disabled={busy}
              onClick={onInterview}
            >
              <MessageSquare size={14} />
              Дополнить в чате
            </button>
          )}
        </footer>
      )}
    </aside>
  );
}
