import { useState } from "react";
import {
  ChevronRight,
  Folder,
  FolderOpen,
  MoreHorizontal,
  PanelLeftClose,
  Plus,
  Search,
  Settings2,
  SquarePen,
} from "lucide-react";
import type { Chat, Project } from "./types";
import { Logo, Menu, MenuItem } from "./ui";

type Props = {
  visible: boolean;
  projects: Project[];
  chats: Chat[];
  projectId: string;
  chatId: string;
  onProject: (id: string) => void;
  onChat: (id: string) => void;
  onNewChat: (projectId?: string) => void;
  onNewProject: () => void;
  onSettings: () => void;
  onClose: () => void;
  onRename: (type: "projects" | "chats", id: string, name: string) => void;
  onDelete: (type: "projects" | "chats", id: string, name: string) => void;
  activeChatIds: string[];
};
export function Sidebar(p: Props) {
  const [collapsed, setCollapsed] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("wr-collapsed") || "[]");
    } catch {
      return [];
    }
  });
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [menu, setMenu] = useState("");
  const toggle = (id: string) => {
    const ids = collapsed.includes(id)
      ? collapsed.filter((i) => i !== id)
      : [...collapsed, id];
    setCollapsed(ids);
    localStorage.setItem("wr-collapsed", JSON.stringify(ids));
  };
  return (
    <aside className="sidebar" inert={!p.visible} aria-label="Проекты и чаты">
      <div className="sidebar-brand">
        <button className="brand" onClick={() => p.onNewChat()}>
          <Logo small />
          <span>
            Без дураков
            <span className="brand-caption">Аналитика в диалоге</span>
          </span>
        </button>
        <button
          className="icon-button subtle"
          aria-label="Свернуть боковую панель"
          onClick={p.onClose}
        >
          <PanelLeftClose size={18} />
        </button>
      </div>
      <div className="sidebar-top">
        <button className="new-chat" onClick={() => p.onNewChat()}>
          <SquarePen size={18} />
          Новый чат
        </button>
        <button
          className="sidebar-search"
          onClick={() => setSearchOpen(!searchOpen)}
        >
          <Search size={17} />
          <span>Поиск чатов</span>
        </button>
        {searchOpen && (
          <input
            autoFocus
            aria-label="Найти чат"
            className="search-input"
            placeholder="Название чата"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        )}
      </div>
      <div className="project-list">
        <div className="section-label">
          <span>Проекты</span>
          <button
            className="icon-button"
            aria-label="Создать проект"
            onClick={p.onNewProject}
          >
            <Plus size={17} />
          </button>
        </div>
        {p.projects.map((project) => {
          const children = p.chats.filter(
            (c) =>
              c.project_id === project.id &&
              c.name.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
          );
          const expanded = !collapsed.includes(project.id) || !!search;
          return (
            <div className="project-group" key={project.id}>
              <div
                className={
                  "project-row " +
                  (p.projectId === project.id ? "selected" : "")
                }
              >
                <button
                  className="project-toggle"
                  aria-label={
                    (expanded ? "Свернуть " : "Развернуть ") + project.name
                  }
                  aria-expanded={expanded}
                  onClick={() => {
                    toggle(project.id);
                    if (p.projectId !== project.id) p.onProject(project.id);
                  }}
                >
                  {expanded ? <FolderOpen size={18} /> : <Folder size={18} />}
                  <span className="project-name" title={project.name}>
                    {project.name}
                  </span>
                  <ChevronRight
                    className={"folder-chevron " + (expanded ? "expanded" : "")}
                    size={13}
                  />
                </button>
                <div className="row-actions">
                  <button
                    className="icon-button"
                    aria-label={"Новый чат в " + project.name}
                    onClick={() => p.onNewChat(project.id)}
                  >
                    <Plus size={16} />
                  </button>
                  <Menu
                    label={<MoreHorizontal size={16} />}
                    ariaLabel={"Меню проекта " + project.name}
                    open={menu === project.id}
                    onToggle={() =>
                      setMenu(menu === project.id ? "" : project.id)
                    }
                    onClose={() => setMenu("")}
                  >
                    <MenuItem
                      onClick={() => {
                        setMenu("");
                        p.onRename("projects", project.id, project.name);
                      }}
                    >
                      Переименовать
                    </MenuItem>
                    <MenuItem
                      onClick={() => {
                        setMenu("");
                        p.onDelete("projects", project.id, project.name);
                      }}
                    >
                      Удалить проект
                    </MenuItem>
                  </Menu>
                </div>
              </div>
              {expanded && (
                <div className="project-chats">
                  {children.map((chat) => (
                    <div
                      className={
                        "chat-row " + (p.chatId === chat.id ? "active" : "")
                      }
                      key={chat.id}
                    >
                      <button
                        className="chat-name"
                        onClick={() => p.onChat(chat.id)}
                        title={chat.name}
                      >
                        {p.activeChatIds.includes(chat.id) && (
                          <span className="working-dot" />
                        )}
                        {chat.name}
                      </button>
                      <Menu
                        label={<MoreHorizontal size={15} />}
                        ariaLabel={"Меню чата " + chat.name}
                        open={menu === chat.id}
                        onToggle={() =>
                          setMenu(menu === chat.id ? "" : chat.id)
                        }
                        onClose={() => setMenu("")}
                      >
                        <MenuItem
                          onClick={() => {
                            setMenu("");
                            p.onRename("chats", chat.id, chat.name);
                          }}
                        >
                          Переименовать
                        </MenuItem>
                        <MenuItem
                          onClick={() => {
                            setMenu("");
                            p.onDelete("chats", chat.id, chat.name);
                          }}
                        >
                          Удалить чат
                        </MenuItem>
                      </Menu>
                    </div>
                  ))}
                  {children.length === 0 && (
                    <button
                      className="empty-project"
                      onClick={() => p.onNewChat(project.id)}
                    >
                      <Plus size={14} />
                      {search ? "Нет совпадений" : "Новый чат"}
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
        <button className="add-project" onClick={p.onNewProject}>
          <Plus size={16} />
          Новый проект
        </button>
      </div>
      <button className="profile" onClick={p.onSettings}>
        <span className="avatar">Л</span>
        <span className="profile-text">
          <strong>Локальный профиль</strong>
          <span>Оформление и модели</span>
        </span>
        <Settings2 size={17} />
      </button>
    </aside>
  );
}
