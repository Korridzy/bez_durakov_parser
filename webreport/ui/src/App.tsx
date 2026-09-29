import { useCallback, useState } from "react";
import {
  BrowserRouter,
  NavLink,
  Navigate,
  Route,
  Routes,
  useParams,
} from "react-router-dom";

import { ChatList } from "./chats/ChatList";
import { ChatView } from "./chats/ChatView";
import { SavedReportsPage } from "./saved/SavedReportsPage";

function ChatsPage() {
  const { chatId } = useParams();
  // The sidebar reloads its list whenever the conversation created a chat or
  // finished a run (title, last message and report count change server-side).
  const [chatsVersion, setChatsVersion] = useState(0);
  const onChatsChanged = useCallback(() => setChatsVersion((n) => n + 1), []);
  return (
    <div className="chats-layout">
      <ChatList selectedChatId={chatId} refreshKey={chatsVersion} />
      <ChatView chatId={chatId} onChatsChanged={onChatsChanged} />
    </div>
  );
}

export function AppShell() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <p className="app-brand">Отчёты по данным</p>
        <nav className="app-tabs" aria-label="Разделы">
          <NavLink className="app-tab" to="/chats">
            Чаты
          </NavLink>
          <NavLink className="app-tab" to="/saved">
            Сохранённые отчёты
          </NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Navigate to="/chats" replace />} />
          <Route path="/chats" element={<ChatsPage />} />
          <Route path="/chats/:chatId" element={<ChatsPage />} />
          <Route path="/saved" element={<SavedReportsPage />} />
          <Route path="/saved/:reportId" element={<SavedReportsPage />} />
          <Route path="*" element={<Navigate to="/chats" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
